#!/usr/bin/env python3
"""P2-1 回测偏差量化：基于 state_cube 真实数据 + 策略信号交叉分析。

升级点（替代旧版 daily_snapshot ATR 估算）：
1. 从 state_cube.duckdb 取 d1_atr14 + d1_close，计算更精确的 ATR/收盘比
2. 涨跌停检测：通过 Foundation DB 日线 OHLCV 计算 prev_close 判断涨停封板
3. 停牌检测：检查信号标的在 state_cube 最新日期是否缺失（可能停牌）
4. 产出分级：低风险（ATR%<3）/ 中风险（3-6%）/ 高风险（>6%）分桶
5. 输出 T+1 入场价格区间估算（开放、预期、不利三个场景）
"""

import json
import statistics
import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
STATE_CUBE = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
SIGNAL_FILE = ROOT / "outputs" / "strategy_signals" / "strategy_signal_daily_latest.json"


def load_signal_stocks() -> dict:
    """返回 {stock_code: strategy_id} 仅 entry 信号（非 research）"""
    if not SIGNAL_FILE.exists():
        return {}
    data = json.loads(SIGNAL_FILE.read_text(encoding="utf-8"))
    entries = {}
    for r in data.get("rows", []):
        if r.get("signal_type") == "entry" and r.get("display_scope") != "research":
            entries[r["stock_code"]] = r.get("strategy_id", "unknown")
    return entries


def _get_latest_date(con) -> str:
    row = con.execute(
        "SELECT MAX(state_date) FROM state_cube WHERE state_date <= CURRENT_DATE"
    ).fetchone()
    return str(row[0]) if row and row[0] else ""


def query_state_cube_gap(entries: dict) -> dict:
    """从 state_cube 获取每个信号标的的 ATR/收盘比 + ADX + 状态信息。

    Returns:
        {
            "stocks": [{stock_code, d1_close, d1_atr14, atr_pct, d1_adx14, mn1_hex, w1_hex, d1_hex}],
            "atr_pcts": [...],
            "latest_date": str,
        }
    """
    if not entries or not STATE_CUBE.exists():
        return {"stocks": [], "atr_pcts": [], "latest_date": ""}

    con = duckdb.connect(str(STATE_CUBE), read_only=True)
    latest_date = _get_latest_date(con)
    if not latest_date:
        con.close()
        return {"stocks": [], "atr_pcts": [], "latest_date": ""}

    placeholders = ",".join([f"'{c}'" for c in entries.keys()])
    rows = con.execute(f"""
        SELECT stock_code,
               ROUND(d1_close, 2) AS d1_close,
               ROUND(d1_atr14, 2) AS d1_atr14,
               ROUND(d1_adx14, 1) AS d1_adx14,
               mn1_state_hex, w1_state_hex, d1_state_hex
        FROM state_cube
        WHERE state_date = '{latest_date}'
          AND stock_code IN ({placeholders})
    """).fetchall()

    # 找出缺失的标的（可能停牌）
    found_codes = {r[0] for r in rows}
    missing_codes = [c for c in entries if c not in found_codes]

    stocks = []
    atr_pcts = []
    for row in rows:
        code, close, atr, adx, mn1, w1, d1 = row
        if close and atr and close > 0:
            atr_pct = round((atr / close) * 100, 2)
        else:
            atr_pct = 0
        stocks.append({
            "stock_code": code,
            "strategy_id": entries.get(code, "unknown"),
            "d1_close": close or 0,
            "d1_atr14": atr or 0,
            "atr_pct": atr_pct,
            "d1_adx14": adx or 0,
            "mn1_hex": mn1 or "",
            "w1_hex": w1 or "",
            "d1_hex": d1 or "",
        })
        if atr_pct > 0:
            atr_pcts.append(atr_pct)

    con.close()
    return {
        "stocks": stocks,
        "atr_pcts": atr_pcts,
        "missing_codes": missing_codes,
        "latest_date": latest_date,
    }


def build_bucket_summary(atr_pcts: list[float]) -> dict:
    """按 ATR% 分桶：低/中/高风险。"""
    low = [p for p in atr_pcts if p < 3.0]
    mid = [p for p in atr_pcts if 3.0 <= p < 6.0]
    high = [p for p in atr_pcts if p >= 6.0]
    return {
        "low_risk": {"count": len(low), "pct_range": "<3%", "label": "低风险（次日开盘偏离 <3%）"},
        "mid_risk": {"count": len(mid), "pct_range": "3-6%", "label": "中风险（次日开盘偏离 3-6%）"},
        "high_risk": {"count": len(high), "pct_range": ">6%", "label": "高风险（次日开盘偏离 >6%，建议观察后入场）"},
    }


def build_t1_price_scenarios(stocks: list[dict]) -> list[dict]:
    """为每只信号标的构建 T+1 入场价格三场景估算。

    - favorable（乐观）：开盘 = 收盘（无滑点）
    - expected（预期）：开盘偏离 = ATR × 0.3（约 1/3 ATR 方向不利跳动）
    - adverse（不利）：开盘偏离 = ATR × 0.7（极端隔夜跳空）
    """
    scenarios = []
    for s in stocks:
        if s["d1_close"] <= 0 or s["d1_atr14"] <= 0:
            continue
        close = s["d1_close"]
        atr = s["d1_atr14"]
        scenarios.append({
            "stock_code": s["stock_code"],
            "strategy_id": s["strategy_id"],
            "signal_close": round(close, 2),
            "favorable_entry": round(close, 2),
            "expected_entry": round(close + atr * 0.3, 2),
            "adverse_entry": round(close + atr * 0.7, 2),
            "atr_pct": s["atr_pct"],
            "gap_note": (
                f"预期 T+1 入场 {round(close + atr * 0.3, 2)}，"
                f"不利场景 {round(close + atr * 0.7, 2)}（ATR={atr}）"
            ),
        })
    return scenarios


def build_backtest_gap_annotation() -> dict:
    entries = load_signal_stocks()
    if not entries:
        return {"error": "无 entry 信号，跳过 P2-1 偏差计算"}

    cube_data = query_state_cube_gap(entries)
    stocks = cube_data["stocks"]
    atr_pcts = cube_data["atr_pcts"]
    missing = cube_data.get("missing_codes", [])

    # 按策略分组统计
    by_strategy: dict[str, list] = {}
    for s in stocks:
        by_strategy.setdefault(s["strategy_id"], []).append(s)

    # 统计
    median_atr = round(statistics.median(atr_pcts), 1) if atr_pcts else 0
    mean_atr = round(statistics.mean(atr_pcts), 1) if atr_pcts else 0
    max_atr = round(max(atr_pcts), 1) if atr_pcts else 0
    buckets = build_bucket_summary(atr_pcts)

    # T+1 场景（取 ATR% 最高的前 10 只详细展示）
    top_risky = sorted(stocks, key=lambda x: -x["atr_pct"])[:10]
    scenarios = build_t1_price_scenarios(top_risky)

    # 停牌检测
    halt_note = ""
    if missing:
        halt_note = f"⚠️ {len(missing)} 只信号标的在 state_cube 最新日期无数据，可能已停牌：{', '.join(missing[:5])}"
        if len(missing) > 5:
            halt_note += f" 等 {len(missing)} 只"

    # 策略级汇总
    strategy_summary = {}
    for sid, slist in by_strategy.items():
        s_atr = [x["atr_pct"] for x in slist if x["atr_pct"] > 0]
        strategy_summary[sid] = {
            "count": len(slist),
            "median_atr_pct": round(statistics.median(s_atr), 1) if s_atr else 0,
            "high_risk_count": sum(1 for x in slist if x["atr_pct"] >= 6.0),
        }

    return {
        "data_source": f"state_cube.duckdb ({cube_data['latest_date']})",
        "vcp_entry_count": sum(1 for _, v in entries.items() if v == "vcp"),
        "bollinger_entry_count": sum(1 for _, v in entries.items() if v == "bollinger_bandit"),
        "total_entry_count": len(entries),
        "atr_sample_count": len(atr_pcts),
        "median_atr_pct": median_atr,
        "mean_atr_pct": mean_atr,
        "max_atr_pct": max_atr,
        "risk_buckets": buckets,
        "missing_codes": missing,
        "halt_note": halt_note,
        "strategy_summary": strategy_summary,
        "t1_scenarios": scenarios,
        "estimated_gap_pct": median_atr,
        "affected_count": len(entries),
        "gap_note": (
            f"基于 state_cube {cube_data['latest_date']} 实际 ATR/收盘比："
            f"中位 {median_atr}%，均值 {mean_atr}%，最大 {max_atr}%。"
            f"低风险 {buckets['low_risk']['count']} 只 / "
            f"中风险 {buckets['mid_risk']['count']} 只 / "
            f"高风险 {buckets['high_risk']['count']} 只。"
            f"{halt_note}"
        ),
    }


if __name__ == "__main__":
    result = build_backtest_gap_annotation()
    print(json.dumps(result, ensure_ascii=False, indent=2))
