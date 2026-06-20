#!/usr/bin/env python3
"""重建 outputs/debate_dashboard.html — 把"系统关键指标"区从硬编码换成运行时真相源。

被 Codex 审计 2026-06-19 标为风险点（结论在 docs/debate_dashboard_review_20260619.md）：
    看板核心"审计"指标是硬编码文案，不是运行时真相源，时间一过就会误导。
        outputs/debate_dashboard.html:311 写死了 最新 state_date: 2026-06-18，
        同段还写死 hermes_cron 正常运行、测试数、web/main.py 行数等。

真相源（按指标）：
  - 数据新鲜度 / state_date       -> outputs/reviews/self_review_latest.json
  - hermes_cron 状态              -> launchctl list 输出
  - 测试文件数                    -> tests/unit/*.test_*.py glob
  - web/main.py 行数              -> wc -l web/main.py
  - 评分方法生成日期（口径说明行）  -> 当前日期

不改写"五方观点 / 评分明细 / 仓位矛盾"等一次性分析结论 — 它们是快照。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "outputs" / "debate_dashboard.html"
SELF_REVIEW = ROOT / "outputs" / "reviews" / "self_review_latest.json"
TESTS_DIR = ROOT / "tests" / "unit"
MAIN_PY = ROOT / "web" / "main.py"
LAUNCHD_LABEL = "com.hermass.hermes-cron"
MOBILE_STYLE_ID = "mobile-responsive"
MOBILE_CSS = f"""<style id="{MOBILE_STYLE_ID}">
/* MOBILE_RESPONSIVE_INJECTED */
@media (max-width:640px) {{
  .wrap {{ padding: 0 12px; }}
  .section {{ padding: 28px 0; }}
  .section-head {{ align-items:flex-start; }}
  .section-title {{ font-size: 1.08em; }}
  .grid-2 {{ grid-template-columns: 1fr; gap: 14px; }}
  .persona-grid {{ grid-template-columns: 1fr; }}
  .metric-grid {{ grid-template-columns: 1fr 1fr; }}
  .conclusion-grid {{ grid-template-columns: 1fr; gap: 14px; }}
  .contra-vals {{ flex-direction: column; gap: 12px; }}
  .chart-box {{ height: 220px; }}
  .chart-box canvas {{ max-height: 220px; }}
  .verdict {{ padding: 16px 18px; font-size: 0.88em; line-height: 1.8; }}
  .persona, .card {{ padding: 16px; }}
  .metric .big {{ font-size: 1.5em; }}
  body {{ font-size: 14px; }}
  .cta-group {{ flex-direction: column; align-items: stretch; }}
  .cta-group a {{ width: 100%; justify-content: center; }}
  .tbl {{ display: block; overflow-x: auto; white-space: nowrap; }}
}}
</style>"""


def _read_self_review() -> dict:
    if not SELF_REVIEW.exists():
        return {}
    try:
        return json.loads(SELF_REVIEW.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] self_review_latest.json 解析失败: {exc}", file=sys.stderr)
        return {}


def _launchd_status() -> tuple[bool, str]:
    """读 launchd 中 hermes_cron 状态。返回 (running, detail)。

    launchctl list 输出格式：PID  LastExitStatus  Label
    PID 为 "-" 或 0 表示未运行，> 0 表示在跑。
    """
    try:
        out = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except Exception as exc:
        return False, f"launchctl 不可用: {exc}"
    for line in out.splitlines():
        if LAUNCHD_LABEL in line:
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit() and int(parts[0]) > 0:
                return True, f"PID {parts[0]} 运行中"
            last_exit = parts[1] if len(parts) >= 2 and parts[1].lstrip("-").isdigit() else "?"
            return False, f"未运行（last exit {last_exit}）"
    return False, "未注册"


def _data_freshness() -> tuple[str, str, str]:
    """从 self_review_latest.json 读新鲜度。返回 (text, color, latest_date)。

    text 形如 "1天"/"48h"；color 是 CSS var name；latest_date 是 YYYYMMDD 字串。
    注：sub_label 不带"最新 state_date: " 前缀，因为 prefix 已经在 regex group 3 里。
    """
    sr = _read_self_review()
    df = (sr.get("checks") or {}).get("data_freshness") or {}
    if not df:
        return "—", "--yellow", "无数据"
    hours_ago = float(df.get("hours_ago") or 0)
    latest = str(df.get("latest_date") or "?")
    stale = bool(df.get("stale"))
    if hours_ago <= 24:
        text = f"{max(1, int(round(hours_ago / 24)))}天"
        color = "--green" if not stale else "--yellow"
    elif hours_ago <= 48:
        text = f"{int(hours_ago)}h"
        color = "--yellow" if not stale else "--red"
    else:
        text = f"{int(hours_ago)}h"
        color = "--red"
    return text, color, latest


def _count_test_files() -> int:
    if not TESTS_DIR.exists():
        return 0
    return sum(1 for p in TESTS_DIR.glob("test_*.py"))


def _count_main_py_lines() -> int:
    if not MAIN_PY.exists():
        return 0
    return sum(1 for _ in MAIN_PY.read_text(encoding="utf-8").splitlines())


def _replace(html: str, pattern: str, repl: str, *, count: int = 1) -> tuple[str, int]:
    """正则替换并返回 (new_html, replaced_count)。"""
    new_html, n = re.subn(pattern, repl, html, count=count)
    if n == 0:
        print(f"[WARN] 替换未命中: {pattern[:60]}…", file=sys.stderr)
    return new_html, n


def _inject_semantic_classes(html: str) -> str:
    """为移动端覆盖注入稳定语义类，保持幂等。"""
    replacements = [
        (
            '<div class="cta-group cta-group" style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
            '<div class="cta-group" style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
        ),
        (
            '<div class="cta-group" style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
            '<div class="cta-group" style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
        ),
        (
            '<div style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
            '<div class="cta-group" style="display:flex;gap:14px;max-width:860px;margin:24px auto 0;flex-wrap:wrap;justify-content:center">',
        ),
        (
            '<div class="grid-5 persona-grid persona-grid">\n    <div class="persona"',
            '<div class="grid-5 persona-grid">\n    <div class="persona"',
        ),
        (
            '<div class="grid-5">\n    <div class="persona"',
            '<div class="grid-5 persona-grid">\n    <div class="persona"',
        ),
        (
            '<div class="grid-5 metric-grid metric-grid">\n    <div class="card metric">',
            '<div class="grid-5 metric-grid">\n    <div class="card metric">',
        ),
        (
            '<div class="grid-5">\n    <div class="card metric">',
            '<div class="grid-5 metric-grid">\n    <div class="card metric">',
        ),
        (
            '<div class="conclusion-grid conclusion-grid" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:24px">',
            '<div class="conclusion-grid" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:24px">',
        ),
        (
            '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:24px">',
            '<div class="conclusion-grid" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:24px">',
        ),
    ]
    for old, new in replacements:
        html = html.replace(old, new, 1)
    return html


def _inject_mobile_css(html: str) -> str:
    """注入移动端样式，重复执行时用新块覆盖旧块。"""
    html = re.sub(
        rf'<style id="{MOBILE_STYLE_ID}">.*?</style>',
        "",
        html,
        count=1,
        flags=re.DOTALL,
    )
    if "</head>" in html:
        return html.replace("</head>", MOBILE_CSS + "\n</head>", 1)
    return MOBILE_CSS + "\n" + html


def main() -> int:
    if not TEMPLATE.exists():
        print(f"[ERROR] 模板不存在: {TEMPLATE}")
        return 1

    html = TEMPLATE.read_text(encoding="utf-8")
    html = _inject_semantic_classes(html)
    html = _inject_mobile_css(html)
    today = date.today().isoformat()

    # 1) 口径说明里的"生成 2026-06-19" → 今天
    html, _ = _replace(
        html,
        r"生成 \d{4}-\d{2}-\d{2} · 非统计评估",
        f"生成 {today} · 非统计评估",
    )

    # 2) 数据新鲜度
    fresh_text, fresh_color, fresh_sub = _data_freshness()
    html, _ = _replace(
        html,
        r'(<div class="card metric"><div class="big mono" style="color:var\()[^)]+(\)">)[^<]+(</div><div class="label">数据新鲜度<br><span style="font-size:\.85em">最新 state_date: )[^<]+(</span></div></div>)',
        rf"\g<1>{fresh_color}\g<2>{fresh_text}\g<3>{fresh_sub}\g<4>",
    )

    # 3) hermes_cron 状态
    cron_ok, cron_detail = _launchd_status()
    cron_color = "--green" if cron_ok else "--red"
    cron_icon = "✅" if cron_ok else "❌"
    cron_sub = "hermes_cron 正常运行" if cron_ok else f"hermes_cron 异常（{cron_detail}）"
    html, _ = _replace(
        html,
        r'(<div class="card metric"><div class="big mono" style="color:var\()[^)]+(\)">)[^<]+(</div><div class="label">定时任务状态<br><span style="font-size:\.85em">)[^<]+(</span></div></div>)',
        rf"\g<1>{cron_color}\g<2>{cron_icon}\g<3>{cron_sub}\g<4>",
    )

    # 4) 测试文件数（仅 48 是硬编码，使用前后缀精确定位）
    test_count = _count_test_files()
    html, _ = _replace(
        html,
        r'(<div class="card metric"><div class="big mono" style="color:var\()[^)]+(\)">)\d+(</div><div class="label">测试文件数)',
        rf"\g<1>{'--green' if test_count >= 30 else '--yellow'}\g<2>{test_count}\g<3>",
    )

    # 5) web/main.py 行数
    main_lines = _count_main_py_lines()
    main_color = "--red" if main_lines > 4500 else ("--yellow" if main_lines > 2000 else "--green")
    html, _ = _replace(
        html,
        r'(<div class="card metric"><div class="big mono" style="color:var\()[^)]+(\)">)\d+(</div><div class="label">web/main\.py 行数)',
        rf"\g<1>{main_color}\g<2>{main_lines}\g<3>",
    )

    TEMPLATE.write_text(html, encoding="utf-8")
    print(f"[OK] {TEMPLATE} 重建完成 — generated_at={today}")
    print(f"     数据新鲜度: {fresh_text} ({fresh_sub})")
    print(f"     hermes_cron: {'✅' if cron_ok else '❌'} ({cron_detail})")
    print(f"     测试文件数: {test_count}")
    print(f"     web/main.py: {main_lines} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
