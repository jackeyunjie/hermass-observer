#!/usr/bin/env python3
"""Serenity 产业链瓶颈分析定期运行入口。

用法：
    .venv/bin/python scripts/run_serenity_chain_analysis.py --chain ai_compute --date 2026-06-05
    .venv/bin/python scripts/run_serenity_chain_analysis.py --all  # 跑全部 P0 产业链

建议加入 config/hermes_cron.json 作为日频/周频任务。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hermass_platform.agents.serenity_chain_analyzer import analyze_serenity_chain, P0_CHAINS


def run_single(chain_id: str, state_date: str | None) -> dict:
    print(f"[Serenity] 开始分析 {chain_id} @ {state_date or date.today()}", file=sys.stderr)
    result = analyze_serenity_chain(chain_id, state_date)
    if result.get("ok"):
        print(f"[Serenity] 完成 {chain_id}: top_node={result['node_ranking'][0]['node_name'] if result['node_ranking'] else '-'} score={result['node_ranking'][0]['score'] if result['node_ranking'] else 0}", file=sys.stderr)
        if result.get("report_path"):
            print(f"[Serenity] 报告: {result['report_path']}", file=sys.stderr)
    else:
        print(f"[Serenity] 失败 {chain_id}: {result.get('error')}", file=sys.stderr)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Serenity 产业链瓶颈分析运行器")
    parser.add_argument("--chain", type=str, help="产业链 ID（如 ai_compute）")
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--all", action="store_true", help="跑全部 P0 产业链")
    parser.add_argument("--output", type=str, help="汇总 JSON 输出路径")
    args = parser.parse_args()

    state_date = args.date or str(date.today())

    if args.all:
        chains = sorted(P0_CHAINS)
    elif args.chain:
        chains = [args.chain]
    else:
        parser.error("请指定 --chain 或 --all")

    summary = {}
    for chain_id in chains:
        result = run_single(chain_id, state_date)
        summary[chain_id] = {
            "ok": result.get("ok"),
            "top_node": result["node_ranking"][0]["node_name"] if result.get("node_ranking") else None,
            "top_score": result["node_ranking"][0]["score"] if result.get("node_ranking") else None,
            "scarce_layers": result.get("scarce_layers", []),
            "report_path": result.get("report_path"),
            "judgment_id": result.get("judgment_id"),
        }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"汇总已写入: {args.output}", file=sys.stderr)
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    failed = [c for c, r in summary.items() if not r["ok"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
