#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.agents.base_agent import find_foundation_db

LEDGER = ROOT / "outputs" / "alerts" / "watch_command_ledger.json"
SENT_LEDGER = ROOT / "outputs" / "alerts" / "watch_command_email_sent.json"
FUNDAMENTAL_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


@dataclass
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _smtp_config() -> SMTPConfig | None:
    user = os.environ.get("HERMASS_SMTP_USER", "").strip()
    password = os.environ.get("HERMASS_SMTP_PASS", "").strip()
    if not user or not password:
        return None
    return SMTPConfig(
        host=os.environ.get("HERMASS_SMTP_HOST", "smtp.qq.com"),
        port=int(os.environ.get("HERMASS_SMTP_PORT", "587")),
        user=user,
        password=password,
    )


def _stock_name_map() -> dict[str, str]:
    if not FUNDAMENTAL_DB.exists():
        return {}
    con = duckdb.connect(str(FUNDAMENTAL_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT DISTINCT stock_code, stock_name
            FROM ifind_industry_chain_profile
            WHERE stock_code IS NOT NULL AND stock_name IS NOT NULL AND stock_name != ''
            """
        ).fetchall()
        return {str(code).upper(): str(name) for code, name in rows}
    finally:
        con.close()


def _state_snapshot(stock_code: str, as_of_date: str) -> dict[str, Any]:
    foundation = find_foundation_db(as_of_date)
    con = duckdb.connect(str(foundation), read_only=True)
    try:
        row = con.execute(
            """
            SELECT state_date, mn1_state_hex, w1_state_hex, d1_state_hex, d1_state_score, ef_count
            FROM d1_perspective_state
            WHERE stock_code = ? AND state_date <= CAST(? AS DATE)
            ORDER BY state_date DESC
            LIMIT 1
            """,
            [stock_code, as_of_date],
        ).fetchone()
        if not row:
            return {}
        return {
            "state_date": str(row[0]),
            "mn1": row[1] or "-",
            "w1": row[2] or "-",
            "d1": row[3] or "-",
            "d1_score": row[4],
            "ef_count": row[5],
        }
    finally:
        con.close()


def _should_fire(record: dict[str, Any], snapshot: dict[str, Any]) -> tuple[bool, str]:
    trigger_type = str(record.get("trigger_type") or "")
    if not snapshot:
        return False, "缺少状态快照"
    if trigger_type == "long_term_watch":
        return True, "长期跟踪摘要更新"
    if trigger_type == "w1_breakout":
        if snapshot.get("w1") in {"E", "F"}:
            return True, f"W1 当前为 {snapshot.get('w1')}，已进入周线强结构区。"
        return False, f"W1 当前为 {snapshot.get('w1')}，尚未进入周线强结构区。"
    if trigger_type == "state_drop":
        if snapshot.get("d1") not in {"E", "F"}:
            return True, f"D1 当前为 {snapshot.get('d1')}，已脱离 E/F。"
        return False, f"D1 当前仍为 {snapshot.get('d1')}。"
    if trigger_type == "d1_weakening_3d":
        score = snapshot.get("d1_score")
        if score is not None and int(score) < 10:
            return True, f"D1 score 当前为 {score}，已进入偏弱区。"
        return False, f"D1 score 当前为 {score}。"
    return False, "当前 trigger_type 尚未实现自动判断。"


def _compose_email(record: dict[str, Any], stock_name: str, snapshot: dict[str, Any], reason: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    stock_code = record["stock_code"]
    subject = f"[Hermass 盯盘提醒] {stock_name or stock_code} - {record.get('note') or record.get('trigger_type')}"
    msg["Subject"] = subject
    body = f"""
<html><body>
<h3>Hermass 盯盘提醒</h3>
<p><b>股票：</b>{stock_name or stock_code}（{stock_code}）</p>
<p><b>提醒类型：</b>{record.get('note') or record.get('trigger_type')}</p>
<p><b>触发原因：</b>{reason}</p>
<p><b>多周期状态：</b>MN1={snapshot.get('mn1','-')} / W1={snapshot.get('w1','-')} / D1={snapshot.get('d1','-')}</p>
<p><b>单周期位置：</b>D1 score={snapshot.get('d1_score','-')} / ef_count={snapshot.get('ef_count','-')}</p>
<p><b>状态日期：</b>{snapshot.get('state_date','-')}</p>
<p><b>研究入口：</b><a href="http://console.supertrader.world/research?stock_code={stock_code}&render_profile=value">打开价值组合研究</a></p>
<p style="color:#666">以上为研究观察，不构成投资建议。</p>
</body></html>
""".strip()
    msg.attach(MIMEText(body, "html", "utf-8"))
    return msg


def _send_email(cfg: SMTPConfig, to_addr: str, msg: MIMEMultipart) -> None:
    msg["From"] = cfg.user
    msg["To"] = to_addr
    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as server:
        server.starttls()
        server.login(cfg.user, cfg.password)
        server.sendmail(cfg.user, [to_addr], msg.as_string())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    smtp = _smtp_config()
    ledger = _load_json(LEDGER, {"version": "1.0.0", "commands": []})
    sent = _load_json(SENT_LEDGER, {"version": "1.0.0", "sent_keys": []})
    sent_keys = set(sent.get("sent_keys", []))
    name_map = _stock_name_map()

    fired: list[dict[str, Any]] = []
    for record in ledger.get("commands", []):
        if record.get("status") != "active":
            continue
        valid_to = str(record.get("valid_to") or "")
        if valid_to and valid_to < args.date:
            continue
        key = f"{args.date}:{record.get('watch_id')}:{record.get('trigger_type')}"
        if key in sent_keys:
            continue
        snapshot = _state_snapshot(record["stock_code"], args.date)
        should_fire, reason = _should_fire(record, snapshot)
        if not should_fire:
            continue
        stock_name = name_map.get(str(record["stock_code"]).upper(), "")
        fired.append(
            {
                "watch_id": record["watch_id"],
                "stock_code": record["stock_code"],
                "stock_name": stock_name,
                "email": record["email"],
                "reason": reason,
                "snapshot": snapshot,
            }
        )
        if not args.dry and smtp:
            msg = _compose_email(record, stock_name, snapshot, reason)
            _send_email(smtp, record["email"], msg)
            sent_keys.add(key)
            record["last_triggered_at"] = datetime.now(timezone.utc).isoformat()

    if not args.dry and smtp:
        sent["sent_keys"] = sorted(sent_keys)[-2000:]
        _save_json(SENT_LEDGER, sent)
        _save_json(LEDGER, ledger)

    print(json.dumps({"date": args.date, "fired_count": len(fired), "fired": fired}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
