#!/usr/bin/env python3
"""Hermass 每日研究报告 — 邮件正文含摘要 + 附件 State 全景 Excel。

环境变量:
    HERMASS_SMTP_HOST / PORT / USER / PASS / REPORT_TO
    或 .envrc 文件

Usage:
    python3 scripts/send_daily_report.py         # 生成 + 发送
    python3 scripts/send_daily_report.py --dry   # 仅预览
"""

import argparse, json, os, smtplib, sys
from datetime import datetime, timezone, date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "outputs" / "daily_snapshot.json"
CALIBRATION = ROOT / "outputs" / "calibration" / "mn1_stratified_calibration.json"


# ── HTML ──
def _c(v):
    return "#d4edda" if v > 0.02 else ("#fff3cd" if v > 0 else "#f8d7da")


def _b(lvl):
    m = {
        "高": "#28a745",
        "中": "#ffc107",
        "中低": "#fd7e14",
        "低": "#dc3545",
        "噪声": "#6c757d",
        "最优": "#0d6efd",
    }
    return f'<span style="background:{m.get(lvl, "#6c757d")};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px">{lvl}</span>'


CSS = """<style>body{font-family:-apple-system,'Segoe UI',Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#222;background:#f5f7fa}
h1{font-size:20px;margin:0;color:#1a1a2e}.date{color:#888;font-size:13px;margin-bottom:20px}
.card{background:#fff;border-radius:10px;padding:16px 20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h2{font-size:15px;margin:0 0 10px;color:#333;border-bottom:1px solid #eee;padding-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:5px 8px;border-bottom:2px solid #dee2e6;color:#555;font-weight:600}
td{padding:5px 8px;border-bottom:1px solid #eee}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.metric{text-align:center;padding:10px;background:#f0f4ff;border-radius:8px}
.metric .val{font-size:22px;font-weight:700;color:#1a1a2e}.metric .lbl{font-size:11px;color:#888;margin-top:2px}
.footer{text-align:center;color:#aaa;font-size:11px;margin-top:24px;padding-top:16px;border-top:1px solid #eee}
.summary{font-size:14px;line-height:1.7;color:#444;padding:14px 18px;background:#fafbfc;border-radius:8px;border-left:3px solid #2F5496;margin-bottom:16px}
.summary b{color:#2F5496}
</style>"""


def build_html():
    snap = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {}
    report_date = snap.get("date", str(date.today()))
    mkt = snap.get("market", {})
    ef_dist = snap.get("ef_dist", {})

    # Header + Summary
    rows = ['<!DOCTYPE html><html><head><meta charset="utf-8">' + CSS + "</head><body>"]
    rows.append(f"<h1>📊 Hermass Observer 每日研究报告</h1>")
    rows.append(f'<div class="date">{report_date}</div>')

    # Summary paragraph
    total = mkt.get("stocks", 0)
    ef2 = mkt.get("ef2_count", 0)
    ef2_pct = mkt.get("ef2_pct", 0)
    ef3 = ef_dist.get("3", 0)
    avg_d1 = mkt.get("avg_d1_score", 0)

    rows.append('<div class="summary">')
    rows.append(
        f"全市场 <b>{total:,}</b> 只股票中，<b>{ef2:,}</b> 只处于 E/F≥2 强势状态（占比 <b>{ef2_pct}%</b>），"
        f"其中三周期共振 ef=3 共 <b>{ef3:,}</b> 只。"
    )
    rows.append(f"全市场 D1 State 日均 Score = <b>{avg_d1}</b>。")
    # Add AI vs Dividend
    try:
        import duckdb, glob as gb

        dbs = sorted(gb.glob(str(ROOT / "outputs/p116_foundation_20*/p116_foundation.duckdb")))
        if dbs:
            con = duckdb.connect(dbs[-1], read_only=True)
            latest = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]
            fund_db = ROOT / "outputs/fundamental/fundamental_evidence.duckdb"
            fcon = duckdb.connect(str(fund_db), read_only=True)
            idx = dict(
                fcon.execute(
                    "SELECT stock_code, sw_l1 FROM ifind_industry_chain_profile WHERE sw_l1 IS NOT NULL"
                ).fetchall()
            )
            fcon.close()
            ai_set = {"电子", "计算机", "通信"}
            div_set = {"银行", "煤炭", "公用事业", "交通运输", "钢铁"}
            ai_codes = [c for c, i in idx.items() if i in ai_set][:3000]
            div_codes = [c for c, i in idx.items() if i in div_set][:3000]
            ai_f = "('" + "','".join(ai_codes) + "')"
            div_f = "('" + "','".join(div_codes) + "')"
            ai_ef2 = con.execute(
                f"SELECT SUM(CASE WHEN ef_count>=2 THEN 1 ELSE 0 END) FROM d1_perspective_state WHERE state_date=CAST('{latest}' AS DATE) AND stock_code IN {ai_f}"
            ).fetchone()[0]
            div_ef2 = con.execute(
                f"SELECT SUM(CASE WHEN ef_count>=2 THEN 1 ELSE 0 END) FROM d1_perspective_state WHERE state_date=CAST('{latest}' AS DATE) AND stock_code IN {div_f}"
            ).fetchone()[0]
            ai_ef2_pct = round(ai_ef2 / max(len(ai_codes), 1) * 100, 1)
            div_ef2_pct = round(div_ef2 / max(len(div_codes), 1) * 100, 1)
            rows.append(
                f"AI叙事方向（电子+计算机+通信）强势占比 <b>{ai_ef2_pct}%</b>，"
                f"红利低波方向（银行+煤炭+公用+交通） <b>{div_ef2_pct}%</b>。"
            )
            con.close()
    except:
        pass
    rows.append("</div>")

    # 结构预警卡片
    warning_path = ROOT / "outputs" / "daily_warning.json"
    if warning_path.exists():
        try:
            warning = json.loads(warning_path.read_text())
            if warning.get("date") == report_date:
                level = warning.get("alert_level", "green")
                if level != "green":
                    border = {"yellow": "#fff3cd", "orange": "#ffe0b2", "red": "#f8d7da"}.get(
                        level, "#fff3cd"
                    )
                    if level == "red":
                        title = f"🔴 多周期结构同步恶化：{warning.get('message', '')}"
                        detail = (
                            f"D1 负值日增 {warning.get('d1_negative_delta', 0)} 只 | "
                            f"MN1 正值 {warning.get('mn1_positive_pct_delta', 0)}% | "
                            f"高位崩跌 {warning.get('high_to_negative_estimate', 0)} 只"
                        )
                    else:
                        title = f"⚠️ 结构预警：{warning.get('message', '')}"
                        detail = (
                            f"D1 负值日增 {warning.get('d1_negative_delta', 0)} 只 | "
                            f"MN1 正值占比 {warning.get('mn1_positive_pct_delta', 0)}%"
                        )
                    rows.append(
                        f'<div class="card" style="border:1px solid {border}"><h2>{title}</h2>'
                        f'<p style="margin:0 0 8px;color:#555;font-size:13px">{detail}</p>'
                    )
                    if warning.get("breather_trap"):
                        rows.append(
                            '<p style="margin-top:8px;color:#856404;font-size:13px">'
                            "⚠️ 当前 ef2 反弹但月线支撑在收缩——不是止跌确认，防诱多陷阱。</p>"
                        )
                    rows.append("</div>")
        except Exception:
            pass

    # Card 1: Market KPI
    rows.append('<div class="card"><h2>市场概览</h2><div class="grid">')
    rows.append(
        f'<div class="metric"><div class="val">{total:,}</div><div class="lbl">全市场股票</div></div>'
    )
    rows.append(
        f'<div class="metric"><div class="val">{ef2:,}</div><div class="lbl">E/F≥2 ({ef2_pct}%)</div></div>'
    )
    rows.append(
        f'<div class="metric"><div class="val">{avg_d1}</div><div class="lbl">平均 D1 Score</div></div>'
    )
    rows.append("</div>")
    rows.append(
        '<table style="margin-top:10px"><tr><th>ef=0</th><th>ef=1</th><th>ef=2</th><th>ef=3</th></tr><tr>'
    )
    for k in ["0", "1", "2", "3"]:
        rows.append(f"<td>{ef_dist.get(k, 0):,}</td>")
    rows.append("</tr></table></div>")

    # Card 2: Sector Resonance
    try:
        import duckdb, glob as gb2

        dbs2 = sorted(gb2.glob(str(ROOT / "outputs/p116_foundation_20*/p116_foundation.duckdb")))
        if dbs2:
            from hermass_platform.slice.industry_slice import detect_sector_resonance

            res = detect_sector_resonance(dbs2[-1])
            if res:
                rows.append(
                    '<div class="card"><h2>🔥 板块共振 Top 6</h2><table><tr><th>行业</th><th>共振数</th><th>置信</th></tr>'
                )
                for r in res[:6]:
                    rows.append(
                        f"<tr><td><b>{r['sw_l1']}</b></td><td>{r['resonance_count']}只</td><td>{_b(r['confidence'])}</td></tr>"
                    )
                rows.append("</table></div>")
    except:
        pass

    # Card 3: MN1 Calibration
    calib = json.loads(CALIBRATION.read_text()) if CALIBRATION.exists() else {}
    if calib:
        rows.append(
            '<div class="card"><h2>🧠 MN1 分层校准</h2><table><tr><th></th><th>牛市E/F</th><th>震荡C/D</th><th>扩张8-B</th><th>破位</th></tr>'
        )
        for sid in ["vcp", "ma2560", "bollinger_bandit"]:
            sd = calib.get("stratified_results", {}).get(sid, {})
            cels = []
            for r in ["牛市环境_E/F", "震荡偏强_C/D", "扩张未突破_8-B", "破位环境"]:
                rd = sd.get(r, {})
                me = rd.get("weighted_mean_excess", 0)
                cels.append(f'<td style="background:{_c(me)};text-align:center">{me:+.4f}</td>')
            rows.append(f'<tr><td style="font-weight:600">{sid.upper()}</td>{"".join(cels)}</tr>')
        rows.append("</table></div>")

    # 盯盘提醒卡片
    watch_alert_path = ROOT / "outputs" / "watch_alerts.json"
    if watch_alert_path.exists():
        try:
            alerts = json.loads(watch_alert_path.read_text())
            if alerts:
                rows.append(
                    '<div class="card"><h2>🔔 盯盘提醒</h2><table><tr><th>股票</th><th>触发条件</th><th>说明</th><th>触发时间</th></tr>'
                )
                for a in alerts:
                    rows.append(
                        f"<tr><td><b>{a['symbol']}</b></td><td>{a['condition']}</td><td>{a['trigger_desc']}</td><td>{a.get('triggered_at', '')[:19]}</td></tr>"
                    )
                rows.append("</table></div>")
        except Exception:
            pass

    # Footer
    rows.append(
        f'<div class="footer"><p>Hermass Observer 自动生成 · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
        "<p>Research Only · 不构成投资建议</p></div></body></html>"
    )
    return "\n".join(rows)


# ── EXCEL ──
def build_excel() -> Path:
    import subprocess

    script = str(ROOT / "scripts" / "build_state_excel.py")
    r = subprocess.run([sys.executable, script], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"Excel build failed: {r.stderr}")
    info = json.loads(r.stdout)
    return Path(info["path"])


# ── SEND ──
def send_email(html, smtp, to_addrs, attach):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Hermass Observer 每日报告 — {date.today().isoformat()}"
    msg["From"] = smtp["user"]
    msg["To"] = ", ".join(to_addrs)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)
    if attach and attach.exists():
        with open(attach, "rb") as f:
            p = MIMEBase("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            p.set_payload(f.read())
            encoders.encode_base64(p)
            p.add_header("Content-Disposition", f'attachment; filename="{attach.name}"')
            msg.attach(p)
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=30) as s:
        s.starttls()
        s.login(smtp["user"], smtp["password"])
        s.sendmail(smtp["user"], to_addrs, msg.as_string())
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true")
    args = p.parse_args()
    html = build_html()
    if args.dry:
        (ROOT / "outputs/daily_report.html").write_text(html, encoding="utf-8")
        print("HTML 已保存: outputs/daily_report.html")
        return
    excel = build_excel()
    smtp = {
        "host": os.environ.get("HERMASS_SMTP_HOST", "smtp.qq.com"),
        "port": int(os.environ.get("HERMASS_SMTP_PORT", "587")),
        "user": os.environ.get("HERMASS_SMTP_USER", ""),
        "password": os.environ.get("HERMASS_SMTP_PASS", ""),
    }
    to = [t.strip() for t in os.environ.get("HERMASS_REPORT_TO", "").split(",") if t.strip()]
    if not smtp["user"] or not to:
        print("缺少 SMTP 凭据，检查 .envrc")
        sys.exit(1)
    send_email(html, smtp, to, excel)
    print(
        json.dumps(
            {
                "status": "ok",
                "to": to,
                "excel": str(excel),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
