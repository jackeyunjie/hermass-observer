#!/usr/bin/env python3
"""Build daily human alignment review from Agent review outputs.

The file is intentionally Markdown: it is meant to be read and amended by the
human operator, then synced into Obsidian.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "outputs" / "reviews"
AGENT_BUS_OUTBOX = ROOT / "outputs" / "agent_bus" / "outbox"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_review_files(target_date: str) -> dict[str, Any]:
    return {
        "self_review": load_json(REVIEW_DIR / "self_review_latest.json"),
        "cross_review": load_json(REVIEW_DIR / f"cross_review_{ymd(target_date)}.json")
        or load_json(REVIEW_DIR / "cross_review_latest.json"),
        "alert_self": load_json(REVIEW_DIR / ".alert_self_review"),
        "alert_cross": load_json(REVIEW_DIR / ".alert_cross_review"),
    }


def list_review_needed_messages() -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if not AGENT_BUS_OUTBOX.exists():
        return messages
    for path in sorted(AGENT_BUS_OUTBOX.glob("*.json")):
        payload = load_json(path)
        if isinstance(payload, dict) and payload.get("topic") == "review_needed":
            messages.append({
                "path": str(path),
                "message": payload,
            })
    return messages


def value(payload: Any, path: str, default: Any = "-") -> Any:
    current = payload
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def build_markdown(target_date: str) -> str:
    reviews = load_review_files(target_date)
    bus_messages = list_review_needed_messages()
    self_review = reviews["self_review"] or {}
    cross_review = reviews["cross_review"] or {}
    alert_self = reviews["alert_self"]
    alert_cross = reviews["alert_cross"]

    lines = [
        f"# Hermass 人机对齐复盘 — {target_date}",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "标签：#复盘 #Agent #人机对齐",
        "",
        "---",
        "",
        "## 一、系统自评",
        "",
        f"- 状态：{self_review.get('overall', 'missing')}",
        f"- 生成时间：{self_review.get('generated_at', '-')}",
        f"- 问题数：{len(self_review.get('issues') or [])}",
    ]

    issues = self_review.get("issues") or []
    if issues:
        lines.append("")
        for item in issues:
            lines.append(f"- 待确认：{item}")
    else:
        lines.append("- 待确认：无")

    lines.extend([
        "",
        "## 二、Agent 互评",
        "",
        f"- 状态：{cross_review.get('overall', 'missing')}",
        f"- 目标日期：{cross_review.get('target_date', '-')}",
        f"- 一致对数：{cross_review.get('consistent_pairs', '-')}/{cross_review.get('total_pairs', '-')}",
        f"- 不一致对数：{cross_review.get('inconsistent_pairs', '-')}",
        "",
    ])

    pairs = cross_review.get("pairs") or []
    if pairs:
        lines.append("| 互评项 | 结果 | 详情 |")
        lines.append("|--------|------|------|")
        for pair in pairs:
            label = pair.get("label", "-")
            result = "一致" if pair.get("consistent") else "需看"
            detail = str(pair.get("detail", "-")).replace("\n", " ")
            lines.append(f"| {label} | {result} | {detail} |")
    else:
        lines.append("未找到当日 Agent 互评产物。")

    lines.extend([
        "",
        "## 三、告警与 AgentBus",
        "",
        f"- `.alert_self_review`：{'存在' if alert_self else '无'}",
        f"- `.alert_cross_review`：{'存在' if alert_cross else '无'}",
        f"- AgentBus `review_needed` 未消费消息：{len(bus_messages)}",
    ])

    if bus_messages:
        lines.append("")
        for item in bus_messages[:20]:
            msg = item["message"]
            payload = msg.get("payload") or {}
            lines.append(f"- {payload.get('subject', '-')}: {item['path']}")

    lines.extend([
        "",
        "## 四、人类确认区",
        "",
        "- 今日系统异常是否合理：待确认",
        "- Agent 分歧是否需要调整权重：待确认",
        "- 是否有需要暂停的自动流程：待确认",
        "- 是否需要写入新的 AGENTS.md 规则：待确认",
        "- 是否需要同步给 KIMI / DeepSeek：待确认",
        "",
        "## 五、结论",
        "",
        "本文件是人机对齐复盘的日级产物。只有本文件生成并被人工确认后，才能说当天人类对齐复盘已落地。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily human alignment review.")
    parser.add_argument("--date", default=str(date.today()), help="YYYY-MM-DD")
    args = parser.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = REVIEW_DIR / f"human_review_{ymd(args.date)}.md"
    path.write_text(build_markdown(args.date), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
