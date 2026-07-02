#!/usr/bin/env python3
"""Build Turning Point Probability MVP output.

独立脚本，基于现有 State Cube / Foundation 历史数据，输出每个标的在
3D / 3W / 3M / 6M 四个时间窗的转折概率、证据与风险。

Usage:
    .venv/bin/python scripts/build_turning_point_probability.py --date 2026-07-02
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

log = logging.getLogger("hermass.scripts.build_turning_point_probability")

OUTPUT_DIR = ROOT / "outputs" / "turning_point_probability"

MODEL_VERSION = "tpp_mvp_v0.1"

WINDOW_CONFIG: dict[str, dict[str, Any]] = {
    "3D": {"days": 3, "up": 0.02, "down": -0.02},
    "3W": {"days": 15, "up": 0.05, "down": -0.05},
    "3M": {"days": 66, "up": 0.10, "down": -0.10},
    "6M": {"days": 126, "up": 0.20, "down": -0.20},
}

OUTCOMES = ["turn_up", "turn_down", "continue", "false_breakout"]

# 经验贝叶斯收缩参数
N_PRIOR = 50
N_TARGET = 100
N_MIN = 30

# 关键位 / 指标阈值
ADX_STRONG = 35.0
ADX_WEAK = 20.0
BB_WIDTH_SQUEEZE = 0.02
BB_WIDTH_EXPAND = 0.05
SHORT_BREAKOUT_PCT = 0.02

FORBIDDEN_WORDS = {
    "买入", "卖出", "加仓", "减仓", "清仓", "空仓",
    "加杠杆", "止盈", "止损", "目标价", "收益承诺",
}


def _score_to_bucket(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score == 0:
        return "zero"
    if score > 11:
        return "strong_pos"
    if score >= 7:
        return "pos"
    if score < -11:
        return "strong_neg"
    if score <= -7:
        return "neg"
    return "neutral"


def _ef_count_bucket(ef_count: int | None) -> str:
    if ef_count is None:
        return "0"
    return str(min(int(ef_count), 3))


def _build_fingerprint(
    d1_bucket: str,
    w1_bucket: str,
    mn1_bucket: str,
    ef_count_bucket: str,
) -> tuple[str, str, str, str]:
    return (d1_bucket, w1_bucket, mn1_bucket, ef_count_bucket)


def _coarser_fingerprint(fp: tuple[str, ...]) -> tuple[str, str, str]:
    """去掉 ef_count 维度后的粗粒度指纹。"""
    return fp[:3]


def _find_latest_state_cube() -> Path | None:
    candidates = sorted(ROOT.glob("outputs/state_cube/state_cube.duckdb"), reverse=True)
    return candidates[0] if candidates else None


def _find_latest_foundation() -> Path | None:
    candidates = sorted(
        ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _has_foundation_date(foundation_db: Path, target_date: date) -> bool:
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"ATTACH '{foundation_db}' AS foundation (READ_ONLY)")
        row = con.execute(
            "SELECT COUNT(*) FROM foundation.d1_perspective_state WHERE state_date = $1",
            [target_date],
        ).fetchone()
        return bool(row and row[0] > 0)
    finally:
        con.close()


def _connect_foundation_view(foundation_db: Path) -> duckdb.DuckDBPyConnection:
    """在内存中连接 Foundation DB 并创建与 State Cube 字段对齐的临时视图。"""
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{foundation_db}' AS foundation (READ_ONLY)")
    con.execute("""
        CREATE TEMP VIEW state_cube AS
        SELECT
            stock_code,
            state_date,
            d1_close,
            mn1_state_hex,
            w1_state_hex,
            d1_state_hex,
            mn1_state_score,
            w1_state_score,
            d1_state_score,
            ef_count,
            d1_adx14,
            d1_bb_width_pct AS d1_bb20_width,
            CAST(NULL AS VARCHAR) AS m30_breakout_signal,
            CAST(NULL AS DOUBLE) AS m30_price_breakout,
            CAST(NULL AS DOUBLE) AS w1_bb20_position,
            CAST(NULL AS DOUBLE) AS d1_bb20_position
        FROM foundation.d1_perspective_state
    """)
    return con


def _find_state_timeline_for_date(target_date: date) -> Path | None:
    path = ROOT / "outputs" / "state_timeline" / f"state_timeline_daily_{target_date.strftime('%Y%m%d')}.duckdb"
    return path if path.exists() else None


def _find_fundamental_db() -> Path | None:
    path = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
    return path if path.exists() else None


def _find_market_assets_for_date(target_date: date) -> Path | None:
    path = ROOT / "outputs" / "market_assets_state" / f"market_assets_state_{target_date.strftime('%Y%m%d')}.json"
    return path if path.exists() else None


def _classify_market_regime(market_state: dict[str, Any] | None) -> str:
    """基于市场资产状态给出简单市场环境标签。"""
    if not market_state:
        return "unknown"
    score = market_state.get("d1_state_score")
    if score is None:
        return "unknown"
    try:
        score = float(score)
    except Exception:
        return "unknown"
    if score >= 12:
        return "strong_bull"
    if score >= 4:
        return "trend_bull"
    if score <= -12:
        return "oversold_bounce"
    if score <= -4:
        return "trend_bear"
    return "range"


def _load_market_state(market_assets_path: Path | None, target_date: date) -> dict[str, Any] | None:
    path = market_assets_path or _find_market_assets_for_date(target_date)
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("读取 market_assets_state 失败: %s", exc)
        return None
    if not isinstance(data, list):
        return None
    broad = [row for row in data if row.get("asset_type") == "broad_index"]
    if not broad:
        broad = [row for row in data if "000001" in str(row.get("symbol", ""))]
    if broad:
        # 优先使用上证综指/沪深300得分
        preferred = [r for r in broad if str(r.get("symbol", "")).startswith(("000001.SH", "000300.SH"))]
        return preferred[0] if preferred else broad[0]
    return data[0] if data else None


def _label_outcome(r_short: float | None, r_long: float | None, cfg: dict[str, Any]) -> str:
    """根据短期和长期收益给出 outcome 标签。"""
    if r_long is None:
        return "continue"
    up_thr = cfg["up"]
    down_thr = cfg["down"]
    short_up = r_short is not None and r_short > SHORT_BREAKOUT_PCT
    short_down = r_short is not None and r_short < -SHORT_BREAKOUT_PCT
    long_up = r_long > up_thr
    long_down = r_long < down_thr
    if short_up and long_down:
        return "false_breakout"
    if short_down and long_up:
        return "false_breakout"
    if long_up:
        return "turn_up"
    if long_down:
        return "turn_down"
    return "continue"


def _compute_historical_stats(
    con: duckdb.DuckDBPyConnection,
    min_date: date | None,
) -> tuple[dict[str, dict[tuple, dict[str, int]]], dict[str, dict[str, int]]]:
    """返回 (bucket_counts[window][fingerprint][outcome], global_counts[window][outcome])。"""
    min_date_sql = "WHERE state_date >= $1" if min_date else ""
    params = [min_date] if min_date else []

    windows_sql_parts: list[str] = []
    for window, cfg in WINDOW_CONFIG.items():
        days = cfg["days"]
        up_thr = cfg["up"]
        down_thr = cfg["down"]
        close_col = f"close_{window.lower()}"
        r_long_expr = f"{close_col} / d1_close - 1"
        windows_sql_parts.append(f"""
            SELECT
                '{window}' AS "window",
                d1_bucket, w1_bucket, mn1_bucket, ef_count_bucket,
                CASE
                    WHEN r_short > {SHORT_BREAKOUT_PCT} AND ({r_long_expr}) < {down_thr} THEN 'false_breakout'
                    WHEN r_short < {-SHORT_BREAKOUT_PCT} AND ({r_long_expr}) > {up_thr} THEN 'false_breakout'
                    WHEN ({r_long_expr}) > {up_thr} THEN 'turn_up'
                    WHEN ({r_long_expr}) < {down_thr} THEN 'turn_down'
                    ELSE 'continue'
                END AS outcome
            FROM labeled
            WHERE {close_col} IS NOT NULL
        """)

    union_sql = " UNION ALL ".join(windows_sql_parts)

    sql = f"""
    WITH hist AS (
        SELECT
            stock_code,
            state_date,
            d1_close,
            LEAD(d1_close, 3) OVER (PARTITION BY stock_code ORDER BY state_date) AS close_3d,
            LEAD(d1_close, 15) OVER (PARTITION BY stock_code ORDER BY state_date) AS close_3w,
            LEAD(d1_close, 66) OVER (PARTITION BY stock_code ORDER BY state_date) AS close_3m,
            LEAD(d1_close, 126) OVER (PARTITION BY stock_code ORDER BY state_date) AS close_6m,
            d1_state_score,
            w1_state_score,
            mn1_state_score,
            ef_count
        FROM state_cube
        {min_date_sql}
    ),
    labeled AS (
        SELECT
            *,
            CASE
                WHEN d1_state_score IS NULL THEN 'unknown'
                WHEN d1_state_score = 0 THEN 'zero'
                WHEN d1_state_score > 11 THEN 'strong_pos'
                WHEN d1_state_score >= 7 THEN 'pos'
                WHEN d1_state_score < -11 THEN 'strong_neg'
                WHEN d1_state_score <= -7 THEN 'neg'
                ELSE 'neutral'
            END AS d1_bucket,
            CASE
                WHEN w1_state_score IS NULL THEN 'unknown'
                WHEN w1_state_score = 0 THEN 'zero'
                WHEN w1_state_score > 11 THEN 'strong_pos'
                WHEN w1_state_score >= 7 THEN 'pos'
                WHEN w1_state_score < -11 THEN 'strong_neg'
                WHEN w1_state_score <= -7 THEN 'neg'
                ELSE 'neutral'
            END AS w1_bucket,
            CASE
                WHEN mn1_state_score IS NULL THEN 'unknown'
                WHEN mn1_state_score = 0 THEN 'zero'
                WHEN mn1_state_score > 11 THEN 'strong_pos'
                WHEN mn1_state_score >= 7 THEN 'pos'
                WHEN mn1_state_score < -11 THEN 'strong_neg'
                WHEN mn1_state_score <= -7 THEN 'neg'
                ELSE 'neutral'
            END AS mn1_bucket,
            CASE
                WHEN ef_count IS NULL THEN '0'
                WHEN ef_count >= 3 THEN '3'
                WHEN ef_count >= 2 THEN '2'
                WHEN ef_count >= 1 THEN '1'
                ELSE '0'
            END AS ef_count_bucket,
            close_3d / d1_close - 1 AS r_short
        FROM hist
        WHERE d1_close IS NOT NULL
    )
    SELECT
        "window",
        d1_bucket,
        w1_bucket,
        mn1_bucket,
        ef_count_bucket,
        outcome,
        COUNT(*) AS n
    FROM (
        {union_sql}
    )
    GROUP BY "window", d1_bucket, w1_bucket, mn1_bucket, ef_count_bucket, outcome
    ORDER BY "window", d1_bucket, w1_bucket, mn1_bucket, ef_count_bucket, outcome
    """

    rows = con.execute(sql, params).fetchall()

    bucket_counts: dict[str, dict[tuple, dict[str, int]]] = {
        w: {} for w in WINDOW_CONFIG
    }
    global_counts: dict[str, dict[str, int]] = {w: {o: 0 for o in OUTCOMES} for w in WINDOW_CONFIG}

    for window, d1_b, w1_b, mn1_b, ef_b, outcome, n in rows:
        fp = (d1_b, w1_b, mn1_b, ef_b)
        bucket_counts[window].setdefault(fp, {o: 0 for o in OUTCOMES})[outcome] = n
        global_counts[window][outcome] += n

    return bucket_counts, global_counts


def _load_current_rows(
    con: duckdb.DuckDBPyConnection,
    target_date: date,
    state_timeline_path: Path | None,
) -> list[dict[str, Any]]:
    """读取目标日期的当前观测行。"""
    attach_sql = ""
    join_sql = ""
    select_extra = ""
    params: list[Any] = [target_date]

    tl_path = state_timeline_path or _find_state_timeline_for_date(target_date)
    if tl_path and tl_path.exists():
        attach_sql = f"ATTACH '{tl_path}' AS tl (READ_ONLY);"
        join_sql = "LEFT JOIN tl.state_timeline_daily tl ON tl.stock_code = sc.stock_code AND tl.state_date = sc.state_date"
        select_extra = ", tl.stock_name AS tl_stock_name, tl.industry_l1 AS tl_industry_l1"
    else:
        # 尝试 fundamental DB
        fund_path = _find_fundamental_db()
        if fund_path and fund_path.exists():
            attach_sql = f"ATTACH '{fund_path}' AS fund (READ_ONLY);"
            join_sql = (
                "LEFT JOIN fund.ifind_industry_chain_profile f "
                "ON f.stock_code = sc.stock_code AND f.as_of_date <= sc.state_date"
            )
            select_extra = ", f.stock_name AS f_stock_name, f.sw_l1 AS f_industry_l1"

    sql = f"""
    {attach_sql}
    SELECT
        sc.stock_code,
        sc.state_date,
        sc.mn1_state_hex,
        sc.w1_state_hex,
        sc.d1_state_hex,
        sc.mn1_state_score,
        sc.w1_state_score,
        sc.d1_state_score,
        sc.ef_count,
        sc.d1_adx14,
        sc.d1_bb20_width,
        sc.d1_close,
        sc.m30_breakout_signal,
        sc.m30_price_breakout,
        sc.w1_bb20_position,
        sc.d1_bb20_position
        {select_extra}
    FROM state_cube sc
    {join_sql}
    WHERE sc.state_date = $1
    ORDER BY sc.stock_code
    """

    rows = con.execute(sql, params).fetchall()
    columns = [d[0] for d in con.description]

    result: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(zip(columns, row))
        # 名称 / 行业优先级：state_timeline > fundamental > code
        stock_name = rec.pop("tl_stock_name", None) or rec.pop("f_stock_name", None) or rec["stock_code"]
        industry_l1 = rec.pop("tl_industry_l1", None) or rec.pop("f_industry_l1", None)
        rec["stock_name"] = stock_name
        rec["industry_l1"] = industry_l1
        result.append(rec)
    return result


def _compute_probabilities_for_row(
    window: str,
    fp: tuple[str, ...],
    bucket_counts: dict[str, dict[tuple, dict[str, int]]],
    global_counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """对单个指纹计算收缩后的四概率、置信度和先验权重。"""
    bc_win = bucket_counts.get(window, {})
    gc_win = global_counts.get(window, {o: 0 for o in OUTCOMES})
    global_total = max(sum(gc_win.values()), 1)
    global_prior = {o: gc_win.get(o, 0) / global_total for o in OUTCOMES}

    fine_counts = bc_win.get(fp, {o: 0 for o in OUTCOMES})
    fine_total = sum(fine_counts.values())

    # 先尝试细粒度指纹，再回退粗粒度，最后全局先验
    counts: dict[str, int]
    used_fp = fp
    fallback_level = "fine"
    if fine_total >= N_MIN // 2 or fine_total > 0:
        counts = fine_counts
    else:
        coarse_key = _coarser_fingerprint(fp)
        coarse_counts = bc_win.get(coarse_key, {o: 0 for o in OUTCOMES})
        coarse_total = sum(coarse_counts.values())
        if coarse_total >= N_MIN // 2:
            counts = coarse_counts
            used_fp = coarse_key
            fallback_level = "coarse"
        else:
            counts = gc_win
            used_fp = ("global",)
            fallback_level = "global"

    total = max(sum(counts.values()), 1)
    empirical = {o: counts.get(o, 0) / total for o in OUTCOMES}

    # 收缩估计
    w = total / (total + N_PRIOR)
    prior_weight = round(float(w), 4)
    probs = {}
    for o in OUTCOMES:
        probs[o] = w * empirical[o] + (1 - w) * global_prior[o]

    # 归一化
    s = sum(probs.values())
    if s > 0:
        probs = {o: probs[o] / s for o in OUTCOMES}
    else:
        probs = {o: 0.25 for o in OUTCOMES}

    # 置信度：基于原始指纹样本量 + 熵；指纹样本不足时强制不超过 0.5
    entropy = 0.0
    for p in probs.values():
        if p > 0:
            entropy -= p * math.log(p, 4)
    confidence = min(1.0, math.sqrt(fine_total / N_TARGET)) * (1.0 - entropy)
    if fine_total < N_MIN:
        confidence = min(confidence, 0.5)
    confidence = max(0.0, min(1.0, round(float(confidence), 4)))

    return {
        "probs": probs,
        "confidence": confidence,
        "bucket_sample_size": int(fine_total),
        "prior_weight": prior_weight,
        "fallback_level": fallback_level,
    }


def _build_evidence_items(row: dict[str, Any]) -> list[str]:
    items: list[str] = []
    d1_score = row.get("d1_state_score")
    w1_score = row.get("w1_state_score")
    mn1_score = row.get("mn1_state_score")
    ef_count = row.get("ef_count") or 0

    if d1_score is not None:
        if d1_score > 11:
            items.append("D1 强势结构")
        elif d1_score >= 7:
            items.append("D1 偏强结构")
        elif d1_score < -11:
            items.append("D1 弱势结构")
        elif d1_score <= -7:
            items.append("D1 偏弱结构")
        else:
            items.append("D1 结构中性")

    if w1_score is not None:
        if w1_score > 7:
            items.append("W1 方向偏多")
        elif w1_score < -7:
            items.append("W1 方向偏空")
        else:
            items.append("W1 方向中性")

    if mn1_score is not None:
        if mn1_score > 7:
            items.append("MN1 长期偏多")
        elif mn1_score < -7:
            items.append("MN1 长期偏空")
        else:
            items.append("MN1 长期中性")

    if ef_count and int(ef_count) > 0:
        items.append(f"EF 数量为 {ef_count}")

    adx = row.get("d1_adx14")
    if adx is not None:
        if adx >= ADX_STRONG:
            items.append("ADX 强劲，趋势动能足")
        elif adx <= ADX_WEAK:
            items.append("ADX 偏弱，趋势动能弱")
        else:
            items.append("ADX 正在构建")

    bbw = row.get("d1_bb20_width")
    if bbw is not None:
        if bbw < BB_WIDTH_SQUEEZE:
            items.append("BB 带宽收缩，波动压缩")
        elif bbw > BB_WIDTH_EXPAND:
            items.append("BB 带宽扩张，波动释放")
        else:
            items.append("BB 带宽中性")

    m30_sig = row.get("m30_breakout_signal")
    if m30_sig:
        items.append(f"M30 信号: {m30_sig}")

    return items


def _build_risk_flags(
    row: dict[str, Any],
    confidence: float,
    bucket_n: int,
    fallback_level: str,
) -> list[str]:
    flags: list[str] = []
    if confidence < 0.3:
        flags.append("低置信")
    if bucket_n < N_MIN or fallback_level == "global":
        flags.append("样本不足")
    adx = row.get("d1_adx14")
    if adx is not None and adx < ADX_WEAK:
        flags.append("ADX 偏弱，趋势未明")
    m30_sig = row.get("m30_breakout_signal")
    if m30_sig and "false" in str(m30_sig).lower():
        flags.append("M30 假突破风险")
    bbw = row.get("d1_bb20_width")
    if bbw is not None and bbw < BB_WIDTH_SQUEEZE:
        flags.append("波动压缩，方向待确认")
    return flags


def _source_state_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mn1_state_hex": row.get("mn1_state_hex"),
        "w1_state_hex": row.get("w1_state_hex"),
        "d1_state_hex": row.get("d1_state_hex"),
        "mn1_state_score": row.get("mn1_state_score"),
        "w1_state_score": row.get("w1_state_score"),
        "d1_state_score": row.get("d1_state_score"),
        "ef_count": row.get("ef_count"),
        "d1_adx14": row.get("d1_adx14"),
        "d1_bb20_width": row.get("d1_bb20_width"),
        "w1_bb20_position": row.get("w1_bb20_position"),
        "d1_bb20_position": row.get("d1_bb20_position"),
        "d1_close": row.get("d1_close"),
    }


def _turning_type(probs: dict[str, float], confidence: float) -> str:
    if confidence < 0.3:
        return "uncertain"
    return max(probs, key=probs.get)  # type: ignore[arg-type]


def _evidence_score(probs: dict[str, float], confidence: float) -> float:
    sorted_vals = sorted(probs.values(), reverse=True)
    spread = sorted_vals[0] - sorted_vals[1]
    return round(float(spread * confidence), 4)


def _has_forbidden_words(text: str) -> bool:
    return any(word in text for word in FORBIDDEN_WORDS)


def _compute_future_return(
    con: duckdb.DuckDBPyConnection,
    stock_code: str,
    state_date: date,
    days: int,
) -> float | None:
    """计算单个标的从 state_date 起未来 N 个交易日收益。用于回填字段。"""
    sql = """
    SELECT LEAD(d1_close, $1) OVER (PARTITION BY stock_code ORDER BY state_date) / d1_close - 1 AS r
    FROM state_cube
    WHERE stock_code = $2
    ORDER BY state_date
    LIMIT 1 OFFSET (
        SELECT COUNT(*) FROM state_cube
        WHERE stock_code = $2 AND state_date < $3
    )
    """
    try:
        row = con.execute(sql, [days, stock_code, state_date]).fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def build_turning_point_probability(
    target_date: date | None = None,
    state_cube_path: Path | str | None = None,
    state_timeline_path: Path | str | None = None,
    market_assets_path: Path | str | None = None,
    foundation_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    min_date: date | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """构建转折概率产物。

    返回 {"ok": bool, "duckdb_path": ..., "json_path": ..., "row_count": int, "warnings": [...]}
    """
    _setup_logging(verbose)
    warnings: list[str] = []

    output_dir = Path(output_dir or OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    con: duckdb.DuckDBPyConnection | None = None
    source_name = "state_cube"
    try:
        state_cube_path = Path(state_cube_path) if state_cube_path else _find_latest_state_cube()
        if not state_cube_path or not state_cube_path.exists():
            warnings.append("未找到 State Cube，尝试使用 Foundation DB 降级")
        else:
            con = duckdb.connect(str(state_cube_path), read_only=True)
            if target_date is None:
                row = con.execute("SELECT MAX(state_date) FROM state_cube").fetchone()
                target_date = row[0] if row and row[0] else date.today()
            check = con.execute(
                "SELECT COUNT(*) FROM state_cube WHERE state_date = $1",
                [target_date],
            ).fetchone()
            if not check or check[0] == 0:
                con.close()
                con = None
                warnings.append(f"State Cube 中无 {target_date} 数据，尝试使用 Foundation DB 降级")

        if con is None:
            foundation_db = Path(foundation_path) if foundation_path else _find_latest_foundation()
            if not foundation_db or not foundation_db.exists():
                warnings.append("未找到 Foundation DB，生成空产物")
                return _write_empty_output(output_dir, target_date, warnings)
            if target_date is None:
                tmp_con = duckdb.connect(":memory:")
                tmp_con.execute(f"ATTACH '{foundation_db}' AS foundation (READ_ONLY)")
                row = tmp_con.execute("SELECT MAX(state_date) FROM foundation.d1_perspective_state").fetchone()
                target_date = row[0] if row and row[0] else date.today()
                tmp_con.close()
            if not _has_foundation_date(foundation_db, target_date):
                warnings.append(f"Foundation DB 中无 {target_date} 数据，生成空产物")
                return _write_empty_output(output_dir, target_date, warnings)
            con = _connect_foundation_view(foundation_db)
            source_name = "foundation"
            warnings.append(f"State Cube 缺少 {target_date}，已降级使用 Foundation DB")

        log.info("目标日期: %s, 数据源: %s", target_date, source_name)

        bucket_counts, global_counts = _compute_historical_stats(con, min_date)
        current_rows = _load_current_rows(con, target_date, Path(state_timeline_path) if state_timeline_path else None)
        market_state = _load_market_state(
            Path(market_assets_path) if market_assets_path else None,
            target_date,
        )
        market_regime = _classify_market_regime(market_state)

        if not current_rows:
            warnings.append(f"{target_date} 无当前观测行，生成空产物")
            return _write_empty_output(output_dir, target_date, warnings)

        records: list[dict[str, Any]] = []
        for row in current_rows:
            fp = _build_fingerprint(
                _score_to_bucket(row.get("d1_state_score")),
                _score_to_bucket(row.get("w1_state_score")),
                _score_to_bucket(row.get("mn1_state_score")),
                _ef_count_bucket(row.get("ef_count")),
            )
            for window, cfg in WINDOW_CONFIG.items():
                prob_info = _compute_probabilities_for_row(window, fp, bucket_counts, global_counts)
                probs = prob_info["probs"]
                confidence = prob_info["confidence"]
                turning_type = _turning_type(probs, confidence)
                evidence_items = _build_evidence_items(row)
                risk_flags = _build_risk_flags(row, confidence, prob_info["bucket_sample_size"], prob_info["fallback_level"])

                # future_return_n 和 outcome_label 仅写入 DuckDB，不进入默认 JSON
                future_return = _compute_future_return(con, row["stock_code"], row["state_date"], cfg["days"])
                outcome_label = _label_outcome(
                    _compute_future_return(con, row["stock_code"], row["state_date"], 3),
                    future_return,
                    cfg,
                ) if future_return is not None else None

                record = {
                    "stock_code": row["stock_code"],
                    "stock_name": row["stock_name"],
                    "state_date": row["state_date"],
                    "window": window,
                    "turning_type": turning_type,
                    "prob_turn_up": round(float(probs["turn_up"]), 4),
                    "prob_turn_down": round(float(probs["turn_down"]), 4),
                    "prob_continue": round(float(probs["continue"]), 4),
                    "prob_false_breakout": round(float(probs["false_breakout"]), 4),
                    "confidence": confidence,
                    "evidence_score": _evidence_score(probs, confidence),
                    "evidence_items": json.dumps(evidence_items, ensure_ascii=False),
                    "risk_flags": json.dumps(risk_flags, ensure_ascii=False),
                    "source_state_summary": json.dumps(_source_state_summary(row), ensure_ascii=False),
                    "bucket_sample_size": prob_info["bucket_sample_size"],
                    "prior_weight": prob_info["prior_weight"],
                    "market_regime": market_regime,
                    "industry_l1": row.get("industry_l1"),
                    "future_return_n": future_return,
                    "outcome_label": outcome_label,
                    "model_version": MODEL_VERSION,
                    "updated_at": datetime.now().isoformat(),
                }
                records.append(record)

        duckdb_path, json_path = _write_outputs(
            output_dir, target_date, records, market_regime, warnings
        )
        return {
            "ok": True,
            "duckdb_path": str(duckdb_path),
            "json_path": str(json_path),
            "row_count": len(records),
            "warnings": warnings,
        }
    finally:
        if con is not None:
            con.close()


def _write_empty_output(
    output_dir: Path,
    target_date: date | None,
    warnings: list[str],
) -> dict[str, Any]:
    duckdb_path, json_path = _write_outputs(output_dir, target_date, [], "unknown", warnings)
    return {
        "ok": True,
        "duckdb_path": str(duckdb_path),
        "json_path": str(json_path),
        "row_count": 0,
        "warnings": warnings,
    }


def _write_outputs(
    output_dir: Path,
    target_date: date | None,
    records: list[dict[str, Any]],
    market_regime: str,
    warnings: list[str],
) -> tuple[Path, Path]:
    date_str = target_date.strftime("%Y%m%d") if target_date else "unknown"
    duckdb_path = output_dir / f"turning_point_probability_{date_str}.duckdb"
    json_path = output_dir / "turning_point_probability_latest.json"

    # DuckDB 原子写入（只生成文件名，不预创建空文件）
    tmp_db = tempfile.mktemp(suffix=".duckdb", dir=str(output_dir), prefix="tmp_tpp_")
    tmp_db_path = Path(tmp_db)
    try:
        con_out = duckdb.connect(str(tmp_db_path))
        try:
            con_out.execute("""
                CREATE TABLE turning_point_probability (
                    stock_code VARCHAR,
                    stock_name VARCHAR,
                    state_date DATE,
                    "window" VARCHAR,
                    turning_type VARCHAR,
                    prob_turn_up DOUBLE,
                    prob_turn_down DOUBLE,
                    prob_continue DOUBLE,
                    prob_false_breakout DOUBLE,
                    confidence DOUBLE,
                    evidence_score DOUBLE,
                    evidence_items VARCHAR,
                    risk_flags VARCHAR,
                    source_state_summary VARCHAR,
                    bucket_sample_size INTEGER,
                    prior_weight DOUBLE,
                    market_regime VARCHAR,
                    industry_l1 VARCHAR,
                    future_return_n DOUBLE,
                    outcome_label VARCHAR,
                    model_version VARCHAR,
                    updated_at TIMESTAMP
                )
            """)
            if records:
                con_out.executemany(
                    """
                    INSERT INTO turning_point_probability VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                    )
                    """,
                    [
                        (
                            r["stock_code"], r["stock_name"], r["state_date"], r["window"], r["turning_type"],
                            r["prob_turn_up"], r["prob_turn_down"], r["prob_continue"], r["prob_false_breakout"],
                            r["confidence"], r["evidence_score"], r["evidence_items"], r["risk_flags"],
                            r["source_state_summary"], r["bucket_sample_size"], r["prior_weight"], r["market_regime"],
                            r["industry_l1"], r["future_return_n"], r["outcome_label"], r["model_version"], r["updated_at"]
                        )
                        for r in records
                    ],
                )
                con_out.execute("""
                    CREATE UNIQUE INDEX idx_tpp_pk
                    ON turning_point_probability(stock_code, state_date, "window", model_version)
                """)
                con_out.execute("CREATE INDEX idx_tpp_date ON turning_point_probability(state_date)")
                con_out.execute('CREATE INDEX idx_tpp_window_type ON turning_point_probability("window", turning_type)')
                con_out.execute("CREATE INDEX idx_tpp_confidence ON turning_point_probability(confidence)")
            con_out.commit()
        finally:
            con_out.close()
        shutil.move(str(tmp_db_path), str(duckdb_path))
    except Exception:
        if tmp_db_path.exists():
            tmp_db_path.unlink()
        raise

    # JSON 摘要：不包含 future_return_n / outcome_label
    json_records = []
    for r in records:
        jr = {
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "state_date": r["state_date"].isoformat() if isinstance(r["state_date"], date) else r["state_date"],
            "window": r["window"],
            "turning_type": r["turning_type"],
            "prob_turn_up": r["prob_turn_up"],
            "prob_turn_down": r["prob_turn_down"],
            "prob_continue": r["prob_continue"],
            "prob_false_breakout": r["prob_false_breakout"],
            "confidence": r["confidence"],
            "evidence_score": r["evidence_score"],
            "evidence_items": json.loads(r["evidence_items"]),
            "risk_flags": json.loads(r["risk_flags"]),
            "source_state_summary": json.loads(r["source_state_summary"]),
            "bucket_sample_size": r["bucket_sample_size"],
            "prior_weight": r["prior_weight"],
            "market_regime": r["market_regime"],
            "industry_l1": r["industry_l1"],
            "model_version": r["model_version"],
            "updated_at": r["updated_at"],
        }
        json_records.append(jr)

    top_by_window: dict[str, list[dict[str, Any]]] = {w: [] for w in WINDOW_CONFIG}
    for w in WINDOW_CONFIG:
        w_rows = [r for r in json_records if r["window"] == w]
        w_rows.sort(key=lambda x: (x["confidence"], x["evidence_score"]), reverse=True)
        top_by_window[w] = w_rows[:50]

    market_summary: dict[str, Any] = {w: {"turning_type_counts": {}, "avg_confidence": 0.0, "count": 0} for w in WINDOW_CONFIG}
    for w in WINDOW_CONFIG:
        w_rows = [r for r in json_records if r["window"] == w]
        counts: dict[str, int] = {}
        conf_sum = 0.0
        for r in w_rows:
            counts[r["turning_type"]] = counts.get(r["turning_type"], 0) + 1
            conf_sum += r["confidence"]
        market_summary[w] = {
            "turning_type_counts": counts,
            "avg_confidence": round(conf_sum / len(w_rows), 4) if w_rows else 0.0,
            "count": len(w_rows),
        }

    payload = {
        "meta": {
            "state_date": target_date.isoformat() if isinstance(target_date, date) else None,
            "model_version": MODEL_VERSION,
            "generated_at": datetime.now().isoformat(),
            "market_regime": market_regime,
            "row_count": len(records),
            "warnings": warnings,
        },
        "market_summary": market_summary,
        "top_by_window": top_by_window,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return duckdb_path, json_path


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="构建转折概率 MVP 产物")
    parser.add_argument(
        "--date",
        default="",
        help="数据日期 YYYY-MM-DD，默认使用 State Cube 最新日期",
    )
    parser.add_argument("--state-cube", default="", help="State Cube DuckDB 路径")
    parser.add_argument("--state-timeline", default="", help="State Timeline DuckDB 路径（可选）")
    parser.add_argument("--market-assets", default="", help="market_assets_state JSON 路径（可选）")
    parser.add_argument("--foundation", default="", help="Foundation DuckDB 路径（State Cube 缺失时降级使用）")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="输出目录")
    parser.add_argument("--min-date", default="", help="历史统计起始日期 YYYY-MM-DD（可选）")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 日志")
    args = parser.parse_args()

    target_date: date | None = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    min_date: date | None = None
    if args.min_date:
        min_date = datetime.strptime(args.min_date, "%Y-%m-%d").date()

    result = build_turning_point_probability(
        target_date=target_date,
        state_cube_path=args.state_cube or None,
        state_timeline_path=args.state_timeline or None,
        market_assets_path=args.market_assets or None,
        foundation_path=args.foundation or None,
        output_dir=args.output_dir or None,
        min_date=min_date,
        verbose=args.verbose,
    )

    if result["ok"]:
        log.info("产物已生成: %s", result["duckdb_path"])
        log.info("JSON 摘要: %s", result["json_path"])
        log.info("行数: %d", result["row_count"])
        if result["warnings"]:
            for w in result["warnings"]:
                log.warning(w)
        return 0
    else:
        log.error("构建失败: %s", result.get("error"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
