#!/usr/bin/env python3
"""Build a normalized strategy signal ledger.

The ledger is an integration contract. It consumes authoritative strategy
modules and records their exact signals in one read-only-for-consumers DuckDB.
It does not reimplement strategy logic and does not write to the State
foundation DB.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.engine import load_state_data_from_duckdb
from backtest.strategy_signals.bollinger_bandit import bollinger_bandit_signal
from backtest.strategy_signals.ma2560 import ma2560_signal
from backtest.strategy_signals.vcp import vcp_signal


LEDGER_DB = ROOT / "outputs" / "strategy_signals" / "strategy_signals.duckdb"
STATE_CACHE_DIR = ROOT / "outputs" / "state_cache"
MA2560_RULE_PATH = ROOT / "config" / "ma2560_state_market_match_rule.json"
RECOMMENDATION_DIR = ROOT / "recommendation" / "outputs"


SIGNAL_META = {
    "vcp_breakout": ("vcp", "entry", "VCP突破确认"),
    "vcp_breakout_weak_vol": ("vcp", "entry", "VCP弱放量突破"),
    "vcp_breakout_no_vol": ("vcp", "entry", "VCP无放量突破"),
    "vcp_contraction": ("vcp", "structure", "VCP收缩结构"),
    "vcp_early_contraction": ("vcp", "structure", "VCP早期收缩结构"),
    "ma2560_golden_cross": ("ma2560", "entry", "2560金叉"),
    "ma2560_strong_hold": ("ma2560", "structure", "2560强多头结构"),
    "ma2560_aligned": ("ma2560", "structure", "2560多头排列"),
    "ma2560_death_cross_exit": ("ma2560", "exit", "2560死叉风险"),
    "ma2560_bearish": ("ma2560", "risk", "2560空头排列"),
    "bb_bandit_long_entry": ("bollinger_bandit", "entry", "布林强盗多头触发"),
}

REMINDER_ENTRY_STRATEGIES = {"vcp", "ma2560", "bollinger_bandit"}


def ensure_column(con: duckdb.DuckDBPyConnection, table: str, column: str, definition: str) -> None:
    exists = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
          AND column_name = ?
        """,
        (table, column),
    ).fetchone()[0]
    if not exists:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def code6(value: Any) -> str:
    text = str(value or "").upper().strip()
    digits = "".join(ch for ch in text.split(".", 1)[0] if ch.isdigit())
    return digits[-6:] if digits else text


def default_foundation_db(date_str: str) -> Path:
    exact = ROOT / "outputs" / f"p116_foundation_{ymd(date_str)}" / "p116_foundation.duckdb"
    if exact.exists():
        return exact
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    if not candidates:
        raise FileNotFoundError("No foundation DB found under outputs/")
    return candidates[-1]


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_signal_daily (
            signal_date DATE NOT NULL,
            stock_code VARCHAR NOT NULL,
            strategy_id VARCHAR NOT NULL,
            signal_type VARCHAR NOT NULL,
            signal_name VARCHAR NOT NULL,
            stock_name VARCHAR DEFAULT '',
            signal_strength DOUBLE NOT NULL,
            params_json VARCHAR NOT NULL,
            raw_signal VARCHAR NOT NULL,
            source_module VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL,
            reminder_eligible BOOLEAN NOT NULL,
            display_scope VARCHAR NOT NULL,
            ma2560_local_combo_pass BOOLEAN DEFAULT false,
            ma2560_p116_state_match BOOLEAN DEFAULT false,
            ma2560_market_match_level VARCHAR DEFAULT 'not_match',
            ma2560_state_combo VARCHAR DEFAULT '',
            created_at VARCHAR NOT NULL,
            PRIMARY KEY (signal_date, stock_code, strategy_id, raw_signal)
        )
        """
    )
    ensure_column(con, "strategy_signal_daily", "reminder_eligible", "BOOLEAN DEFAULT false")
    ensure_column(con, "strategy_signal_daily", "display_scope", "VARCHAR DEFAULT 'research'")
    ensure_column(con, "strategy_signal_daily", "lifecycle_stage", "VARCHAR DEFAULT '未知'")
    ensure_column(con, "strategy_signal_daily", "strategy_environment_fit", "VARCHAR DEFAULT '待观察'")
    ensure_column(con, "strategy_signal_daily", "fit_reasons", "VARCHAR DEFAULT ''")
    ensure_column(con, "strategy_signal_daily", "stock_name", "VARCHAR DEFAULT ''")
    ensure_column(con, "strategy_signal_daily", "ma2560_local_combo_pass", "BOOLEAN DEFAULT false")
    ensure_column(con, "strategy_signal_daily", "ma2560_p116_state_match", "BOOLEAN DEFAULT false")
    ensure_column(con, "strategy_signal_daily", "ma2560_market_match_level", "VARCHAR DEFAULT 'not_match'")
    ensure_column(con, "strategy_signal_daily", "ma2560_state_combo", "VARCHAR DEFAULT ''")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_signal_manifest (
            signal_date DATE PRIMARY KEY,
            generated_at VARCHAR NOT NULL,
            foundation_db VARCHAR NOT NULL,
            signal_count BIGINT NOT NULL,
            strategy_counts_json VARCHAR NOT NULL,
            unsupported_json VARCHAR NOT NULL,
            research_only BOOLEAN NOT NULL
        )
        """
    )


def clear_date(con: duckdb.DuckDBPyConnection, date_str: str) -> None:
    con.execute("DELETE FROM strategy_signal_daily WHERE signal_date = CAST(? AS DATE)", (date_str,))
    con.execute("DELETE FROM strategy_signal_manifest WHERE signal_date = CAST(? AS DATE)", (date_str,))


def indicator_params(strategy_id: str, raw_signal: str) -> dict[str, Any]:
    if strategy_id == "vcp":
        return {"source": "backtest.strategy_signals.vcp.vcp_signal"}
    if strategy_id == "ma2560":
        return {"fast_ma": 25, "slow_ma": 60, "source": "backtest.strategy_signals.ma2560.ma2560_signal"}
    if strategy_id == "bollinger_bandit":
        return {
            "basis_period": 50,
            "stddev_multiplier": 1,
            "momentum_lookback": 30,
            "source": "backtest.strategy_signals.bollinger_bandit.bollinger_bandit_signal",
        }
    return {"source": raw_signal}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def state_hex(row: dict[str, Any], prefix: str) -> str:
    value = row.get(f"{prefix}_state_hex")
    if value in (None, ""):
        value = row.get(f"{prefix}_hex")
    return str(value or "").upper().strip()


def state_combo(row: dict[str, Any]) -> str:
    return "/".join([state_hex(row, "mn1"), state_hex(row, "w1"), state_hex(row, "d1")])


def load_ma2560_rule(path: Path = MA2560_RULE_PATH) -> dict[str, Any]:
    fallback = {
        "p116_state_match": {
            "latest_2560_signal": "ma2560_strong_hold",
            "allowed_states": ["E/E/F", "E/F/F", "E/F/E"],
        },
        "market_match": {
            "preferred": "macro_etf_ef_count >= 2",
            "missing_macro_etf_policy": "stock_rule_only_not_market_confirmed",
            "unsupported_market_policy": "do_not_call_full_match",
        },
    }
    payload = load_json(path)
    if not payload:
        return fallback
    fallback.update(payload)
    fallback["p116_state_match"] = {
        **fallback.get("p116_state_match", {}),
        **(payload.get("p116_state_match") or {}),
    }
    fallback["market_match"] = {
        **fallback.get("market_match", {}),
        **(payload.get("market_match") or {}),
    }
    return fallback


def recommendation_csv_for(date_str: str, override: Path | None = None) -> Path | None:
    if override:
        path = override if override.is_absolute() else (ROOT / override).resolve()
        return path if path.exists() else None
    exact = RECOMMENDATION_DIR / f"p116_recommendation_{ymd(date_str)}.csv"
    return exact if exact.exists() else None


def build_recommendation_context(date_str: str, recommendation_csv: Path | None = None) -> dict[str, dict[str, Any]]:
    path = recommendation_csv_for(date_str, recommendation_csv)
    if path is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = code6(row.get("stock_code") or row.get("symbol"))
            if key:
                out[key] = row
    return out


def compute_ma2560_state_market_fields(
    row: dict[str, Any],
    strategy_id: str,
    raw_signal: str,
    recommendation_context: dict[str, dict[str, Any]],
    ma2560_rule: dict[str, Any],
) -> dict[str, Any]:
    combo = state_combo(row)
    fields = {
        "ma2560_local_combo_pass": False,
        "ma2560_p116_state_match": False,
        "ma2560_market_match_level": "not_match",
        "ma2560_state_combo": combo,
    }
    if strategy_id != "ma2560":
        return fields

    state_rule = ma2560_rule.get("p116_state_match") or {}
    required_signal = str(state_rule.get("latest_2560_signal") or "ma2560_strong_hold")
    allowed_states = {str(item).upper().strip() for item in (state_rule.get("allowed_states") or [])}
    local_combo_pass = raw_signal == required_signal
    p116_state_match = combo in allowed_states

    fields["ma2560_local_combo_pass"] = local_combo_pass
    fields["ma2560_p116_state_match"] = p116_state_match
    if not (local_combo_pass and p116_state_match):
        return fields

    rec = recommendation_context.get(code6(row.get("stock_code"))) or {}
    macro_ef = safe_float(rec.get("macro_etf_ef_count"))
    macro_has_data = any(
        str(rec.get(key) or "").strip()
        for key in ["macro_etf_symbol", "macro_etf_name", "macro_etf_state", "macro_etf_ef_count"]
    )
    if macro_ef is not None and macro_ef >= 2:
        fields["ma2560_market_match_level"] = "full_match"
    elif macro_has_data:
        fields["ma2560_market_match_level"] = "market_unsupported"
    else:
        fields["ma2560_market_match_level"] = "stock_only"
    return fields


def build_duration_context(date_str: str) -> dict[str, dict[str, Any]]:
    payload = load_json(STATE_CACHE_DIR / f"state_duration_{ymd(date_str)}.json")
    return {code6(row.get("stock_code")): row for row in payload.get("rows", []) or []}


def build_sr_context(date_str: str) -> dict[str, dict[str, Any]]:
    payload = load_json(STATE_CACHE_DIR / f"sr_boundary_{ymd(date_str)}.json")
    best: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows", []) or []:
        key = code6(row.get("stock_code"))
        distance = row.get("distance_pct")
        try:
            distance_value = float(distance)
        except (TypeError, ValueError):
            distance_value = 999.0
        current = best.get(key)
        if current is None:
            best[key] = row
            continue
        try:
            current_distance = float(current.get("distance_pct"))
        except (TypeError, ValueError):
            current_distance = 999.0
        if distance_value < current_distance:
            best[key] = row
    return best


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def compute_lifecycle_stage(
    state: dict[str, Any],
    duration: dict[str, Any] | None,
    sr: dict[str, Any] | None,
) -> tuple[str, list[str]]:
    duration = duration or {}
    sr = sr or {}
    reasons: list[str] = []

    d1_since_exit = as_int(duration.get("d1_days_since_contraction_exit"))
    all_three_duration = as_int(duration.get("all_three_ef_duration"))
    d1_ef_duration = as_int(duration.get("d1_ef_duration"))
    d1_volatility_bit = as_int(state.get("d1_volatility_bit"), 0)
    ef_count = as_int(state.get("ef_count"), 0) or 0
    above_resistance = sr.get("above_resistance") is True

    if d1_volatility_bit == 1:
        reasons.append("D1波动偏活跃")
    if above_resistance:
        reasons.append("价格位于阻力区间上方")

    if d1_since_exit is not None and 0 <= d1_since_exit <= 3:
        reasons.append(f"D1刚脱离收缩({d1_since_exit}天)")
        if d1_volatility_bit != 1 and not above_resistance:
            return "新生", reasons

    if all_three_duration is not None and 0 < all_three_duration <= 5:
        reasons.append(f"三周期共振新近形成({all_three_duration}天)")
        if d1_volatility_bit != 1 and not above_resistance:
            return "新生", reasons

    if d1_volatility_bit == 1 or above_resistance:
        return "延展", reasons

    if d1_ef_duration is not None and d1_ef_duration > 20:
        reasons.append(f"D1 E/F持续{d1_ef_duration}天")
        return "延展", reasons

    if d1_ef_duration is not None and 3 < d1_ef_duration <= 20 and d1_volatility_bit == 0 and ef_count >= 2:
        reasons.append(f"D1 E/F持续{d1_ef_duration}天")
        reasons.append("波动稳定")
        reasons.append(f"ef_count={ef_count}")
        return "行进", reasons

    if d1_ef_duration is not None:
        reasons.append(f"D1 E/F持续{d1_ef_duration}天")
    if ef_count:
        reasons.append(f"ef_count={ef_count}")
    return "未知", reasons


def compute_environment_fit(strategy_id: str, lifecycle_stage: str, reasons: list[str]) -> tuple[str, str]:
    best_stage = {
        "vcp": "新生",
        "ma2560": "行进",
        "bollinger_bandit": "延展",
    }.get(strategy_id)

    if lifecycle_stage == "未知" or not best_stage:
        return "待观察", "；".join(reasons + [f"{strategy_id}待观察"])

    if lifecycle_stage == best_stage:
        fit = "最佳适配"
    elif strategy_id == "ma2560" and lifecycle_stage == "新生":
        fit = "适配"
    elif strategy_id == "bollinger_bandit" and lifecycle_stage == "行进":
        fit = "适配"
    else:
        fit = "弱适配"

    return fit, "；".join(reasons + [f"{strategy_id}{fit}"])


def signal_rows_for_state(
    row: dict[str, Any],
    duration_context: dict[str, dict[str, Any]],
    sr_context: dict[str, dict[str, Any]],
    recommendation_context: dict[str, dict[str, Any]],
    ma2560_rule: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    key = code6(row.get("stock_code"))
    duration = duration_context.get(key, {})
    sr = sr_context.get(key, {})
    lifecycle_stage, lifecycle_reasons = compute_lifecycle_stage(row, duration, sr)
    for source_module, fn in [
        ("backtest.strategy_signals.vcp", vcp_signal),
        ("backtest.strategy_signals.ma2560", ma2560_signal),
        ("backtest.strategy_signals.bollinger_bandit", bollinger_bandit_signal),
    ]:
        result = fn(row, row)
        if not result:
            continue
        raw_signal, strength = result
        meta = SIGNAL_META.get(raw_signal)
        if not meta:
            continue
        strategy_id, signal_type, signal_name = meta
        reminder_eligible = signal_type == "entry" and strategy_id in REMINDER_ENTRY_STRATEGIES
        display_scope = "reminder" if reminder_eligible else "research"
        environment_fit, fit_reasons = compute_environment_fit(strategy_id, lifecycle_stage, lifecycle_reasons)
        ma2560_fields = compute_ma2560_state_market_fields(
            row,
            strategy_id,
            raw_signal,
            recommendation_context,
            ma2560_rule,
        )
        out.append(
            {
                "signal_date": row["date"],
                "stock_code": row["stock_code"],
                "stock_name": row.get("stock_name") or "",
                "strategy_id": strategy_id,
                "signal_type": signal_type,
                "signal_name": signal_name,
                "signal_strength": float(strength or 0.0),
                "params_json": json.dumps(indicator_params(strategy_id, raw_signal), ensure_ascii=False, sort_keys=True),
                "raw_signal": raw_signal,
                "source_module": source_module,
                "research_only": True,
                "reminder_eligible": reminder_eligible,
                "display_scope": display_scope,
                "lifecycle_stage": lifecycle_stage,
                "strategy_environment_fit": environment_fit,
                "fit_reasons": fit_reasons,
                **ma2560_fields,
            }
        )
    return out


def build_ledger(
    date_str: str,
    foundation_db: Path,
    ledger_db: Path = LEDGER_DB,
    min_ef: int = 2,
    recommendation_csv: Path | None = None,
    ma2560_rule_path: Path = MA2560_RULE_PATH,
) -> dict[str, Any]:
    ledger_db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ledger_db))
    create_tables(con)
    clear_date(con, date_str)

    state_by_date = load_state_data_from_duckdb(foundation_db, date_str, date_str)
    states = state_by_date.get(date_str, [])
    duration_context = build_duration_context(date_str)
    sr_context = build_sr_context(date_str)
    recommendation_path = recommendation_csv_for(date_str, recommendation_csv)
    recommendation_context = build_recommendation_context(date_str, recommendation_csv)
    ma2560_rule = load_ma2560_rule(ma2560_rule_path)
    created_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for state in states:
        if int(state.get("ef_count") or 0) < min_ef:
            continue
        rows.extend(signal_rows_for_state(state, duration_context, sr_context, recommendation_context, ma2560_rule))

    if rows:
        con.executemany(
            """
            INSERT OR REPLACE INTO strategy_signal_daily
            (signal_date, stock_code, strategy_id, signal_type, signal_name,
             stock_name, signal_strength, params_json, raw_signal, source_module, research_only,
             reminder_eligible, display_scope, lifecycle_stage, strategy_environment_fit,
             fit_reasons, ma2560_local_combo_pass, ma2560_p116_state_match,
             ma2560_market_match_level, ma2560_state_combo, created_at)
            VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["signal_date"],
                    r["stock_code"],
                    r["strategy_id"],
                    r["signal_type"],
                    r["signal_name"],
                    r["stock_name"],
                    r["signal_strength"],
                    r["params_json"],
                    r["raw_signal"],
                    r["source_module"],
                    r["research_only"],
                    r["reminder_eligible"],
                    r["display_scope"],
                    r["lifecycle_stage"],
                    r["strategy_environment_fit"],
                    r["fit_reasons"],
                    r["ma2560_local_combo_pass"],
                    r["ma2560_p116_state_match"],
                    r["ma2560_market_match_level"],
                    r["ma2560_state_combo"],
                    created_at,
                )
                for r in rows
            ],
        )

    strategy_counts = {
        f"{sid}:{stype}": n
        for sid, stype, n in con.execute(
            """
            SELECT strategy_id, signal_type, COUNT(*)
            FROM strategy_signal_daily
            WHERE signal_date = CAST(? AS DATE)
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            (date_str,),
        ).fetchall()
    }
    unsupported = {
        "atr_chandelier": "requires position context; no ledger signals emitted without real position/highest_since_entry data",
    }
    con.execute(
        """
        INSERT OR REPLACE INTO strategy_signal_manifest
        VALUES (CAST(? AS DATE), ?, ?, ?, ?, ?, true)
        """,
        (
            date_str,
            created_at,
            str(foundation_db),
            len(rows),
            json.dumps(strategy_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(unsupported, ensure_ascii=False, sort_keys=True),
        ),
    )

    out_json = ledger_db.parent / f"strategy_signal_daily_{ymd(date_str)}.json"
    out_latest = ledger_db.parent / "strategy_signal_daily_latest.json"
    payload = {
        "schema_version": "strategy_signal_daily_v2",
        "date": date_str,
        "generated_at": created_at,
        "foundation_db": str(foundation_db),
        "ledger_db": str(ledger_db),
        "ma2560_rule": str(ma2560_rule_path),
        "recommendation_csv": str(recommendation_path) if recommendation_path else None,
        "signal_count": len(rows),
        "strategy_counts": strategy_counts,
        "unsupported": unsupported,
        "rows": rows,
        "research_only": True,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out_json.write_text(text, encoding="utf-8")
    out_latest.write_text(text, encoding="utf-8")
    con.close()

    return {
        "ok": True,
        "date": date_str,
        "foundation_db": str(foundation_db),
        "ledger_db": str(ledger_db),
        "signal_count": len(rows),
        "strategy_counts": strategy_counts,
        "json": str(out_json),
        "latest_json": str(out_latest),
        "recommendation_csv": str(recommendation_path) if recommendation_path else None,
        "research_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized strategy signal ledger.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--foundation-db", type=Path)
    parser.add_argument("--ledger-db", type=Path, default=LEDGER_DB)
    parser.add_argument("--min-ef", type=int, default=2)
    parser.add_argument("--recommendation-csv", type=Path)
    parser.add_argument("--ma2560-rule", type=Path, default=MA2560_RULE_PATH)
    args = parser.parse_args()
    result = build_ledger(
        args.date,
        args.foundation_db or default_foundation_db(args.date),
        args.ledger_db,
        args.min_ef,
        args.recommendation_csv,
        args.ma2560_rule,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
