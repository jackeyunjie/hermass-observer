#!/usr/bin/env python3
"""Hermass 每日复盘 → 飞书群消息 + 飞书多维表格

最小闭环：
1. 读取当日 daily_snapshot、decision_observation、自评/互评/人机对齐复盘
2. 生成一条 Markdown 群消息，推送到 lark_app.yaml 配置的 chat_id
3. 将市场级 + Top N 个股判断写入飞书 Base（配置在 lark_digest.yaml）

Usage:
    .venv/bin/python scripts/send_daily_hermass_digest_to_lark.py --date 2026-06-18 --dry-run
    .venv/bin/python scripts/send_daily_hermass_digest_to_lark.py --date 2026-06-18
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
LARK_APP_CONFIG = ROOT / "config" / "platform" / "lark_app.yaml"
LARK_DIGEST_CONFIG = ROOT / "config" / "platform" / "lark_digest.yaml"
DECISION_DB = ROOT / "outputs" / "decision_observation" / "decision_observation.duckdb"
SNAPSHOT_DIR = ROOT / "outputs" / "daily_snapshot"
REVIEW_DIR = ROOT / "outputs" / "reviews"
DIGEST_MARKER_DIR = ROOT / "outputs" / "lark_digest"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def _resolve_date_str(args_date: str | None) -> str:
    if args_date:
        return args_date
    return date.today().isoformat()


def _load_snapshot(target_date: str) -> dict[str, Any] | None:
    ymd = target_date.replace("-", "")
    candidates = [
        SNAPSHOT_DIR / f"daily_snapshot_{ymd}.json",
        ROOT / "outputs" / "daily_snapshot.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def _load_decision_rows(target_date: str) -> list[dict[str, Any]]:
    if not DECISION_DB.exists():
        return []
    con = duckdb.connect(str(DECISION_DB), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT observation_id, hypothesis_id, stock_code, state_date,
                   agent_debate_json, router_json, final_label, final_score,
                   risk_veto, future_r5, future_r20, outcome_label, review_status
            FROM decision_observation
            WHERE state_date = CAST(? AS DATE)
            ORDER BY CASE WHEN stock_code = '__MARKET__' THEN 0 ELSE 1 END,
                   final_score DESC
            """,
            [target_date],
        ).fetchall()
    finally:
        con.close()

    result: list[dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "observation_id": r[0],
                "hypothesis_id": r[1],
                "stock_code": r[2],
                "state_date": str(r[3]),
                "agent_debate_json": _safe_json(r[4]),
                "router_json": _safe_json(r[5]),
                "final_label": r[6],
                "final_score": r[7],
                "risk_veto": bool(r[8]) if r[8] is not None else False,
                "future_r5": r[9],
                "future_r20": r[10],
                "outcome_label": r[11],
                "review_status": r[12],
            }
        )
    return result


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _load_self_review() -> dict[str, Any] | None:
    path = REVIEW_DIR / "self_review_latest.json"
    if not path.exists():
        # fallback: newest self_review_*.json
        paths = sorted(REVIEW_DIR.glob("self_review_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if paths:
            path = paths[0]
        else:
            return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_cross_review(target_date: str) -> dict[str, Any] | None:
    path = REVIEW_DIR / f"cross_review_{target_date.replace('-', '')}.json"
    if not path.exists():
        paths = sorted(REVIEW_DIR.glob("cross_review_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if paths:
            path = paths[0]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_human_review(target_date: str) -> str:
    path = REVIEW_DIR / f"human_review_{target_date.replace('-', '')}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _market_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in rows:
        if r["stock_code"] == "__MARKET__":
            return r
    return None


def _per_stock_rows(rows: list[dict[str, Any]], max_n: int = 50) -> list[dict[str, Any]]:
    stocks = [r for r in rows if r["stock_code"] != "__MARKET__"]
    # prefer higher score, observe > watch > reject
    label_order = {"observe": 0, "watch": 1, "reject": 2}
    stocks.sort(key=lambda r: (label_order.get(r["final_label"], 9), -(r["final_score"] or 0)))
    return stocks[:max_n]


def _agent_counts_from_debate(debate: dict[str, Any]) -> tuple[int, int, int]:
    agents = debate.get("agents") or debate.get("opinions") or {}
    if isinstance(agents, dict):
        support = sum(1 for a in agents.values() if isinstance(a, dict) and a.get("stance") == "support")
        oppose = sum(1 for a in agents.values() if isinstance(a, dict) and a.get("stance") == "oppose")
        neutral = sum(1 for a in agents.values() if isinstance(a, dict) and a.get("stance") not in ("support", "oppose"))
        return support, oppose, neutral
    return 0, 0, 0


def _risk_tags_from_row(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    debate = row.get("agent_debate_json") or {}
    route = row.get("router_json") or {}
    risk_agent = (debate.get("agents") or debate.get("opinions") or {}).get("RiskAgent", {})
    if isinstance(risk_agent, dict):
        tags.extend(risk_agent.get("risk_tags", []) or [])
    flags = route.get("risk_flags", [])
    if isinstance(flags, list):
        tags.extend([str(f) for f in flags if f])
    elif isinstance(flags, dict):
        tags.extend([str(k) for k, v in flags.items() if v])
    return list(dict.fromkeys(tags)) if tags else []


def _risk_veto_reasons(rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for r in rows:
        if not r["risk_veto"]:
            continue
        debate = r.get("agent_debate_json") or {}
        risk_agent = (debate.get("agents") or debate.get("opinions") or {}).get("RiskAgent", {})
        reason = risk_agent.get("veto_reason") if isinstance(risk_agent, dict) else ""
        if reason:
            reasons.append(f"{r['stock_code']}: {reason}")
    return reasons


def _format_markdown(
    target_date: str,
    snapshot: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    self_review: dict[str, Any] | None,
    cross_review: dict[str, Any] | None,
    human_md: str,
) -> str:
    market = snapshot.get("market", {}) if snapshot else {}
    snap_date = snapshot.get("date", target_date) if snapshot else target_date
    built = snapshot.get("built", "") if snapshot else ""

    market_row = _market_row(rows)
    per_stock = _per_stock_rows(rows)

    # label distribution
    label_counts: dict[str, int] = {}
    for r in per_stock:
        label_counts[r["final_label"] or "unknown"] = label_counts.get(r["final_label"] or "unknown", 0) + 1

    # router market verdict
    router = market_row.get("router_json") or {} if market_row else {}
    verdict = router.get("verdict", {}) if isinstance(router, dict) else {}
    final_verdict = verdict.get("final_verdict") or verdict.get("decision") or (market_row["final_label"] if market_row else "-")
    adjusted_score = verdict.get("adjusted_score") or (market_row["final_score"] if market_row else None)
    conflicts = router.get("conflicts_count", 0)
    resonances = router.get("resonances_count", 0)
    top_risks = verdict.get("top_risks", []) if isinstance(verdict, dict) else []
    decision = verdict.get("decision", "")

    # reviews
    self_overall = self_review.get("overall", "unknown") if self_review else "unknown"
    self_issues = self_review.get("issues", []) if self_review else []
    cross_overall = cross_review.get("overall", "unknown") if cross_review else "unknown"
    cross_inconsistent = cross_review.get("inconsistent_pairs", 0) if cross_review else 0

    lines = [
        f"**Hermass 每日复盘 — {target_date}**",
        "",
        "📊 数据同步状态",
        f"- 数据日期：{snap_date}",
        f"- 总标的：{market.get('total', '-')} 只 | EF≥2：{market.get('ef2_count', '-')} 只（{market.get('ef2_pct', '-')}%）",
        f"- 平均 D1 Score：{market.get('avg_d1_score', '-')}",
        f"- 快照生成：{built}",
        "",
        "⚠️ 今日异常",
        f"- 系统自评：{self_overall}" + (f"（{len(self_issues)} 项问题）" if self_issues else ""),
        f"- Agent 互评：{cross_overall}" + (f"，{cross_inconsistent} 组不一致" if cross_inconsistent else ""),
        "- 人机对齐：" + ("已生成" if human_md else "未生成"),
    ]
    if self_issues:
        for issue in self_issues[:3]:
            lines.append(f"  - {issue}")

    lines.extend([
        "",
        "🤖 Agent 辩论结论",
        f"- 市场级：{final_verdict}" + (f"（评分 {adjusted_score:.3f}）" if adjusted_score is not None else ""),
        f"- 个股观察 {label_counts.get('observe', 0)} / 关注 {label_counts.get('watch', 0)} / 拒绝 {label_counts.get('reject', 0)}（Top {len(per_stock)}）",
    ])

    top_observe = [r for r in per_stock if r["final_label"] == "observe"][:5]
    if top_observe:
        lines.append("- Top 观察标的：" + "，".join(f"{r['stock_code']}({r['final_score']:.2f})" for r in top_observe))

    lines.extend([
        "",
        "🧭 Router Verdict",
        f"- 最终结论：{final_verdict}",
        f"- 冲突：{conflicts} 组 | 共振：{resonances} 组",
    ])
    if decision:
        lines.append(f"- 决策建议：{decision}")

    lines.extend([
        "",
        "🛡️ Risk Agent 反驳点",
    ])
    if top_risks:
        for risk in top_risks[:5]:
            lines.append(f"- {risk}")
    else:
        lines.append("- 当前未触发显著风险标记")

    veto_reasons = _risk_veto_reasons(per_stock)
    if veto_reasons:
        lines.append(f"- 个股风险否决 {len(veto_reasons)} 条")
        for reason in veto_reasons[:3]:
            lines.append(f"  - {reason}")

    lines.extend([
        "",
        "---",
        "*Research-Only，不构成投资建议*",
    ])
    return "\n".join(lines)


def _lark_cli(args: list[str], identity: str | None = None, timeout: int = 60) -> dict[str, Any]:
    cmd = ["lark-cli"]
    cmd.extend(args)
    if identity:
        cmd.extend(["--as", identity])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = {}
    if "ok" not in data:
        data["ok"] = result.returncode == 0
    data.setdefault("returncode", result.returncode)
    if result.returncode != 0:
        data.setdefault("stderr", result.stderr)
    return data


def _send_group_message(chat_id: str, markdown: str, idempotency_key: str, dry_run: bool) -> dict[str, Any]:
    args = [
        "im", "+messages-send",
        "--as", "bot",
        "--chat-id", chat_id,
        "--markdown", markdown,
        "--idempotency-key", idempotency_key,
    ]
    if dry_run:
        args.append("--dry-run")
    return _lark_cli(args)


def _base_record_fields(row: dict[str, Any], record_type: str, verdict_text: str, summary: str, detail_url: str) -> dict[str, Any]:
    support, oppose, _ = _agent_counts_from_debate(row.get("agent_debate_json") or {})
    risk_tags = _risk_tags_from_row(row)
    fields: dict[str, Any] = {
        "日期": f"{row['state_date']} 00:00:00",
        "标的": row["stock_code"],
        "类型": record_type,
        "Hypothesis": row["hypothesis_id"] or "",
        "Router结论": row["final_label"] or "watch",
        "Router评分": row["final_score"] if row["final_score"] is not None else 0.0,
        "风险否决": bool(row["risk_veto"]),
        "风险标签": risk_tags,
        "Agent支持数": support,
        "Agent反对数": oppose,
        "future_r5": row["future_r5"] if row["future_r5"] is not None else None,
        "future_r20": row["future_r20"] if row["future_r20"] is not None else None,
        "后验结果": row["outcome_label"] or "",
        "复核状态": row["review_status"] or "pending",
        "详情链接": detail_url,
        "备注": summary,
    }
    # remove None values to avoid type mismatches
    return {k: v for k, v in fields.items() if v is not None}


def _write_base_records(
    base_token: str,
    table_id: str,
    target_date: str,
    rows: list[dict[str, Any]],
    dry_run: bool,
    force: bool,
    max_stocks: int = 50,
) -> dict[str, Any]:
    DIGEST_MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = DIGEST_MARKER_DIR / f"digest_{target_date.replace('-', '')}.json"
    if marker.exists() and not force and not dry_run:
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
            if previous.get("table_id") == table_id and previous.get("base_token") == base_token:
                return {"ok": True, "skipped": True, "reason": "already synced today", "previous": previous}
        except Exception:
            pass

    market_row = _market_row(rows)
    per_stock = _per_stock_rows(rows, max_n=max_stocks)
    detail_url = f"http://console.supertrader.world/debate-dashboard?date={target_date}"

    written: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def upsert(fields: dict[str, Any]) -> None:
        payload = json.dumps(fields, ensure_ascii=False)
        args = ["base", "+record-upsert", "--base-token", base_token, "--table-id", table_id, "--json", payload]
        if dry_run:
            args.append("--dry-run")
        resp = _lark_cli(args, identity=None)
        if resp.get("ok"):
            written.append(resp.get("record", {}))
        else:
            errors.append({"fields": fields, "response": resp})

    if market_row:
        router = market_row.get("router_json") or {}
        verdict = router.get("verdict", {}) if isinstance(router, dict) else {}
        summary = verdict.get("summary", "") if isinstance(verdict, dict) else ""
        upsert(_base_record_fields(market_row, "市场", verdict.get("final_verdict", ""), summary, detail_url))

    for r in per_stock:
        router = r.get("router_json") or {}
        reason = router.get("router_reason", "") if isinstance(router, dict) else ""
        upsert(_base_record_fields(r, "个股", r["final_label"] or "", reason, detail_url))

    result: dict[str, Any] = {
        "ok": len(errors) == 0,
        "written_count": len(written),
        "error_count": len(errors),
        "errors": errors,
    }
    if result["ok"] and not dry_run:
        marker.write_text(
            json.dumps(
                {
                    "date": target_date,
                    "table_id": table_id,
                    "base_token": base_token,
                    "record_count": len(written),
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Hermass daily digest to Lark group and Base")
    parser.add_argument("--date", help="YYYY-MM-DD, default today")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not send or write")
    parser.add_argument("--force", action="store_true", help="Ignore daily sync marker and re-send/re-write")
    args = parser.parse_args()

    target_date = _resolve_date_str(args.date)

    app_cfg = _load_yaml(LARK_APP_CONFIG)
    digest_cfg = _load_yaml(LARK_DIGEST_CONFIG)

    chat_id = (app_cfg.get("push") or {}).get("chat_id", "")
    base_token = (digest_cfg.get("digest") or {}).get("base_token", "")
    table_id = (digest_cfg.get("digest") or {}).get("table_id", "")
    base_enabled = (digest_cfg.get("digest") or {}).get("enabled", False)
    max_stocks = (digest_cfg.get("digest") or {}).get("max_stocks_per_day", 50)

    if not chat_id:
        print("ERROR: chat_id not configured in config/platform/lark_app.yaml push.chat_id", file=sys.stderr)
        return 1

    snapshot = _load_snapshot(target_date)
    rows = _load_decision_rows(target_date)
    self_review = _load_self_review()
    cross_review = _load_cross_review(target_date)
    human_md = _load_human_review(target_date)

    if not rows:
        print(f"WARNING: no decision_observation rows for {target_date}", file=sys.stderr)

    markdown = _format_markdown(target_date, snapshot, rows, self_review, cross_review, human_md)

    print("=== Markdown message ===")
    print(markdown)
    print("=== End message ===")

    # send group message
    idempotency_key = f"hermass-digest-{target_date}"
    msg_result = _send_group_message(chat_id, markdown, idempotency_key, dry_run=args.dry_run)
    print(json.dumps({"group_message": msg_result}, ensure_ascii=False, indent=2))

    if base_enabled and base_token and table_id:
        base_result = _write_base_records(
            base_token=base_token,
            table_id=table_id,
            target_date=target_date,
            rows=rows,
            dry_run=args.dry_run,
            force=args.force,
            max_stocks=max_stocks,
        )
        print(json.dumps({"base_sync": base_result}, ensure_ascii=False, indent=2))
        if not base_result.get("ok"):
            print("ERROR: Base sync failed", file=sys.stderr)
            return 1
    else:
        print("Base sync skipped (enable and configure base_token/table_id in config/platform/lark_digest.yaml)")

    if not msg_result.get("ok"):
        print("ERROR: Group message failed", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
