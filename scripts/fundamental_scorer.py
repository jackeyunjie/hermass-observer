#!/usr/bin/env python3
"""L2 基本面质量评分计算器。

计算核心 L2 因子：
1. 主业纯度 (core_business_purity) = 经营活动净收益／利润总额 (如果缺失则用营业利润/利润总额)
2. 现金含金量 (cash_quality) = 经营活动产生的现金流量净额 / 净利润
3. 盈利质量 (earnings_quality) = 扣除非经常损益后的归属母公司股东净利润／归属于母公司所有者的净利润
4. 资产安全 (asset_safety_ratio) = 1 - (负债合计 / 资产总计)

加权生成 quality_score (0-100)。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def score_core_business_purity(value: float | None) -> float | None:
    """Score operating-profit purity without rewarding denominator anomalies."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value < 0.5:
        return 0.0
    if value < 0.8:
        return (value - 0.5) / 0.3 * 100.0
    if value <= 1.5:
        return 100.0
    if value <= 3.0:
        return 100.0 - (value - 1.5) / 1.5 * 30.0
    return 50.0


def score_cash_quality(value: float | None) -> float | None:
    """CFO/net-profit is good near or above 1, but extreme values often mean tiny earnings."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value < 1.0:
        return value * 100.0
    if value <= 2.5:
        return 100.0
    if value <= 5.0:
        return 100.0 - (value - 2.5) / 2.5 * 25.0
    return 60.0


def score_earnings_quality(value: float | None) -> float | None:
    """Recurring-profit ratio above 0.9 is strong; extreme values get anomaly discount."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value < 0.5:
        return 0.0
    if value < 0.9:
        return (value - 0.5) / 0.4 * 100.0
    if value <= 1.5:
        return 100.0
    if value <= 3.0:
        return 85.0
    return 60.0


def score_asset_safety(value: float | None) -> float | None:
    if value is None:
        return None
    return min(100.0, max(0.0, (value - 0.2) / 0.4 * 100.0))


def init_schema():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fundamental_evidence_schema",
        str(ROOT / "scripts" / "fundamental_evidence_schema.py"))
    schema_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema_mod)
    schema_mod.init_schema(EVIDENCE_DB)

def run_scorer(date_str: str) -> dict:
    init_schema()
    con = duckdb.connect(str(EVIDENCE_DB))
    collected_at = datetime.now(timezone.utc).isoformat()
    
    # 获取所有的 facts
    con.execute("DROP TABLE IF EXISTS _temp_pivot_facts")
    con.execute("""
        CREATE TEMP TABLE _temp_pivot_facts AS
        SELECT stock_code, any_value(stock_name) as stock_name,
               MAX(CASE WHEN metric_name = '经营活动净收益／利润总额' THEN metric_value ELSE NULL END) as core_purity_raw,
               MAX(CASE WHEN metric_name = '营业利润' THEN metric_value ELSE NULL END) as op_profit,
               MAX(CASE WHEN metric_name = '利润总额' THEN metric_value ELSE NULL END) as total_profit,
               MAX(CASE WHEN metric_name = '经营活动产生的现金流量净额' THEN metric_value ELSE NULL END) as cfo,
               MAX(CASE WHEN metric_name = '净利润' THEN metric_value ELSE NULL END) as net_profit,
               MAX(CASE WHEN metric_name = '扣除非经常损益后的归属母公司股东净利润／归属于母公司所有者的净利润' THEN metric_value ELSE NULL END) as earn_quality_raw,
               MAX(CASE WHEN metric_name = '负债合计' THEN metric_value ELSE NULL END) as total_liab,
               MAX(CASE WHEN metric_name = '资产总计' THEN metric_value ELSE NULL END) as total_assets
        FROM ifind_excel_facts
        WHERE as_of_date = ?
        GROUP BY stock_code
    """, (date_str,))
    
    rows = con.execute("SELECT * FROM _temp_pivot_facts").fetchall()
    
    insert_data = []
    count = 0
    
    for row in rows:
        code = row[0]
        name = row[1]
        core_purity_raw = row[2]
        op_profit = row[3]
        total_profit = row[4]
        cfo = row[5]
        net_profit = row[6]
        earn_quality_raw = row[7]
        total_liab = row[8]
        total_assets = row[9]
        
        # 1. 主业纯度
        core_business_purity = None
        if core_purity_raw is not None:
            core_business_purity = float(core_purity_raw) / 100.0
        elif op_profit is not None and total_profit is not None and total_profit > 0:
            core_business_purity = op_profit / total_profit
            
        # 2. 现金含金量
        cash_quality = None
        if cfo is not None and net_profit is not None and net_profit > 0:
            cash_quality = cfo / net_profit
            
        # 3. 盈利质量
        earnings_quality = None
        if earn_quality_raw is not None:
            earnings_quality = float(earn_quality_raw) / 100.0
            
        # 4. 资产安全
        asset_safety_ratio = None
        if total_liab is not None and total_assets is not None and total_assets > 0:
            asset_safety_ratio = 1.0 - (total_liab / total_assets)
            
        # 计算打分 0-100
        # 假设：
        # 主业纯度 > 0.8 满分，< 0.5 零分
        # 现金含金量 > 1.0 满分，< 0 零分
        # 盈利质量 > 0.9 满分，< 0.5 零分
        # 资产安全 > 0.6 满分，< 0.2 零分
        
        score_components = [
            score_core_business_purity(core_business_purity),
            score_cash_quality(cash_quality),
            score_earnings_quality(earnings_quality),
            score_asset_safety(asset_safety_ratio),
        ]
        scores = [s for s in score_components if s is not None]
            
        raw_quality_score = sum(scores) / len(scores) if scores else 0.0
        data_coverage = len(scores) / 4.0
        quality_score = raw_quality_score * data_coverage
        final_fundamental_score = quality_score # TODO: 结合成长性等其他因子
        
        insert_data.append((
            code, date_str, name,
            core_business_purity, cash_quality, earnings_quality, asset_safety_ratio,
            quality_score, final_fundamental_score, collected_at
        ))
        count += 1
        
    con.execute("BEGIN")
    con.executemany("""
        INSERT OR REPLACE INTO fundamental_quality_score
        (stock_code, as_of_date, stock_name, 
         core_business_purity, cash_quality, earnings_quality, asset_safety_ratio,
         quality_score, final_fundamental_score, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, insert_data)
    con.execute("COMMIT")
    
    # 写回 evidence packet 供 L3 LLM 使用
    ev_data = []
    for d in insert_data:
        code = d[0]
        purity_str = f"{d[3]:.2f}" if d[3] is not None else "N/A"
        cash_str = f"{d[4]:.2f}" if d[4] is not None else "N/A"
        earn_str = f"{d[5]:.2f}" if d[5] is not None else "N/A"
        safe_str = f"{d[6]:.2f}" if d[6] is not None else "N/A"
        text = (
            f"L2 Fundamental Quality Score (0-100):\n"
            f"- 综合质量得分: {d[7]:.1f}\n"
            f"- 有效指标覆盖: {sum(x is not None for x in d[3:7])}/4\n"
            f"- 主业纯度 (core_business_purity): {purity_str}\n"
            f"- 现金含金量 (cash_quality): {cash_str}\n"
            f"- 盈利质量 (earnings_quality): {earn_str}\n"
            f"- 资产安全度 (asset_safety_ratio): {safe_str}"
        )
        ev_data.append((
            f"l2_quality_score_{code}_{date_str.replace('-','')}",
            code, date_str, 'l2_quality_score', text,
            'iFind', 'Python_L2_Scorer', 'fundamental_quality_score', 'MRQ', 1.0, collected_at
        ))
    
    con.execute("BEGIN")
    con.executemany("""
        INSERT OR REPLACE INTO fundamental_evidence_packet
        (evidence_id, stock_code, as_of_date, evidence_type, evidence_text,
         source_vendor, source_api, source_query, source_period, confidence, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ev_data)
    con.execute("COMMIT")
    
    con.close()
    
    return {
        "status": "success",
        "date": date_str,
        "stocks_scored": count,
        "generated_at": collected_at
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Compute L2 Fundamental Quality Score")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    result = run_scorer(args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
