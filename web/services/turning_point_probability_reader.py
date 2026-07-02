"""Turning Point Probability 只读消费层。

读取 `outputs/turning_point_probability/` 下的 latest JSON 或 DuckDB，
为前端 / Agent 提供概率证据，不输出交易动作结论。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs" / "turning_point_probability"
LATEST_JSON = OUTPUT_DIR / "turning_point_probability_latest.json"

WINDOW_ORDER = ["3D", "3W", "3M", "6M"]
MAX_LIMIT = 500

log = logging.getLogger("hermass.web.turning_point_probability_reader")

RESEARCH_ONLY_DISCLAIMER = (
    "本接口仅返回状态观察与概率证据，不构成交易建议。"
)


def _latest_duckdb_path() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("turning_point_probability_*.duckdb"), reverse=True)
    return candidates[0] if candidates else None


def _load_latest_json() -> dict[str, Any] | None:
    if not LATEST_JSON.exists():
        return None
    try:
        return json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("读取 latest JSON 失败: %s", exc)
        return None


def _parse_json_columns(row: dict[str, Any]) -> dict[str, Any]:
    """把 evidence_items / risk_flags / source_state_summary 从 JSON 字符串解析为对象。"""
    for key in ("evidence_items", "risk_flags", "source_state_summary"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except Exception:
                row[key] = []
    return row


def _filter_signal_fields(row: dict[str, Any]) -> dict[str, Any]:
    """只返回 signals API 需要的字段。"""
    wanted = (
        "stock_code",
        "stock_name",
        "window",
        "turning_type",
        "prob_turn_up",
        "prob_turn_down",
        "prob_continue",
        "prob_false_breakout",
        "confidence",
        "evidence_score",
        "risk_flags",
        "bucket_sample_size",
        "market_regime",
        "industry_l1",
    )
    return {k: row.get(k) for k in wanted}


def _normalize_window(window: str) -> str:
    return str(window or "3W").strip().upper()


def _normalize_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(MAX_LIMIT, value))


def _normalize_stock_code(stock_code: str) -> str:
    return str(stock_code or "").strip().upper()


def get_summary() -> dict[str, Any]:
    """返回概率产物摘要。"""
    data = _load_latest_json()
    if data:
        meta = data.get("meta", {})
        return {
            "ok": True,
            "state_date": meta.get("state_date"),
            "model_version": meta.get("model_version"),
            "row_count": meta.get("row_count", 0),
            "market_regime": meta.get("market_regime", "unknown"),
            "warnings": meta.get("warnings", []),
            "market_summary": data.get("market_summary", {}),
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }

    db_path = _latest_duckdb_path()
    if not db_path:
        return {
            "ok": True,
            "state_date": None,
            "model_version": None,
            "row_count": 0,
            "market_regime": "unknown",
            "warnings": ["转折点概率产物尚未生成"],
            "market_summary": {},
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            row_count = con.execute(
                "SELECT COUNT(*) FROM turning_point_probability"
            ).fetchone()[0]
            window_rows = con.execute(
                '''SELECT "window", COUNT(*) FROM turning_point_probability GROUP BY "window"'''
            ).fetchall()
            market_summary = {
                w: {"count": int(c)} for w, c in window_rows
            }
            return {
                "ok": True,
                "state_date": None,
                "model_version": None,
                "row_count": row_count,
                "market_regime": "unknown",
                "warnings": ["latest JSON 缺失，已从 DuckDB 降级读取"],
                "market_summary": market_summary,
                "disclaimer": RESEARCH_ONLY_DISCLAIMER,
            }
        finally:
            con.close()
    except Exception as exc:
        log.warning("从 DuckDB 读取摘要失败: %s", exc)
        return {
            "ok": True,
            "state_date": None,
            "model_version": None,
            "row_count": 0,
            "market_regime": "unknown",
            "warnings": [f"读取产物失败: {exc}"],
            "market_summary": {},
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }


def get_signals(window: str = "3W", limit: int = 50) -> dict[str, Any]:
    """返回指定时间窗的 Top 信号列表。"""
    window = _normalize_window(window)
    limit = _normalize_limit(limit)
    if window not in WINDOW_ORDER:
        return {
            "ok": False,
            "error": f"window 必须是 {WINDOW_ORDER} 之一",
            "window": window,
            "signals": [],
        }

    data = _load_latest_json()
    if data:
        raw_signals = data.get("top_by_window", {}).get(window, [])
        signals = [_filter_signal_fields(_parse_json_columns(dict(r))) for r in raw_signals[:limit]]
        return {
            "ok": True,
            "window": window,
            "limit": limit,
            "count": len(signals),
            "signals": signals,
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }

    db_path = _latest_duckdb_path()
    if not db_path:
        return {
            "ok": True,
            "window": window,
            "limit": limit,
            "count": 0,
            "signals": [],
            "warning": "转折点概率产物尚未生成",
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            columns = [d[0] for d in con.execute("DESCRIBE turning_point_probability").fetchall()]
            rows = con.execute(
                '''
                SELECT * FROM turning_point_probability
                WHERE "window" = $1
                ORDER BY confidence DESC, evidence_score DESC
                LIMIT $2
                ''',
                [window, limit],
            ).fetchall()
            signals = []
            for row in rows:
                rec = _parse_json_columns(dict(zip(columns, row)))
                signals.append(_filter_signal_fields(rec))
            return {
                "ok": True,
                "window": window,
                "limit": limit,
                "count": len(signals),
                "signals": signals,
                "warning": "latest JSON 缺失，已从 DuckDB 降级读取",
                "disclaimer": RESEARCH_ONLY_DISCLAIMER,
            }
        finally:
            con.close()
    except Exception as exc:
        log.warning("从 DuckDB 读取 signals 失败: %s", exc)
        return {
            "ok": True,
            "window": window,
            "limit": limit,
            "count": 0,
            "signals": [],
            "warning": f"读取产物失败: {exc}",
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }


def get_stock(stock_code: str) -> dict[str, Any]:
    """返回单标的四个时间窗概率行。"""
    stock_code = _normalize_stock_code(stock_code)
    if not stock_code:
        return {
            "ok": False,
            "error": "缺少 stock_code",
            "stock_code": stock_code,
            "rows": [],
        }

    db_path = _latest_duckdb_path()
    if not db_path:
        # JSON 里只有 Top 50，无法覆盖任意标的；直接按无产物处理
        return {
            "ok": True,
            "stock_code": stock_code,
            "rows": [],
            "warning": "转折点概率产物尚未生成",
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            columns = [d[0] for d in con.execute("DESCRIBE turning_point_probability").fetchall()]
            rows = con.execute(
                '''
                SELECT * FROM turning_point_probability
                WHERE stock_code = $1
                ORDER BY
                    CASE "window"
                        WHEN '3D' THEN 1
                        WHEN '3W' THEN 2
                        WHEN '3M' THEN 3
                        WHEN '6M' THEN 4
                    END
                ''',
                [stock_code],
            ).fetchall()
            result_rows = []
            for row in rows:
                rec = _parse_json_columns(dict(zip(columns, row)))
                result_rows.append(_filter_signal_fields(rec))
            return {
                "ok": True,
                "stock_code": stock_code,
                "rows": result_rows,
                "count": len(result_rows),
                "disclaimer": RESEARCH_ONLY_DISCLAIMER,
            }
        finally:
            con.close()
    except Exception as exc:
        log.warning("从 DuckDB 读取 stock 失败: %s", exc)
        return {
            "ok": True,
            "stock_code": stock_code,
            "rows": [],
            "warning": f"读取产物失败: {exc}",
            "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        }
