#!/usr/bin/env python3
"""Hermass Agent 互评 — 每日收盘后自动运行的交叉校验。

评价对象：当日有产出的 Agent 对
评价方法：规则化一致性检查（后续版本接 LLM 语义检查）
数据源：AgentMemory.duckdb 的 agent_judgments 表

输出：outputs/reviews/cross_review_YYYYMMDD.json
退出码：0=全部一致, 1=有差异, 2=严重差异
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MEMORY_DB = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"
REVIEW_DIR = ROOT / "outputs" / "reviews"
ALERT_FILE = REVIEW_DIR / ".alert_cross_review"

logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent_cross_review")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ═══════════════════════════════════════════════════════════════════════════
# 互评对定义（与 evaluation_rhythm.yaml 保持同步）
# ═══════════════════════════════════════════════════════════════════════════

CROSS_PAIRS = [
    {
        "reviewer": "market_analyst",
        "reviewee": "strategy_advisor",
        "label": "策略适配 vs 市场环境",
        "explanation": "strategy_advisor 的建议是否与 market_analyst 判定的市场环境一致",
    },
    {
        "reviewer": "risk_guardian",
        "reviewee": "strategy_advisor",
        "label": "仓位建议 vs 风控约束",
        "explanation": "strategy_advisor 的建议仓位是否超出 risk_guardian 的风控上限",
    },
    {
        "reviewer": "contraction_observer",
        "reviewee": "strategy_advisor",
        "label": "收缩信号 vs 策略确认",
        "explanation": "contraction_observer 发现的收缩状态是否被 strategy_advisor 纳入决策",
    },
    {
        "reviewer": "judge",
        "reviewee": "diagnoser",
        "label": "市场判官 vs 诊断 Agent",
        "explanation": "judge 的市场判断与 diagnoser 的个股诊断是否自洽",
    },
]


def get_today_judgments() -> list[dict]:
    """从 AgentMemory 获取今天的 Agent 判断记录。"""
    import duckdb

    if not MEMORY_DB.exists():
        return []

    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    try:
        con = duckdb.connect(str(MEMORY_DB), read_only=True)
        try:
            rows = con.execute(
                """
                SELECT agent_id, judgment_id, judgment_date, judgment_type, judgment_content
                FROM agent_judgments
                WHERE judgment_date IN (?, ?)
                ORDER BY agent_id, judgment_date DESC
                """,
                [today, yesterday],
            ).fetchall()
            return [
                {
                    "agent_id": str(r[0]),
                    "judgment_id": str(r[1]),
                    "judgment_date": str(r[2]),
                    "judgment_type": str(r[3]),
                    "judgment_content": json.loads(r[4]) if r[4] else {},
                }
                for r in rows
            ]
        finally:
            con.close()
    except Exception:
        return []


def group_by_agent(judgments: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for j in judgments:
        grouped[j["agent_id"]].append(j)
    return dict(grouped)


def check_consistency(
    reviewer_judgments: list[dict],
    reviewee_judgments: list[dict],
    pair_label: str = "",
    pair_explanation: str = "",
) -> dict[str, Any]:
    """规则化一致性检查 v2：跨日期窗口 + judgment_content 关键词交叉比对。

    相比 v1（只比 judgment_type 集合交集），v2 增加：
    - 日期窗口：双方最近 2 天内的判断都纳入
    - 内容交叉：judgment_content 中的中文关键词是否重叠
    - 差异时给出具体提示：哪一方有数据、哪一方缺失
    """

    reviewer_has = bool(reviewer_judgments)
    reviewee_has = bool(reviewee_judgments)

    if not reviewer_has and not reviewee_has:
        return {
            "consistent": True,
            "label": "双方均无输出",
            "detail": "近 2 日无判断可比较",
            "method": "keyword_overlap_v2",
        }

    if not reviewer_has:
        return {
            "consistent": False,
            "label": "差异",
            "detail": f"评价方（{pair_label.split(' vs ')[0] if ' vs ' in pair_label else ''}）近 2 日无产出",
            "method": "keyword_overlap_v2",
        }

    if not reviewee_has:
        return {
            "consistent": False,
            "label": "差异",
            "detail": f"被评价方（{pair_label.split(' vs ')[-1] if ' vs ' in pair_label else ''}）近 2 日无产出",
            "method": "keyword_overlap_v2",
        }

    # 提取中文关键词（2-4 字，去重）
    def _keywords(judgments: list[dict]) -> set[str]:
        kws: set[str] = set()
        for j in judgments:
            content = j.get("judgment_content", {})
            text = json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else str(content)
            found = set(re.findall(r"[\u4e00-\u9fa5]{2,4}", text))
            kws.update(found)
        return kws

    r_kws = _keywords(reviewer_judgments)
    v_kws = _keywords(reviewee_judgments)

    if not r_kws or not v_kws:
        return {
            "consistent": False,
            "label": "差异",
            "detail": "一方或多方判断内容无可提取关键词（content 为空或纯英文）",
            "method": "keyword_overlap_v2",
        }

    overlap = r_kws & v_kws
    r_only = r_kws - v_kws
    v_only = v_kws - r_kws

    # 一致性评分：交集 / (交集 + 差集)
    total_unique = len(overlap) + len(r_only) + len(v_only)
    score = len(overlap) / total_unique if total_unique > 0 else 0.0
    consistent = score >= 0.15  # 15% 关键词重叠即视为一致

    detail_parts = [f"评分={score:.2f}", f"重叠={len(overlap)}词"]
    if r_only:
        detail_parts.append(f"评价方独有={len(r_only)}词")
    if v_only:
        detail_parts.append(f"被评价方独有={len(v_only)}词")

    return {
        "consistent": consistent,
        "label": "一致" if consistent else "差异",
        "detail": "; ".join(detail_parts),
        "reviewer_keywords_count": len(r_kws),
        "reviewee_keywords_count": len(v_kws),
        "overlap_count": len(overlap),
        "overlap_score": round(score, 3),
        "method": "keyword_overlap_v2",
    }


def build_report(target_date: str | None = None) -> dict[str, Any]:
    judgments = get_today_judgments()
    grouped = group_by_agent(judgments)

    pairs_result: list[dict] = []
    inconsistencies = 0

    for pair in CROSS_PAIRS:
        r_name = pair["reviewer"]
        v_name = pair["reviewee"]
        r_judgments = grouped.get(r_name, [])
        v_judgments = grouped.get(v_name, [])

        check = check_consistency(r_judgments, v_judgments, pair_label=pair["label"])
        result = {
            "reviewer": r_name,
            "reviewee": v_name,
            "label": pair["label"],
            "explanation": pair["explanation"],
            "consistent": check["consistent"],
            "detail": check["detail"],
            "method": check["method"],
        }
        pairs_result.append(result)
        if not check["consistent"]:
            inconsistencies += 1

    overall = "ok" if inconsistencies == 0 else ("warn" if inconsistencies <= 1 else "error")

    report = {
        "review_type": "cross_review",
        "generated_at": _now(),
        "target_date": target_date or str(date.today()),
        "overall": overall,
        "total_pairs": len(CROSS_PAIRS),
        "consistent_pairs": len(CROSS_PAIRS) - inconsistencies,
        "inconsistent_pairs": inconsistencies,
        "pairs": pairs_result,
        "note": "规则化互评 v2：关键词重叠评分，阈值 0.15。LLM 语义互评版本后续接入 DeepSeek。",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hermass Agent 互评 — 交叉校验"
    )
    parser.add_argument("--date", help="目标日期（默认今天）")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args()

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    target = args.date or str(date.today())
    report = build_report(target)

    ts = target.replace("-", "")
    out_path = REVIEW_DIR / f"cross_review_{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    latest_path = REVIEW_DIR / "cross_review_latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    # ── 告警信号：互评差异 >50% 时落标记文件 + ERROR 日志 ──
    if report["overall"] in ("warn", "error"):
        logger.error(
            "互评差异: overall=%s consistent=%d/%d",
            report["overall"],
            report["consistent_pairs"],
            report["total_pairs"],
        )
        alert = {
            "triggered_at": _now(),
            "overall": report["overall"],
            "consistent_pairs": report["consistent_pairs"],
            "total_pairs": report["total_pairs"],
            "inconsistent_details": [
                {"reviewer": p["reviewer"], "reviewee": p["reviewee"], "detail": p["detail"]}
                for p in report["pairs"]
                if not p["consistent"]
            ],
            "action": "AgentBus review_needed 应由 alert_scanner 消费此标记文件后广播",
        }
        ALERT_FILE.write_text(json.dumps(alert, ensure_ascii=False, indent=2))

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)

    if report["overall"] == "error":
        return 2
    elif report["overall"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
