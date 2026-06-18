#!/usr/bin/env python3
"""M30 2560 回调二波信号 — 邮件发送

读取最新信号 JSON，生成 HTML 表格邮件发送。

环境变量:
    HERMASS_SMTP_HOST / PORT / USER / PASS / REPORT_TO

用法:
    python3 scripts/send_m30_second_wave_email.py                 # 发送
    python3 scripts/send_m30_second_wave_email.py --dry           # 仅预览 HTML
    python3 scripts/send_m30_second_wave_email.py --date 2026-06-17
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNAL_DIR = ROOT / "outputs" / "research_observer"
REQUIRED_DISCLAIMER = "仅作研究观察，不构成交易建议"


def _smtp_config() -> dict[str, str] | None:
    user = os.environ.get("HERMASS_SMTP_USER", "").strip()
    password = os.environ.get("HERMASS_SMTP_PASS", "").strip()
    if not user or not password:
        return None
    return {
        "host": os.environ.get("HERMASS_SMTP_HOST", "smtp.qq.com"),
        "port": int(os.environ.get("HERMASS_SMTP_PORT", "587")),
        "user": user,
        "password": password,
    }


def _load_signals(obs_date: str | None = None) -> dict:
    if obs_date:
        ymd = obs_date.replace("-", "")
    else:
        candidates = sorted(SIGNAL_DIR.glob("m30_2560_second_wave_*.json"), reverse=True)
        if not candidates:
            return {"signals": [], "scan_date": str(date.today())}
        return json.loads(candidates[0].read_text(encoding="utf-8"))

    path = SIGNAL_DIR / f"m30_2560_second_wave_{ymd}.json"
    if not path.exists():
        return {"signals": [], "scan_date": obs_date}
    return json.loads(path.read_text(encoding="utf-8"))


CSS = """<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#222;background:#f5f7fa}
h1{font-size:20px;margin:0 0 4px 0;color:#1a1a2e}
.date{color:#888;font-size:13px;margin-bottom:16px}
.summary{font-size:14px;padding:14px 18px;background:#fafbfc;border-radius:8px;border-left:3px solid #2F5496;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px}
th{text-align:left;padding:6px 8px;border-bottom:2px solid #dee2e6;color:#555;font-weight:600;background:#f8f9fa}
td{padding:6px 8px;border-bottom:1px solid #eee}
.grade-a{color:#059669;font-weight:700}
.grade-b{color:#d97706;font-weight:700}
.grade-c{color:#dc2626}
.grade-na{color:#9ca3af}
.footer{text-align:center;color:#aaa;font-size:11px;margin-top:24px;padding-top:16px;border-top:1px solid #eee}
.note{font-size:12px;color:#6b7280;margin-top:8px}
</style>"""


def build_html(scan_date: str, signals: list[dict]) -> str:
    a_count = sum(1 for s in signals if s.get("signal_grade") == "A")
    b_count = sum(1 for s in signals if s.get("signal_grade") == "B")
    c_count = sum(1 for s in signals if s.get("signal_grade") == "C")

    rows = ['<!DOCTYPE html><html><head><meta charset="utf-8">' + CSS + "</head><body>"]
    rows.append("<h1>M30 2560 回调二波信号</h1>")
    rows.append(f'<div class="date">扫描日期: {scan_date}</div>')

    rows.append('<div class="summary">')
    rows.append(
        f"共扫描 <b>{len(signals)}</b> 只 · <b style=\"color:#059669\">A类(强) {a_count}</b> · "
        f"<b style=\"color:#d97706\">B类(边界) {b_count}</b> · <b style=\"color:#dc2626\">C类(仅观察) {c_count}</b> · "
        f"淘汰 {len(signals)-a_count-b_count-c_count}"
    )
    rows.append("</div>")

    # ── A + B 类重点表格 ──
    ab = [s for s in signals if s.get("signal_grade") in ("A", "B")]
    if ab:
        rows.append("<h2>🔍 A / B 类观察清单</h2>")
        rows.append("<table>")
        rows.append("<tr><th>等级</th><th>代码</th><th>名称</th><th>W1</th><th>D1</th><th>M30分</th><th>入口</th><th>止损</th><th>风宽</th><th>过热</th></tr>")
        for s in ab:
            g = s.get("signal_grade", "-")
            cls = f"grade-{g.lower()}" if g in ("A", "B") else ""
            rows.append(
                f"<tr>"
                f"<td class=\"{cls}\">{g}</td>"
                f"<td>{s['stock_code']}</td>"
                f"<td>{s.get('stock_name','')}</td>"
                f"<td>{s.get('w1_close_vs_ma25','N/A')}</td>"
                f"<td>{s.get('d1_tier','N/A')}</td>"
                f"<td>{s.get('m30_score','-')}</td>"
                f"<td>¥{s.get('entry_price','-')}</td>"
                f"<td>¥{s.get('stop_price','-')}</td>"
                f"<td>{s.get('risk_width_pct','N/A')}</td>"
                f"<td>{'⚠️' if s.get('overextension_flag') else '-'}</td>"
                f"</tr>"
            )
        rows.append("</table>")

    # ── C 类附注 ──
    c_signals = [s for s in signals if s.get("signal_grade") == "C"]
    if c_signals:
        rows.append("<h2>📋 C 类仅观察（M30 触发但被 W1/D1/过热/风宽否决）</h2>")
        rows.append("<table>")
        rows.append("<tr><th>代码</th><th>名称</th><th>M30分</th><th>否决原因</th></tr>")
        for s in c_signals:
            flags = s.get("risk_flags", [])
            rows.append(
                f"<tr>"
                f"<td>{s['stock_code']}</td>"
                f"<td>{s.get('stock_name','')}</td>"
                f"<td>{s.get('m30_score','-')}</td>"
                f"<td>{', '.join(flags) if flags else '无'}</td>"
                f"</tr>"
            )
        rows.append("</table>")

    rows.append(f'<div class="note"><strong>分级规则：</strong>A 类 = W1上方 + D1强通过 + M30触发 + 无过热；B 类 = W1通过 + D1边界观察 + M30触发；C 类 = M30 触发但被否决</div>')
    rows.append(f'<div class="footer">{REQUIRED_DISCLAIMER}<br>Hermass 2560 SR Observation System</div>')
    rows.append("</body></html>")
    return "\n".join(rows)


def send_email(html_body: str, scan_date: str) -> bool:
    cfg = _smtp_config()
    if not cfg:
        print("SMTP 未配置 (HERMASS_SMTP_USER/PASS)", file=sys.stderr)
        return False

    to_addr = os.environ.get("HERMASS_REPORT_TO", cfg["user"])
    subject = f"M30 2560 回调二波信号 — {scan_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["user"]
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=15)
        server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["user"], [to_addr], msg.as_string())
        server.quit()
        print(f"邮件已发送 → {to_addr}")
        return True
    except Exception as exc:
        print(f"发送失败: {exc}", file=sys.stderr)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M30 2560 回调二波信号邮件发送")
    parser.add_argument("--date", default="", help="信号日期 YYYY-MM-DD，默认取最新")
    parser.add_argument("--dry", action="store_true", help="仅输出 HTML 预览，不发送")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = _load_signals(args.date or None)
    scan_date = data.get("scan_date", str(date.today()))
    signals = data.get("signals", [])
    html = build_html(scan_date, signals)

    if args.dry:
        print(html)
        return 0

    if not signals:
        print("无信号数据")
        return 0

    ok = send_email(html, scan_date)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
