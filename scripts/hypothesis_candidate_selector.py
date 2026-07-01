#!/usr/bin/env python3
"""Hypothesis Candidate Selector — 假设验证候选提取器。

Phase 2 核心组件。从 State Cube 中按窄假设提取候选：
  假设: D1_CONTRACTION_BREAKOUT_OBSERVATION
  条件:
    1. W1 趋势未坏（W1 MA state 非空头排列 W5/W6）
    2. D1 波动收缩（BB20 width = squeeze，或 ATR14 处于低位）
    3. D1 靠近上轨/边界（BB20 position = above_upper 或 above_middle）
    4. 排除明显数据缺失

输出: JSONL 到 outputs/hypothesis_candidates/

Usage:
    .venv/bin/python scripts/hypothesis_candidate_selector.py \
        --date 2026-06-05 \
        --hypothesis D1_CONTRACTION_BREAKOUT_OBSERVATION \
        --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_CUBE = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
OUTPUT_DIR = ROOT / "outputs" / "hypothesis_candidates"

HYPOTHESIS_ID = "D1_CONTRACTION_BREAKOUT_OBSERVATION"


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _build_filter_sql(hypothesis_id: str) -> str:
    """返回该假设的筛选 SQL WHERE 子句。"""
    if hypothesis_id == "D1_CONTRACTION_BREAKOUT_OBSERVATION":
        return """
            -- W1 趋势未坏：排除 W5(空头排列)、W6(空头排列)
            AND (w1_ma_state IS NULL OR w1_ma_state NOT IN ('W5', 'W6'))
            -- D1 波动收缩：BB20 width 为 squeeze
            AND d1_bb20_width = 'squeeze'
            -- D1 靠近上轨/边界：BB20 position 在 above_upper 或 above_middle
            AND d1_bb20_position IN ('above_upper', 'above_middle')
            -- 排除明显数据缺失
            AND d1_close IS NOT NULL
            AND w1_close IS NOT NULL
            AND d1_atr14 IS NOT NULL
            AND d1_adx14 IS NOT NULL
        """
    raise ValueError(f"不支持的假设: {hypothesis_id}")


def _build_evidence_fields(row: dict[str, Any]) -> dict[str, Any]:
    """为候选生成证据字段。"""
    return {
        "w1_trend_status": {
            "w1_state_hex": row.get("w1_state_hex"),
            "w1_ma_state": row.get("w1_ma_state"),
            "w1_bb20_position": row.get("w1_bb20_position"),
            "w1_bb20_width": row.get("w1_bb20_width"),
            "w1_adx14": row.get("w1_adx14"),
        },
        "d1_contraction_status": {
            "d1_state_hex": row.get("d1_state_hex"),
            "d1_ma_state": row.get("d1_ma_state"),
            "d1_bb20_position": row.get("d1_bb20_position"),
            "d1_bb20_width": row.get("d1_bb20_width"),
            "d1_atr14": row.get("d1_atr14"),
            "d1_adx14": row.get("d1_adx14"),
        },
        "boundary_proximity": {
            "d1_close": row.get("d1_close"),
            "d1_bb20_position": row.get("d1_bb20_position"),
            "d1_bb50_position": row.get("d1_bb50_position"),
        },
        "m30_snapshot": {
            "m30_close": row.get("m30_close"),
            "m30_bb20_position": row.get("m30_bb20_position"),
            "m30_bb20_width": row.get("m30_bb20_width"),
            "m30_atr14": row.get("m30_atr14"),
            "m30_adx14": row.get("m30_adx14"),
            "m30_adx_slope_3": row.get("m30_adx_slope_3"),
            "m30_breakout_signal": row.get("m30_breakout_signal"),
            "m30_price_breakout": row.get("m30_price_breakout"),
        },
    }


def _build_data_quality_flags(row: dict[str, Any]) -> list[str]:
    """检查数据质量标记。"""
    flags = []
    if row.get("m30_close") is None:
        flags.append("m30_data_missing")
    if row.get("w1_bb20_position") is None or row.get("w1_bb20_width") is None:
        flags.append("w1_bb_data_incomplete")
    if row.get("d1_bb50_position") is None:
        flags.append("d1_bb50_missing")
    if row.get("future_r5") is None:
        flags.append("future_r5_not_yet_available")
    if row.get("future_r20") is None:
        flags.append("future_r20_not_yet_available")
    if not flags:
        flags.append("data_complete")
    return flags


def _build_candidate_reason(row: dict[str, Any]) -> str:
    """生成候选原因描述。"""
    parts = []
    w1_ma = row.get("w1_ma_state", "")
    d1_bb_pos = row.get("d1_bb20_position", "")
    d1_bb_width = row.get("d1_bb20_width", "")
    d1_hex = row.get("d1_state_hex", "")
    w1_hex = row.get("w1_state_hex", "")

    if w1_ma in ("W1", "W2", "W3"):
        parts.append(f"W1多头排列({w1_ma})")
    elif w1_ma == "W7":
        parts.append(f"W1均线粘合({w1_ma})")
    elif w1_ma == "W4":
        parts.append(f"W1震荡({w1_ma})")
    else:
        parts.append(f"W1趋势未坏({w1_hex})")

    if d1_bb_width == "squeeze":
        parts.append("D1波动收缩(squeeze)")

    if d1_bb_pos == "above_upper":
        parts.append("D1突破上轨")
    elif d1_bb_pos == "above_middle":
        parts.append("D1位于中轨上方")

    if d1_hex and d1_hex[0] in ("E", "F"):
        parts.append(f"D1正向状态({d1_hex})")
    elif d1_hex and d1_hex[0] in ("A", "B"):
        parts.append(f"D1蓄势状态({d1_hex})")

    return "；".join(parts)


def select_candidates(
    target_date: str,
    hypothesis_id: str = HYPOTHESIS_ID,
    limit: int = 100,
    state_cube_db: str = "",
) -> dict[str, Any]:
    """从 State Cube 提取假设候选。

    Returns:
        dict: 包含候选列表、统计信息、输出路径
    """
    db_path = state_cube_db or str(DEFAULT_STATE_CUBE)
    if not Path(db_path).exists():
        return {"status": "error", "errors": [f"State Cube DB 不存在: {db_path}"]}

    filter_sql = _build_filter_sql(hypothesis_id)

    con = duckdb.connect(db_path, read_only=True)

    # 检查表存在
    tables = con.execute("SHOW TABLES").fetchdf()
    if "state_cube" not in tables["name"].values:
        con.close()
        return {"status": "error", "errors": ["state_cube 表不存在"]}

    # 查询候选
    sql = f"""
        SELECT
            stock_code,
            state_date,
            mn1_state_hex,
            w1_state_hex,
            d1_state_hex,
            ef_count,
            w1_ma_state,
            d1_ma_state,
            w1_bb20_position,
            w1_bb20_width,
            d1_bb20_position,
            d1_bb20_width,
            w1_bb50_position,
            d1_bb50_position,
            w1_atr14,
            d1_atr14,
            w1_adx14,
            d1_adx14,
            w1_plus_di_14,
            d1_plus_di_14,
            w1_minus_di_14,
            d1_minus_di_14,
            d1_close,
            w1_close,
            m30_close,
            m30_bb20_position,
            m30_bb20_width,
            m30_atr14,
            m30_adx14,
            m30_adx_slope_3,
            m30_breakout_signal,
            m30_price_breakout,
            m30_ma20_ready,
            m30_close_vs_ma20_flag,
            future_r5,
            future_r20
        FROM state_cube
        WHERE state_date = DATE '{target_date}'
          {filter_sql}
        ORDER BY ef_count DESC, d1_adx14 DESC, stock_code
        LIMIT {limit}
    """

    df = con.execute(sql).fetchdf()
    con.close()

    candidates: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record = row.to_dict()
        candidate = {
            "stock_code": record["stock_code"],
            "state_date": str(record["state_date"]),
            "hypothesis_id": hypothesis_id,
            "snapshot": {
                "mn1_state_hex": record.get("mn1_state_hex"),
                "w1_state_hex": record.get("w1_state_hex"),
                "d1_state_hex": record.get("d1_state_hex"),
                "ef_count": record.get("ef_count"),
                "w1_ma_state": record.get("w1_ma_state"),
                "d1_ma_state": record.get("d1_ma_state"),
                "d1_bb20_position": record.get("d1_bb20_position"),
                "d1_bb20_width": record.get("d1_bb20_width"),
                "d1_atr14": record.get("d1_atr14"),
                "d1_adx14": record.get("d1_adx14"),
                "d1_close": record.get("d1_close"),
                "w1_close": record.get("w1_close"),
                "m30_close": record.get("m30_close"),
                "future_r5": record.get("future_r5"),
                "future_r20": record.get("future_r20"),
            },
            "candidate_reason": _build_candidate_reason(record),
            "evidence_fields": _build_evidence_fields(record),
            "data_quality_flags": _build_data_quality_flags(record),
        }
        candidates.append(candidate)

    _ensure_output_dir()
    ymd = target_date.replace("-", "")
    output_path = OUTPUT_DIR / f"{hypothesis_id}_{ymd}.jsonl"

    with open(output_path, "w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

    # 统计
    ef_dist: dict[str, int] = {}
    w1_ma_dist: dict[str, int] = {}
    d1_pos_dist: dict[str, int] = {}
    for c in candidates:
        ef = str(c["snapshot"].get("ef_count", "unknown"))
        ef_dist[ef] = ef_dist.get(ef, 0) + 1
        w1 = str(c["snapshot"].get("w1_ma_state", "unknown"))
        w1_ma_dist[w1] = w1_ma_dist.get(w1, 0) + 1
        d1 = str(c["snapshot"].get("d1_bb20_position", "unknown"))
        d1_pos_dist[d1] = d1_pos_dist.get(d1, 0) + 1

    result = {
        "status": "ok",
        "hypothesis_id": hypothesis_id,
        "target_date": target_date,
        "candidate_count": len(candidates),
        "limit": limit,
        "output_path": str(output_path),
        "statistics": {
            "ef_count_distribution": ef_dist,
            "w1_ma_state_distribution": w1_ma_dist,
            "d1_bb20_position_distribution": d1_pos_dist,
        },
        "candidates": candidates,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # 同时写入一个精简的 JSON 摘要（供下游脚本快速读取）
    summary_path = OUTPUT_DIR / f"{hypothesis_id}_{ymd}_summary.json"
    summary = {
        "status": "ok",
        "hypothesis_id": hypothesis_id,
        "target_date": target_date,
        "candidate_count": len(candidates),
        "output_path": str(output_path),
        "statistics": result["statistics"],
        "generated_at": result["generated_at"],
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Hypothesis Candidate Selector")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--hypothesis", default=HYPOTHESIS_ID, help="假设 ID")
    parser.add_argument("--limit", type=int, default=100, help="候选数量上限")
    parser.add_argument("--state-cube", default="", help="State Cube DB 路径")
    parser.add_argument("--output", default="", help="输出 JSON 路径（覆盖默认）")
    args = parser.parse_args()

    result = select_candidates(
        target_date=args.date,
        hypothesis_id=args.hypothesis,
        limit=args.limit,
        state_cube_db=args.state_cube,
    )

    if result.get("status") != "ok":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1

    print(f"=== Candidate Selector: {args.date} ===")
    print(f"假设: {args.hypothesis}")
    print(f"候选数量: {result['candidate_count']} / limit={args.limit}")
    print(f"输出: {result['output_path']}")
    print(f"\n统计:")
    print(f"  ef_count 分布: {result['statistics']['ef_count_distribution']}")
    print(f"  W1 MA 分布: {result['statistics']['w1_ma_state_distribution']}")
    print(f"  D1 BB 位置分布: {result['statistics']['d1_bb20_position_distribution']}")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n已写入: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
