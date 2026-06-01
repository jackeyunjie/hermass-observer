#!/usr/bin/env python3
"""
rebuild_macro_scores.py  —  宏观四维评分重建

基于 macro_indicator_data.duckdb 中的 7 个指标历史序列，按四维模型计算：
    growth_score, liquidity_score, credit_score, inflation_score
合成宏观象限（复苏/过热/滞胀/衰退），计算策略加成系数，更新 macro_prior。

用法：
    source .venv/bin/activate && python3 scripts/rebuild_macro_scores.py --date 2026-05-23

产出：
    - outputs/macro_chain_prior/macro_chain_prior_YYYYMMDD.json
    - outputs/macro_chain_prior/macro_chain_prior_latest.json
    - outputs/macro/macro_indicator_data.duckdb (macro_prior 表)
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MACRO_DB = ROOT / "outputs" / "macro" / "macro_indicator_data.duckdb"
DEFAULT_OUT_DIR = ROOT / "outputs" / "macro_chain_prior"
DEFAULT_MACRO_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"

# ── 指标配置 ──────────────────────────────────────────
# 指标编码 → 维度、权重、类型（normal / rate / inflation）
INDICATOR_CONFIG: dict[str, dict[str, Any]] = {
    "AK:macro_china_pmi_yearly": {
        "name": "制造业PMI",
        "dimension": "growth",
        "weight": 0.50,
        "type": "normal",
        "frequency": "monthly",
    },
    "AK:macro_china_industrial": {
        "name": "工业增加值:当月同比",
        "dimension": "growth",
        "weight": 0.30,
        "type": "normal",
        "frequency": "monthly",
    },
    "AK:macro_china_gdp": {
        "name": "GDP:累计同比",
        "dimension": "growth",
        "weight": 0.20,
        "type": "normal",
        "frequency": "quarterly",
    },
    "AK:bond_10y": {
        "name": "中债国债到期收益率:10年",
        "dimension": "liquidity",
        "weight": 0.70,
        "type": "rate",
        "frequency": "daily",
    },
    "AK:macro_china_lpr": {
        "name": "1年期LPR",
        "dimension": "liquidity",
        "weight": 0.30,
        "type": "rate",
        "frequency": "monthly",
    },
    "AK:macro_china_cpi_yearly": {
        "name": "CPI:当月同比",
        "dimension": "inflation",
        "weight": 0.50,
        "type": "inflation",
        "frequency": "monthly",
    },
    "AK:macro_china_ppi_yearly": {
        "name": "PPI:当月同比",
        "dimension": "inflation",
        "weight": 0.50,
        "type": "inflation",
        "frequency": "monthly",
    },
}

# ── 维度总权重 ──────────────────────────────────────────
DIMENSION_WEIGHTS = {
    "growth": 0.30,
    "liquidity": 0.30,
    "credit": 0.25,
    "inflation": 0.15,
}

# ── 策略加成权重 ────────────────────────────────────────
STRATEGY_WEIGHTS = {
    "vcp": {"growth": 0.30, "liquidity": 0.35, "credit": 0.20, "inflation": 0.15},
    "ma2560": {"growth": 0.20, "liquidity": 0.25, "credit": 0.35, "inflation": 0.20},
    "bollinger_bandit": {"growth": 0.25, "liquidity": 0.35, "credit": 0.20, "inflation": 0.20},
}


def clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, value))


def load_indicator_history(db_path: Path, indicator_code: str) -> pd.DataFrame:
    """读取单个指标的历史数据。"""
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute(
        """
        SELECT as_of_date, value
        FROM macro_indicator_history
        WHERE indicator_code = ?
        ORDER BY as_of_date
        """,
        (indicator_code,),
    ).fetchdf()
    con.close()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    df = df.dropna(subset=["value"])
    return df


def compute_percentile(current: float, history: list[float]) -> float:
    """计算当前值在历史序列中的百分位（0-100）。"""
    if not history:
        return 50.0
    below = sum(1 for v in history if v < current)
    return below / len(history) * 100.0


def compute_trend_score(values: list[float], indicator_type: str) -> float:
    """基于近 3 期数据计算趋势分（0-10）。"""
    if len(values) < 3:
        return 5.0

    v0, v1, v2 = values[-1], values[-2], values[-3]
    delta_1 = v0 - v1
    delta_2 = v1 - v2
    acceleration = delta_1 - delta_2

    # 利率类：下行 = 正面（宽松）
    if indicator_type == "rate":
        delta_1 = -delta_1  # 反转
        acceleration = -acceleration

    if delta_1 > 0 and acceleration >= 0:
        return 8.0
    if delta_1 > 0 and acceleration < 0:
        return 6.5
    if delta_1 == 0:
        return 5.0
    if delta_1 < 0 and acceleration <= 0:
        return 2.0
    if delta_1 < 0 and acceleration > 0:
        return 3.5
    return 5.0


def compute_level_score(current: float, history: list[float], indicator_type: str) -> float:
    """计算水平分（0-10）。"""
    if not history:
        return 5.0

    percentile = compute_percentile(current, history)

    if indicator_type == "rate":
        # 利率类：低分位（低利率）= 宽松 = 高分
        return clamp(10.0 - percentile / 10.0)
    elif indicator_type == "inflation":
        # 通胀类：舒适区间映射
        # 简化：使用分位映射，但中间分位给高分
        # 0-20% → 2-4, 20-40% → 4-6, 40-60% → 6-8, 60-80% → 5-7, 80-100% → 2-5
        if percentile <= 20:
            return 3.0 + percentile / 20 * 1.0
        elif percentile <= 40:
            return 4.0 + (percentile - 20) / 20 * 2.0
        elif percentile <= 60:
            return 6.0 + (percentile - 40) / 20 * 2.0
        elif percentile <= 80:
            return 8.0 - (percentile - 60) / 20 * 3.0
        else:
            return 5.0 - (percentile - 80) / 20 * 3.0
    else:
        # 正常类：高分位 = 高分
        return clamp(percentile / 10.0)


def compute_indicator_score(
    current: float,
    history: list[float],
    indicator_type: str,
) -> dict[str, float]:
    """计算单指标的综合评分。"""
    level = compute_level_score(current, history, indicator_type)
    trend = compute_trend_score(history + [current], indicator_type)

    if indicator_type == "inflation":
        # 通胀类：level 权重更高，因为舒适区间更重要
        score = level * 0.7 + trend * 0.3
    else:
        score = level * 0.6 + trend * 0.4

    return {
        "level_score": round(level, 2),
        "trend_score": round(trend, 2),
        "indicator_score": round(clamp(score), 2),
        "percentile": round(compute_percentile(current, history), 1),
        "history_count": len(history),
    }


def compute_dimension_score(
    dimension: str,
    indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算单个维度的评分。"""
    if not indicators:
        return {
            "score": 5.0,
            "confidence": 0.0,
            "status": "data_insufficient",
            "indicators_used": 0,
            "indicators_total": len([c for c in INDICATOR_CONFIG.values() if c["dimension"] == dimension]),
            "evidence": [f"{dimension} 维度无可用指标数据"],
        }

    weighted_sum = 0.0
    weight_total = 0.0
    evidence: list[str] = []
    history_counts: list[int] = []

    for ind in indicators:
        w = ind["weight"]
        s = ind["indicator_score"]
        weighted_sum += s * w
        weight_total += w
        history_counts.append(ind["history_count"])
        evidence.append(
            f"{ind['name']}={ind['latest_value']}"
            f"(分位{ind['percentile']}%,水平{ind['level_score']},趋势{ind['trend_score']})"
        )

    score = clamp(weighted_sum / weight_total) if weight_total > 0 else 5.0

    # 置信度
    total_expected = len([c for c in INDICATOR_CONFIG.values() if c["dimension"] == dimension])
    coverage = len(indicators) / max(1, total_expected)
    avg_history = sum(history_counts) / len(history_counts) if history_counts else 0
    history_factor = min(1.0, avg_history / 24)
    confidence = round(min(1.0, coverage * history_factor * 0.9), 4)

    status = "ok" if confidence >= 0.7 else ("partial" if confidence >= 0.3 else "data_insufficient")

    return {
        "score": round(score, 2),
        "confidence": confidence,
        "status": status,
        "indicators_used": len(indicators),
        "indicators_total": total_expected,
        "evidence": evidence,
    }


def classify_quadrant(
    S_growth: float, S_liquidity: float, S_credit: float, S_inflation: float
) -> dict[str, Any]:
    """四象限判定。"""
    growth_cycle = 0.60 * S_growth + 0.40 * S_inflation
    money_credit_cycle = 0.55 * S_liquidity + 0.45 * S_credit

    if growth_cycle >= 5.0 and money_credit_cycle >= 5.5:
        quadrant = "复苏"
    elif growth_cycle >= 5.0 and money_credit_cycle < 5.5:
        quadrant = "过热"
    elif growth_cycle < 5.0 and money_credit_cycle >= 5.5:
        quadrant = "衰退"
    else:
        quadrant = "滞胀"

    return {
        "name": quadrant,
        "growth_cycle": round(growth_cycle, 2),
        "money_credit_cycle": round(money_credit_cycle, 2),
    }


def compute_strategy_adj(sub_scores: dict[str, float]) -> dict[str, float]:
    """计算各策略的宏观加成系数。"""
    result: dict[str, float] = {}
    for strategy, weights in STRATEGY_WEIGHTS.items():
        total = 0.0
        for dim, weight in weights.items():
            normalized = (sub_scores.get(dim, 5.0) - 5.0) / 5.0
            total += normalized * weight
        result[strategy] = round(total * 15, 2)
    return result


def overall_confidence(dimensions: dict[str, dict[str, Any]]) -> float:
    """计算总体置信度。"""
    confidences = [d["confidence"] for d in dimensions.values()]
    weights = [DIMENSION_WEIGHTS.get(dim, 0.25) for dim in dimensions.keys()]
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return round(sum(c * w for c, w in zip(confidences, weights)) / total_weight, 4)


def build_macro_scores(date_str: str, db_path: Path) -> dict[str, Any]:
    """构建宏观四维评分。"""
    # 1. 读取并计算每个指标
    indicators_by_dim: dict[str, list[dict]] = defaultdict(list)
    data_gaps: list[str] = []

    for code, cfg in INDICATOR_CONFIG.items():
        df = load_indicator_history(db_path, code)
        if df.empty or len(df) < 2:
            data_gaps.append(f"{cfg['name']}({code}): 数据不足")
            continue

        values = df["value"].tolist()
        current = values[-1]
        history = values[:-1]

        result = compute_indicator_score(current, history, cfg["type"])
        result.update(
            {
                "code": code,
                "name": cfg["name"],
                "dimension": cfg["dimension"],
                "weight": cfg["weight"],
                "latest_value": current,
                "latest_date": df["as_of_date"].iloc[-1].strftime("%Y-%m-%d"),
            }
        )
        indicators_by_dim[cfg["dimension"]].append(result)

    # 2. 计算四维评分
    dimensions = {}
    for dim in ["growth", "liquidity", "credit", "inflation"]:
        dimensions[dim] = compute_dimension_score(dim, indicators_by_dim.get(dim, []))

    sub_scores = {dim: d["score"] for dim, d in dimensions.items()}

    # 3. 合成总评分
    total_score = sum(
        sub_scores.get(dim, 5.0) * DIMENSION_WEIGHTS.get(dim, 0.25) for dim in dimensions.keys()
    ) / sum(DIMENSION_WEIGHTS.get(dim, 0.25) for dim in dimensions.keys())

    # 4. 象限
    quadrant = classify_quadrant(
        sub_scores.get("growth", 5.0),
        sub_scores.get("liquidity", 5.0),
        sub_scores.get("credit", 5.0),
        sub_scores.get("inflation", 5.0),
    )

    # 5. 策略加成
    strategy_adj = compute_strategy_adj(sub_scores)

    # 6. 置信度
    confidence = overall_confidence(dimensions)

    # 7. display_level
    if confidence >= 0.7:
        display_level = "full"
    elif confidence >= 0.5:
        display_level = "partial"
    elif confidence >= 0.3:
        display_level = "minimal"
    else:
        display_level = "insufficient"

    # 8. 证据摘要
    evidence = []
    for dim, d in dimensions.items():
        if d["status"] != "data_insufficient":
            evidence.append(f"{dim}: {d['score']}/10 ({d['status']}, conf={d['confidence']})")

    return {
        "schema_version": "macro_prior_v2",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score_0_10": round(total_score, 2),
        "sub_scores": {
            dim: {
                "score": d["score"],
                "confidence": d["confidence"],
                "indicators_used": d["indicators_used"],
                "indicators_total": d["indicators_total"],
                "status": d["status"],
                "evidence": d["evidence"],
            }
            for dim, d in dimensions.items()
        },
        "quadrant": quadrant,
        "confidence": confidence,
        "display_level": display_level,
        "strategy_adj": strategy_adj,
        "evidence": evidence,
        "data_gaps": data_gaps,
        "research_only": True,
    }


def write_macro_prior_db(db_path: Path, payload: dict[str, Any]) -> None:
    """写入 macro_prior 表。"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS macro_prior (
            date VARCHAR PRIMARY KEY,
            score_0_10 DOUBLE,
            growth_score DOUBLE,
            growth_confidence DOUBLE,
            liquidity_score DOUBLE,
            liquidity_confidence DOUBLE,
            credit_score DOUBLE,
            credit_confidence DOUBLE,
            inflation_score DOUBLE,
            inflation_confidence DOUBLE,
            quadrant VARCHAR,
            growth_cycle DOUBLE,
            money_credit_cycle DOUBLE,
            overall_confidence DOUBLE,
            display_level VARCHAR,
            strategy_adj_vcp DOUBLE,
            strategy_adj_ma2560 DOUBLE,
            strategy_adj_bollinger DOUBLE,
            payload_json VARCHAR,
            generated_at VARCHAR
        )
    """)

    sub = payload.get("sub_scores", {})
    con.execute(
        """
        INSERT OR REPLACE INTO macro_prior VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            payload["date"],
            payload["score_0_10"],
            sub.get("growth", {}).get("score"),
            sub.get("growth", {}).get("confidence"),
            sub.get("liquidity", {}).get("score"),
            sub.get("liquidity", {}).get("confidence"),
            sub.get("credit", {}).get("score"),
            sub.get("credit", {}).get("confidence"),
            sub.get("inflation", {}).get("score"),
            sub.get("inflation", {}).get("confidence"),
            payload.get("quadrant", {}).get("name"),
            payload.get("quadrant", {}).get("growth_cycle"),
            payload.get("quadrant", {}).get("money_credit_cycle"),
            payload["confidence"],
            payload["display_level"],
            payload.get("strategy_adj", {}).get("vcp"),
            payload.get("strategy_adj", {}).get("ma2560"),
            payload.get("strategy_adj", {}).get("bollinger_bandit"),
            json.dumps(payload, ensure_ascii=False, default=str),
            payload["generated_at"],
        ),
    )
    con.close()
    print(f"[OK] 写入 macro_prior 表: {db_path}")


def generate_report(payload: dict[str, Any]) -> Path:
    """生成 Markdown 报告。"""
    date_str = payload["date"]
    report_path = DEFAULT_OUT_DIR / f"macro_scores_report_{date_str.replace('-', '')}.md"
    DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# 宏观四维评分报告 ({date_str})",
        "",
        f"生成时间: {payload['generated_at']}",
        f"模型版本: {payload['schema_version']}",
        f"置信度: {payload['confidence']} ({payload['display_level']})",
        "",
        "## 1. 总体评分",
        "",
        f"**宏观综合评分**: {payload['score_0_10']} / 10",
        f"**宏观象限**: {payload['quadrant']['name']}",
        f"- 增长周期轴: {payload['quadrant']['growth_cycle']}",
        f"- 货币信用轴: {payload['quadrant']['money_credit_cycle']}",
        "",
        "## 2. 四维子评分",
        "",
        "| 维度 | 评分 | 置信度 | 状态 | 使用指标 | 预期指标 |",
        "|------|------|--------|------|----------|----------|",
    ]

    for dim in ["growth", "liquidity", "credit", "inflation"]:
        sub = payload.get("sub_scores", {}).get(dim, {})
        lines.append(
            f"| {dim} | {sub.get('score', 'N/A')} | {sub.get('confidence', 'N/A')} | "
            f"{sub.get('status', 'N/A')} | {sub.get('indicators_used', 0)} | {sub.get('indicators_total', 0)} |"
        )

    lines.extend(
        [
            "",
            "## 3. 策略加成系数",
            "",
            "| 策略 | 加成系数 |",
            "|------|----------|",
        ]
    )
    for strategy, adj in payload.get("strategy_adj", {}).items():
        lines.append(f"| {strategy} | {adj:+.2f} |")

    lines.extend(
        [
            "",
            "## 4. 数据缺口",
            "",
        ]
    )
    for gap in payload.get("data_gaps", []):
        lines.append(f"- {gap}")

    if not payload.get("data_gaps"):
        lines.append("- 无显著数据缺口")

    lines.extend(
        [
            "",
            "## 5. 证据摘要",
            "",
        ]
    )
    for ev in payload.get("evidence", []):
        lines.append(f"- {ev}")

    lines.extend(
        [
            "",
            "---",
            "*报告由 rebuild_macro_scores.py 自动生成*",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 报告已生成: {report_path}")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="宏观四维评分重建")
    parser.add_argument(
        "--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="基准日期 YYYY-MM-DD"
    )
    parser.add_argument("--db", default=str(DEFAULT_MACRO_DB), help="宏观指标 DuckDB 路径")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅计算不写入")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out_dir)
    date_str = args.date

    print("=" * 60)
    print("宏观四维评分重建")
    print(f"日期: {date_str}")
    print("=" * 60)

    if not db_path.exists():
        print(f"[ERROR] 宏观数据库不存在: {db_path}")
        return 1

    payload = build_macro_scores(date_str, db_path)

    print(f"\n[RESULT] 宏观综合评分: {payload['score_0_10']}/10")
    print(f"[RESULT] 象限: {payload['quadrant']['name']}")
    print(f"[RESULT] 置信度: {payload['confidence']} ({payload['display_level']})")
    for dim, sub in payload.get("sub_scores", {}).items():
        print(f"  {dim}: {sub['score']}/10 (conf={sub['confidence']}, {sub['status']})")
    print(
        f"[RESULT] 策略加成: VCP={payload['strategy_adj']['vcp']:+.2f}, "
        f"MA2560={payload['strategy_adj']['ma2560']:+.2f}, "
        f"Bollinger={payload['strategy_adj']['bollinger_bandit']:+.2f}"
    )

    if not args.dry_run:
        # 写入 JSON
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"macro_chain_prior_{date_str.replace('-', '')}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        shutil.copy2(str(json_path), str(out_dir / "macro_chain_prior_latest.json"))
        print(f"[OK] JSON 输出: {json_path}")

        # 写入数据库
        write_macro_prior_db(db_path, payload)

        # 生成报告
        generate_report(payload)
    else:
        print("[DRY-RUN] 计算完成，不写入文件")

    print("=" * 60)
    print("宏观评分重建完成")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
