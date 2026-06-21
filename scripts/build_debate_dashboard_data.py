#!/usr/bin/env python3
"""收集本地指标并生成 debate_dashboard_data.json 以供上传到服务器。
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEBATE_DIR = ROOT / "outputs" / "debate"
DATA_FILE = DEBATE_DIR / "debate_dashboard_data.json"
SELF_REVIEW = ROOT / "outputs" / "reviews" / "self_review_latest.json"
TESTS_DIR = ROOT / "tests" / "unit"
MAIN_PY = ROOT / "web" / "main.py"
LAUNCHD_LABEL = "com.hermass.hermes-cron"

def _read_self_review() -> dict:
    if not SELF_REVIEW.exists():
        return {}
    try:
        return json.loads(SELF_REVIEW.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] self_review_latest.json 解析失败: {exc}", file=sys.stderr)
        return {}

def _launchd_status() -> tuple[bool, str]:
    uid = subprocess.run(
        ["id", "-u"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).stdout.strip() or "0"
    try:
        out = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{LAUNCHD_LABEL}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except Exception as exc:
        return False, f"launchctl 不可用: {exc}"
    if "could not find service" in out.lower() or not out.strip():
        return False, "未注册"
    state_match = None
    pid_match = None
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("state = ") and state_match is None:
            state_match = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid = ") and pid_match is None:
            pid_match = stripped.split("=", 1)[1].strip()
    if state_match == "running" and pid_match and pid_match.isdigit():
        return True, f"PID {pid_match} 运行中"
    if state_match:
        return False, f"状态 {state_match}"
    return False, "状态未知"

def _data_freshness() -> tuple[str, str, str]:
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

def main() -> int:
    DEBATE_DIR.mkdir(parents=True, exist_ok=True)
    
    fresh_text, fresh_color, fresh_sub = _data_freshness()
    cron_ok, cron_detail = _launchd_status()
    cron_color = "--green" if cron_ok else "--red"
    cron_icon = "✅" if cron_ok else "❌"
    cron_sub = "hermes_cron 正常运行" if cron_ok else f"hermes_cron 异常（{cron_detail}）"

    test_count = _count_test_files()
    test_color = "--green" if test_count >= 30 else "--yellow"

    main_lines = _count_main_py_lines()
    main_color = "--red" if main_lines > 4500 else ("--yellow" if main_lines > 2000 else "--green")

    metrics = {
        "fresh_text": fresh_text,
        "fresh_color": fresh_color,
        "fresh_sub": fresh_sub,
        "cron_icon": cron_icon,
        "cron_color": cron_color,
        "cron_sub": cron_sub,
        "test_count": test_count,
        "test_color": test_color,
        "main_lines": main_lines,
        "main_color": main_color,
    }

    # 回测偏差标注（P2-1）
    sys.path.insert(0, str(ROOT))
    from scripts.build_backtest_gap_annotation import build_backtest_gap_annotation
    gap = build_backtest_gap_annotation()
    metrics["backtest_gap"] = gap

    # Agent 辩论数据（Phase 2 MOE）
    from scripts.agent_debate_runner import main as run_agent_debate
    debate = run_agent_debate()
    metrics["agent_debate"] = debate

    # Agent 动态权重路由与综合结论（Phase 2 MOE Router）
    from scripts.dynamic_weight_router import main as run_router
    router_result = run_router(debate)
    metrics["agent_router"] = router_result

    DATA_FILE.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {DATA_FILE} 生成完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
