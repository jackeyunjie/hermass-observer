#!/usr/bin/env python3
"""State Timeline Observer 每日摘要邮件。

用法:
    .venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01
    .venv/bin/python scripts/send_state_timeline_digest_email.py --dry
    .venv/bin/python scripts/send_state_timeline_digest_email.py --date 2026-07-01 --user-key visitor_xxx
    .venv/bin/python scripts/send_state_timeline_digest_email.py --dispatch-subscriptions --date 2026-07-01

环境变量:
    HERMASS_SMTP_HOST / PORT / USER / PASS / REPORT_TO
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from collections import defaultdict
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED_DISCLAIMER = "仅作研究观察，不构成交易建议"
SITE_URL = "http://console.supertrader.world/state-observer"


def _smtp_config() -> dict[str, Any] | None:
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


def _load_timeline_rows(
    symbol_set: str,
    days: int,
    anchor_date: str,
    user_key: str | None = None,
) -> list[dict[str, Any]]:
    """读取 State Timeline 数据，失败时返回空列表。"""
    try:
        from agently_adapter.tools.state_timeline_reader import load_state_timeline
    except Exception as exc:
        print(f"导入 state_timeline_reader 失败: {exc}", file=sys.stderr)
        return []

    try:
        if symbol_set == "watchlist":
            if not user_key:
                return []
            return load_state_timeline(
                symbol_set="watchlist",
                days=days,
                date_to=anchor_date,
                user_key=user_key,
            )
        return load_state_timeline(
            symbol_set=symbol_set if symbol_set != "all" else None,
            symbols="all" if symbol_set == "all" else None,
            days=days,
            date_to=anchor_date,
        )
    except Exception as exc:
        print(f"读取 State Timeline 失败: {exc}", file=sys.stderr)
        return []


def _compute_extra_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按股票分组，为最新行补充 ab_change / zero_change。"""
    by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_stock[row["stock_code"]].append(row)

    latest_rows: list[dict[str, Any]] = []
    for code, series in by_stock.items():
        if not series:
            continue
        latest = dict(series[0])
        if len(series) >= 2:
            prev = series[1]
            latest["ab_change"] = (latest.get("ab_count") or 0) - (prev.get("ab_count") or 0)
            latest["zero_change"] = (latest.get("zero_count") or 0) - (prev.get("zero_count") or 0)
        else:
            latest["ab_change"] = None
            latest["zero_change"] = None
        latest_rows.append(latest)
    return latest_rows


def _latest_rows_for_anchor_date(
    all_rows: list[dict[str, Any]],
    anchor_date: str,
) -> list[dict[str, Any]]:
    """从多日长表中提取 anchor_date 当天的每股最新行，并补 ab/zero 变化。"""
    latest_rows = _compute_extra_changes(all_rows)
    return [r for r in latest_rows if r.get("state_date") == anchor_date]


def _change_strength(row: dict[str, Any]) -> int:
    return (
        abs(row.get("ef_change") or 0)
        + abs(row.get("ab_change") or 0)
        + abs(row.get("zero_change") or 0)
    )


def _escape_html(text: Any) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


CSS = """<style>
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:900px;margin:0 auto;padding:20px;color:#222;background:#f5f7fa}
h1{font-size:20px;margin:0 0 4px 0;color:#1a1a2e}
h2{font-size:15px;margin:24px 0 10px 0;color:#1a1a2e;border-left:3px solid #2F5496;padding-left:8px}
.date{color:#888;font-size:13px;margin-bottom:16px}
.summary{font-size:14px;padding:14px 18px;background:#fafbfc;border-radius:8px;border-left:3px solid #2F5496;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:12px;background:#fff}
th{text-align:left;padding:6px 8px;border-bottom:2px solid #dee2e6;color:#555;font-weight:600;background:#f8f9fa}
td{padding:6px 8px;border-bottom:1px solid #eee}
.ef{color:#059669;font-weight:700}
.ab{color:#2563eb;font-weight:700}
.zero{color:#7c3aed;font-weight:700}
.changed{background:#fffbeb}
.footer{text-align:center;color:#888;font-size:11px;margin-top:24px;padding-top:16px;border-top:1px solid #eee}
.note{font-size:12px;color:#6b7280;margin-top:8px}
.empty{color:#9ca3af;font-style:italic;padding:12px 0}
a{color:#2563eb}
</style>"""


def build_html(
    anchor_date: str,
    latest_rows: list[dict[str, Any]],
    changed_rows: list[dict[str, Any]],
    watchlist_rows: list[dict[str, Any]],
) -> str:
    rows: list[str] = ['<!DOCTYPE html><html><head><meta charset="utf-8">' + CSS + "</head><body>"]
    rows.append("<h1>State Timeline Observer 每日摘要</h1>")
    rows.append(f'<div class="date">数据日期: {anchor_date}</div>')

    # 顶部摘要
    total = len(latest_rows)
    changed = sum(1 for r in latest_rows if r.get("state_change_flag"))
    ef_rows = sum(1 for r in latest_rows if r.get("ef_count", 0) > 0)
    ab_rows = sum(1 for r in latest_rows if r.get("ab_count", 0) > 0)
    zero_rows = sum(1 for r in latest_rows if r.get("zero_count", 0) > 0)
    rows.append('<div class="summary">')
    rows.append(
        f"共 <b>{total}</b> 只标的 · <b class='ef'>EF {ef_rows}</b> · "
        f"<b class='ab'>A/B {ab_rows}</b> · <b class='zero'>0 {zero_rows}</b> · "
        f"今日状态变化 <b>{changed}</b> 只"
    )
    rows.append("</div>")

    # 最近状态变化 Top20
    rows.append("<h2>🔥 今日状态变化最大 Top20</h2>")
    if changed_rows:
        rows.append("<table>")
        rows.append("<tr><th>代码</th><th>名称</th><th>行业</th><th>状态</th><th>变化</th><th>EFΔ</th><th>A/BΔ</th><th>0Δ</th><th>transition</th></tr>")
        for r in changed_rows[:20]:
            cls = "changed" if r.get("state_change_flag") else ""
            rows.append(
                f"<tr class='{cls}'>"
                f"<td>{_escape_html(r['stock_code'])}</td>"
                f"<td>{_escape_html(r.get('stock_name','-'))}</td>"
                f"<td>{_escape_html(r.get('industry_l1','-'))}</td>"
                f"<td>{_escape_html(r.get('state_triplet','-'))}</td>"
                f"<td>{'变' if r.get('state_change_flag') else '-'}</td>"
                f"<td>{_fmt_delta(r.get('ef_change'))}</td>"
                f"<td>{_fmt_delta(r.get('ab_change'))}</td>"
                f"<td>{_fmt_delta(r.get('zero_change'))}</td>"
                f"<td>{_escape_html(r.get('transition_label','-'))}</td>"
                f"</tr>"
            )
        rows.append("</table>")
    else:
        rows.append('<div class="empty">今日无状态变化</div>')

    # 分周期样本
    _append_period_section(rows, "月线 EF", latest_rows, "mn1_is_ef", "ef")
    _append_period_section(rows, "周线 EF", latest_rows, "w1_is_ef", "ef")
    _append_period_section(rows, "日线 EF", latest_rows, "d1_is_ef", "ef")
    _append_period_section(rows, "月线 A/B", latest_rows, "mn1_is_ab", "ab")
    _append_period_section(rows, "周线 A/B", latest_rows, "w1_is_ab", "ab")
    _append_period_section(rows, "日线 A/B", latest_rows, "d1_is_ab", "ab")
    _append_period_section(rows, "月线 0", latest_rows, "mn1_is_zero", "zero")
    _append_period_section(rows, "周线 0", latest_rows, "w1_is_zero", "zero")
    _append_period_section(rows, "日线 0", latest_rows, "d1_is_zero", "zero")

    # 周期交集样本
    _append_pattern_section(rows, "EF 周期交集", latest_rows, "ef_pattern")
    _append_pattern_section(rows, "A/B 周期交集", latest_rows, "ab_pattern")
    _append_pattern_section(rows, "0 周期交集", latest_rows, "zero_pattern")

    # watchlist 最近 3 天变化
    if watchlist_rows:
        rows.append("<h2>⭐ 自选池最近 3 天变化</h2>")
        rows.append("<table>")
        rows.append("<tr><th>代码</th><th>名称</th><th>日期</th><th>状态</th><th>变化</th><th>transition</th></tr>")
        for r in watchlist_rows[:30]:
            rows.append(
                f"<tr>"
                f"<td>{_escape_html(r['stock_code'])}</td>"
                f"<td>{_escape_html(r.get('stock_name','-'))}</td>"
                f"<td>{_escape_html(r['state_date'])}</td>"
                f"<td>{_escape_html(r.get('state_triplet','-'))}</td>"
                f"<td>{'变' if r.get('state_change_flag') else '-'}</td>"
                f"<td>{_escape_html(r.get('transition_label','-'))}</td>"
                f"</tr>"
            )
        rows.append("</table>")

    # 底部免责声明与回链
    rows.append(f'<div class="note"><strong>说明：</strong>本邮件仅汇总 State 结构观察事实，不提供交易建议、操作指引或价格预测。</div>')
    rows.append(f'<div class="footer">{REQUIRED_DISCLAIMER}<br><a href="{SITE_URL}">{SITE_URL}</a><br>Hermass State Timeline Observer</div>')
    rows.append("</body></html>")
    return "\n".join(rows)


def _fmt_delta(value: Any) -> str:
    if value is None:
        return "-"
    try:
        n = int(value)
        return f"+{n}" if n > 0 else str(n)
    except (TypeError, ValueError):
        return str(value)


def _append_period_section(
    rows: list[str],
    title: str,
    latest_rows: list[dict[str, Any]],
    flag_field: str,
    family: str,
) -> None:
    samples = [r for r in latest_rows if r.get(flag_field)][:10]
    rows.append(f"<h2>{_family_emoji(family)} {title}</h2>")
    if samples:
        rows.append("<table>")
        rows.append("<tr><th>代码</th><th>名称</th><th>行业</th><th>状态</th><th>模式</th><th>收盘价</th></tr>")
        for r in samples:
            pattern = r.get(f"{family}_pattern", "-")
            rows.append(
                f"<tr>"
                f"<td>{_escape_html(r['stock_code'])}</td>"
                f"<td>{_escape_html(r.get('stock_name','-'))}</td>"
                f"<td>{_escape_html(r.get('industry_l1','-'))}</td>"
                f"<td>{_escape_html(r.get('state_triplet','-'))}</td>"
                f"<td>{_escape_html(pattern)}</td>"
                f"<td>{r.get('close','-')}</td>"
                f"</tr>"
            )
        rows.append("</table>")
    else:
        rows.append('<div class="empty">无样本</div>')


def _append_pattern_section(
    rows: list[str],
    title: str,
    latest_rows: list[dict[str, Any]],
    pattern_field: str,
) -> None:
    interesting = ["MN1+W1+D1", "MN1+W1", "W1+D1", "MN1+D1"]
    rows.append(f"<h2>{title}</h2>")
    any_shown = False
    for pat in interesting:
        samples = [r for r in latest_rows if r.get(pattern_field) == pat][:10]
        if not samples:
            continue
        any_shown = True
        rows.append(f"<div class='note'>{pat}（最多 10 只）</div>")
        rows.append("<table>")
        rows.append("<tr><th>代码</th><th>名称</th><th>行业</th><th>状态</th><th>收盘价</th></tr>")
        for r in samples:
            rows.append(
                f"<tr>"
                f"<td>{_escape_html(r['stock_code'])}</td>"
                f"<td>{_escape_html(r.get('stock_name','-'))}</td>"
                f"<td>{_escape_html(r.get('industry_l1','-'))}</td>"
                f"<td>{_escape_html(r.get('state_triplet','-'))}</td>"
                f"<td>{r.get('close','-')}</td>"
                f"</tr>"
            )
        rows.append("</table>")
    if not any_shown:
        rows.append('<div class="empty">无样本</div>')


def _family_emoji(family: str) -> str:
    return {"ef": "📈", "ab": "📊", "zero": "🎯"}.get(family, "•")


def send_email(
    html_body: str,
    anchor_date: str,
    to_addr: str | None = None,
) -> bool:
    cfg = _smtp_config()
    if not cfg:
        print("SMTP 未配置 (HERMASS_SMTP_USER/PASS)，跳过发送", file=sys.stderr)
        return False

    to_addr = (to_addr or os.environ.get("HERMASS_REPORT_TO", cfg["user"])).strip()
    subject = f"State Timeline Observer 每日摘要 — {anchor_date}"

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


def _load_subscriptions(ledger_path: Path | None = None) -> list[dict[str, Any]]:
    """从 user_task_ledger 读取 active 的 state_timeline_digest 订阅。"""
    try:
        from agently_adapter.tools.user_tasks import load_user_task_ledger
        ledger = load_user_task_ledger(ledger_path)
    except Exception as exc:
        print(f"读取订阅账本失败: {exc}", file=sys.stderr)
        return []

    subs: list[dict[str, Any]] = []
    for task in ledger.get("tasks", []) or []:
        if task.get("task_type") != "state_timeline_digest":
            continue
        if task.get("status") != "active":
            continue
        email = str(task.get("email") or "").strip()
        if not email:
            continue
        subs.append(task)
    return subs


def _send_one_digest(
    anchor_date: str,
    symbol_set: str,
    days: int,
    user_key: str,
    to_addr: str,
    dry: bool,
) -> bool:
    """为单个订阅生成并发送邮件；dry 时输出 HTML。

    返回 True 表示数据非空且已处理（dry 或真实发送）。
    数据为空返回 False；发送失败抛异常。
    """
    all_rows = _load_timeline_rows(symbol_set, days, anchor_date, user_key)
    if not all_rows:
        return False

    latest_rows = _latest_rows_for_anchor_date(all_rows, anchor_date)
    changed_rows = sorted(
        [r for r in latest_rows if r.get("state_change_flag")],
        key=_change_strength,
        reverse=True,
    )

    watchlist_rows: list[dict[str, Any]] = []
    if user_key:
        watchlist_rows = _load_timeline_rows("watchlist", 3, anchor_date, user_key)

    html = build_html(anchor_date, latest_rows, changed_rows, watchlist_rows)

    if dry:
        print(html)
        return True

    if not send_email(html, anchor_date, to_addr=to_addr):
        raise RuntimeError("邮件发送失败或 SMTP 未配置")
    return True


def _dispatch_subscriptions(
    anchor_date: str,
    dry: bool = False,
    ledger_path: Path | None = None,
) -> int:
    """按订阅批量派发，单个失败不影响其他订阅。"""
    subs = _load_subscriptions(ledger_path)
    if not subs:
        print(f"未找到 {anchor_date} 的 active state_timeline_digest 订阅")
        return 0

    total = len(subs)
    success = 0
    for idx, sub in enumerate(subs, 1):
        task_id = sub.get("task_id", f"sub_{idx}")
        email = sub["email"]
        symbol_set = str(sub.get("symbol_set") or "all").strip() or "all"
        days = int(sub.get("days") or 2)
        user_key = str(sub.get("created_by") or "").strip()

        label = f"{task_id} email={email} symbol_set={symbol_set} days={days}"
        try:
            ok = _send_one_digest(
                anchor_date=anchor_date,
                symbol_set=symbol_set,
                days=days,
                user_key=user_key,
                to_addr=email,
                dry=dry,
            )
            if ok:
                print(f"[DISPATCH OK {idx}/{total}] {label}")
                success += 1
            else:
                print(f"[DISPATCH EMPTY {idx}/{total}] {label}")
        except Exception as exc:
            print(f"[DISPATCH FAIL {idx}/{total}] {label}: {exc}", file=sys.stderr)

    print(f"派发完成: {success}/{total} 成功")
    return 0 if success == total else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="State Timeline Observer 每日摘要邮件")
    parser.add_argument("--date", default=str(date.today()), help="数据日期 YYYY-MM-DD")
    parser.add_argument("--dry", action="store_true", help="仅输出 HTML 预览，不发送")
    parser.add_argument("--symbol-set", default="all", help="股票集合: all / top50 / watchlist")
    parser.add_argument("--days", type=int, default=2, help="观察窗口天数，默认 2")
    parser.add_argument("--user-key", default="", help="watchlist 用户标识")
    parser.add_argument(
        "--dispatch-subscriptions",
        action="store_true",
        help="从 user_task_ledger 读取订阅并批量派发",
    )
    parser.add_argument(
        "--subscription-ledger",
        type=Path,
        default=None,
        help="（测试用）指定订阅账本路径",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anchor_date = args.date

    if args.dispatch_subscriptions:
        return _dispatch_subscriptions(
            anchor_date=anchor_date,
            dry=args.dry,
            ledger_path=args.subscription_ledger,
        )

    # 单次发送模式
    ok = _send_one_digest(
        anchor_date=anchor_date,
        symbol_set=args.symbol_set,
        days=max(2, args.days),
        user_key=args.user_key if args.symbol_set == "watchlist" else "",
        to_addr=os.environ.get("HERMASS_REPORT_TO", ""),
        dry=args.dry,
    )
    if not ok and not args.dry:
        print(f"未读取到 {anchor_date} 的 State Timeline 数据或发送失败", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
