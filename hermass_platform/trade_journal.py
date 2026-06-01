from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

from hermass_platform.agents.base_agent import find_foundation_db

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "outputs" / "trades.db"
STATE_HUMAN_MAPPING_PATH = ROOT / "config" / "state_human_mapping.json"

STRATEGY_LABELS = {
    "vcp": "VCP 突破",
    "ma2560": "MA2560",
    "bollinger_bandit": "布林强盗",
    "ef": "E/F 信号",
    "composite": "复合策略",
    "watch_command": "盯盘",
}


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT 'hermass-test',
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT 'long',
            entry_price REAL NOT NULL,
            exit_price REAL,
            strategy_id TEXT NOT NULL DEFAULT '',
            stop_loss REAL,
            mn1_state_name TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trade_journal_user
        ON trade_journal(username, trade_date)
        """
    )
    return conn


def _load_state_human_mapping() -> dict[str, Any]:
    if not STATE_HUMAN_MAPPING_PATH.exists():
        return {}
    try:
        return json.loads(STATE_HUMAN_MAPPING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _hex_to_state_name(hex_value: Any) -> str:
    raw = str(hex_value or "").strip()
    if not raw or raw == "-":
        return ""

    mapping = _load_state_human_mapping()
    name_map = {str(k).upper(): str(v) for k, v in mapping.get("hex_to_name", {}).items()}
    negative_name = str(mapping.get("negative_hex_to_name", "逆位"))

    is_negative = raw.startswith("-")
    text = raw[1:] if is_negative else raw
    try:
        key = str(int(text, 16))
    except Exception:
        key = text.upper()

    name = name_map.get(key, "")
    if is_negative:
        return negative_name
    return name


def _resolve_mn1_state_name(
    stock_code: str,
    trade_date: str,
    provided_name: Optional[str],
) -> str:
    if provided_name:
        return str(provided_name)
    db = find_foundation_db(trade_date)
    if db is None:
        return ""
    con = None
    try:
        con = duckdb.connect(str(db), read_only=True)
        row = con.execute(
            """
            SELECT mn1_state_hex
            FROM d1_perspective_state
            WHERE stock_code = ?
              AND state_date <= CAST(? AS DATE)
            ORDER BY state_date DESC
            LIMIT 1
            """,
            [stock_code, trade_date],
        ).fetchone()
        hex_value = row[0] if row else None
    except Exception:
        hex_value = None
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
    return _hex_to_state_name(hex_value)


def _calc_pnl(row: sqlite3.Row) -> Optional[float]:
    entry = row["entry_price"]
    exit_price = row["exit_price"]
    if entry is not None and exit_price is not None and float(entry) != 0:
        return round((float(exit_price) - float(entry)) / float(entry) * 100, 2)
    return None


def add_trade(
    username: str,
    trade_date: str,
    stock_code: str,
    stock_name: str,
    direction: str,
    entry_price: float,
    exit_price: Optional[float],
    strategy_id: str,
    stop_loss: Optional[float],
    mn1_state_name: Optional[str] = None,
    note: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    username = username or "hermass-test"
    stock_code = "".join(ch for ch in str(stock_code) if ch.isdigit())[:6]
    mn1 = _resolve_mn1_state_name(stock_code, trade_date, mn1_state_name)
    now = datetime.now(timezone.utc).isoformat()
    conn = _conn(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO trade_journal
                (username, trade_date, stock_code, stock_name, direction, entry_price, exit_price, strategy_id, stop_loss, mn1_state_name, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                trade_date,
                stock_code,
                stock_name,
                direction,
                entry_price,
                exit_price,
                strategy_id,
                stop_loss,
                mn1,
                note,
                now,
            ),
        )
        trade_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return {
        "id": trade_id,
        "username": username,
        "trade_date": trade_date,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "strategy_id": strategy_id,
        "stop_loss": stop_loss,
        "mn1_state_name": mn1,
        "note": note,
        "created_at": now,
    }


def list_trades(
    username: str,
    strategy_filter: str = "",
    state_filter: str = "",
    page: int = 1,
    per_page: int = 10,
    db_path: Path | None = None,
) -> dict[str, Any]:
    username = username or "hermass-test"
    page = max(int(page), 1)
    per_page = max(int(per_page), 1)
    offset = (page - 1) * per_page
    conn = _conn(db_path)
    try:
        where = ["username = ?"]
        params: list[Any] = [username]
        if strategy_filter:
            where.append("strategy_id = ?")
            params.append(str(strategy_filter))
        if state_filter:
            where.append("mn1_state_name = ?")
            params.append(str(state_filter))
        where_sql = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) FROM trade_journal WHERE {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM trade_journal WHERE {where_sql} ORDER BY trade_date DESC, id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        trades: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["pnl_pct"] = _calc_pnl(row)
            item["hold_days"] = None
            item["strategy_label"] = STRATEGY_LABELS.get(
                item.get("strategy_id", ""), item.get("strategy_id", "")
            )
            trades.append(item)
        pages = max((total + per_page - 1) // per_page, 1)
        return {
            "trades": trades,
            "total": total,
            "page": page,
            "pages": pages,
        }
    finally:
        conn.close()


def get_filters(
    username: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    username = username or "hermass-test"
    conn = _conn(db_path)
    try:
        strategies = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT strategy_id FROM trade_journal WHERE username = ? AND strategy_id != ''",
                [username],
            ).fetchall()
        ]
        states = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT mn1_state_name FROM trade_journal WHERE username = ? AND mn1_state_name != ''",
                [username],
            ).fetchall()
        ]
        return {"strategies": sorted(strategies), "states": sorted(states)}
    finally:
        conn.close()


def get_trade_stats(
    username: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    username = username or "hermass-test"
    conn = _conn(db_path)
    try:
        rows = conn.execute(
            "SELECT strategy_id, mn1_state_name, entry_price, exit_price FROM trade_journal WHERE username = ?",
            [username],
        ).fetchall()
    finally:
        conn.close()

    total_trades = len(rows)
    pnls: list[float] = []
    gains: list[float] = []
    losses: list[float] = []
    by_strategy: dict[str, list[sqlite3.Row]] = {}
    by_state: dict[str, list[sqlite3.Row]] = {}

    for row in rows:
        pnl = _calc_pnl(row)
        if pnl is not None:
            pnls.append(pnl)
            if pnl > 0:
                gains.append(pnl)
            elif pnl < 0:
                losses.append(abs(pnl))
        sid = str(row["strategy_id"] or "未知策略")
        st = str(row["mn1_state_name"] or "未知环境")
        by_strategy.setdefault(sid, []).append(row)
        by_state.setdefault(st, []).append(row)

    wins = len(gains)
    loss_count = len(losses)
    win_rate = (wins / len(pnls) * 100) if pnls else 0.0
    avg_gain = (sum(gains) / wins) if wins else 0.0
    avg_loss = (sum(losses) / loss_count) if loss_count else 0.0
    profit_factor = (avg_gain / avg_loss) if avg_loss else (999.0 if avg_gain > 0 else 0.0)
    total_return = round(sum(pnls), 2)

    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    max_drawdown = round(-max_dd, 2)

    strategy_stats = []
    for sid, items in sorted(by_strategy.items()):
        n = len(items)
        sp = [_calc_pnl(i) for i in items if _calc_pnl(i) is not None]
        sw = sum(1 for p in sp if p > 0)
        avg_g = (sum(p for p in sp if p > 0) / sw) if sw else 0.0
        avg_l = (sum(abs(p) for p in sp if p < 0) / (len(sp) - sw)) if (len(sp) - sw) else 0.0
        pf = (avg_g / avg_l) if avg_l else (999.0 if avg_g > 0 else 0.0)
        strategy_stats.append(
            {
                "strategy_id": sid,
                "strategy_label": STRATEGY_LABELS.get(sid, sid),
                "count": n,
                "win_rate": round(sw / n * 100, 1) if n else 0.0,
                "profit_factor": round(pf, 2),
                "share": round(n / total_trades * 100, 1) if total_trades else 0.0,
            }
        )

    state_stats = []
    for st, items in sorted(by_state.items()):
        n = len(items)
        sp = [_calc_pnl(i) for i in items if _calc_pnl(i) is not None]
        sw = sum(1 for p in sp if p > 0)
        avg_g = (sum(p for p in sp if p > 0) / sw) if sw else 0.0
        avg_l = (sum(abs(p) for p in sp if p < 0) / (len(sp) - sw)) if (len(sp) - sw) else 0.0
        pf = (avg_g / avg_l) if avg_l else (999.0 if avg_g > 0 else 0.0)
        state_stats.append(
            {
                "state_name": st,
                "count": n,
                "win_rate": round(sw / n * 100, 1) if n else 0.0,
                "profit_factor": round(pf, 2),
            }
        )

    insight = _build_insight(strategy_stats, state_stats)
    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "total_return": total_return,
        "max_drawdown": max_drawdown,
        "by_strategy": strategy_stats,
        "by_state": state_stats,
        "insight": insight,
    }


def _build_insight(
    strategy_stats: list[dict[str, Any]],
    state_stats: list[dict[str, Any]],
) -> str:
    best_strategy = max(strategy_stats, key=lambda x: x["win_rate"]) if strategy_stats else None
    worst_state = min(state_stats, key=lambda x: x["win_rate"]) if state_stats else None

    strategy_part = (
        f"{best_strategy['strategy_label']}胜率最高（{best_strategy['win_rate']:.1f}%）"
        if best_strategy
        else "暂无策略归因"
    )
    state_part = (
        f"{worst_state['state_name']}的操作全部亏损"
        if worst_state and worst_state["win_rate"] == 0
        else f"{worst_state['state_name']}的操作胜率最低（{worst_state['win_rate']:.1f}%）"
        if worst_state
        else "暂无环境归因"
    )
    return f"你在{strategy_part}，{state_part}。建议只在 ef≥2 + MN1 正值时使用趋势类策略。"


def delete_trade(
    trade_id: int,
    username: str,
    db_path: Path | None = None,
) -> bool:
    username = username or "hermass-test"
    conn = _conn(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM trade_journal WHERE id = ? AND username = ?",
            (int(trade_id), username),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
