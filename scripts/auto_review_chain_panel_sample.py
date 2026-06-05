#!/usr/bin/env python3
"""Auto pre-review a chain panel sample CSV.

This is a conservative helper for triage only. It fills review_status using
local node rules and profile context:
  - verified: direct name/product/business/sw_l3 evidence
  - rejected: clearly unrelated sw_l3 and no keyword evidence
  - needs_research: ambiguous or insufficient evidence
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "chain_node_rules.json"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def load_rules(path: Path = RULES_PATH) -> dict[tuple[str, str], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rules: dict[tuple[str, str], dict[str, Any]] = {}
    for chain in data.get("chains", []):
        for node in chain.get("nodes", []):
            item = dict(node)
            item["chain_id"] = chain.get("chain_id")
            item["chain_name"] = chain.get("chain_name")
            rules[(str(chain.get("chain_id")), str(node.get("node_id")))] = item
    return rules


def _contains_any(text: str, keywords: list[str]) -> bool:
    if not text or not keywords:
        return False
    return any(keyword and keyword in text for keyword in keywords)


def decide_row(row: dict[str, str], node_rule: dict[str, Any] | None) -> tuple[str, str]:
    if not node_rule:
        return "needs_research", "Auto: missing node rule"

    match_rules = node_rule.get("match_rules", {})
    stock_name = _clean(row.get("stock_name"))
    sw_l3 = _clean(row.get("sw_l3"))
    product_text = " ".join(
        [
            _clean(row.get("main_product_types")),
            _clean(row.get("main_product_names")),
        ]
    )
    business_text = _clean(row.get("main_business"))
    combined_text = " ".join([stock_name, sw_l3, product_text, business_text])

    if _contains_any(stock_name, match_rules.get("name_keyword", [])):
        return "verified", "Auto: name_keyword match"
    if _contains_any(product_text, match_rules.get("product_keyword", [])) or _contains_any(
        business_text, match_rules.get("business_keyword", [])
    ):
        return "verified", "Auto: product/business_keyword match"
    if sw_l3 and sw_l3 in set(match_rules.get("sw_l3_exact", [])):
        return "verified", "Auto: sw_l3_exact match"
    if _contains_any(sw_l3, match_rules.get("sw_l3_contains", [])):
        return "verified", "Auto: sw_l3_contains match"

    weak_hits = []
    for key in ["product_keyword", "business_keyword", "name_keyword"]:
        hits = [kw for kw in match_rules.get(key, []) if kw and kw in combined_text]
        weak_hits.extend(hits)
    if weak_hits:
        return "needs_research", "Auto: weak keyword hit requires human review"

    if sw_l3:
        return "rejected", "Auto: sw_l3 unrelated and no keyword match"
    return "needs_research", "Auto: missing sw_l3/profile context"


def auto_review_csv(input_csv: Path, output_csv: Path | None = None, reviewer: str = "ai_auto") -> dict[str, Any]:
    if not input_csv.exists():
        return {"ok": False, "error": f"Input CSV not found: {input_csv}"}
    node_rules = load_rules()
    rows: list[dict[str, str]]
    with input_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])

    reviewed_at = datetime.now(timezone.utc).isoformat()
    for required in ["review_status", "reviewed_node_id", "reviewer_note", "reviewer", "reviewed_at"]:
        if required not in fieldnames:
            fieldnames.append(required)

    for row in rows:
        if _clean(row.get("review_status")):
            continue
        chain_id = _clean(row.get("chain_id"))
        node_id = _clean(row.get("node_id"))
        status, note = decide_row(row, node_rules.get((chain_id, node_id)))
        row["review_status"] = status
        row["reviewed_node_id"] = row.get("reviewed_node_id") or node_id
        row["reviewer_note"] = note
        row["reviewer"] = reviewer
        row["reviewed_at"] = reviewed_at

    if output_csv is None:
        output_csv = input_csv.with_name(f"{input_csv.stem}_auto_reviewed.csv")
    with output_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    status_dist = Counter(row.get("review_status", "") for row in rows)
    return {
        "ok": True,
        "input_csv": str(input_csv),
        "output_csv": str(output_csv),
        "rows": len(rows),
        "status_dist": dict(status_dist),
        "reviewer": reviewer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto pre-review a chain panel sample CSV.")
    parser.add_argument("input_csv")
    parser.add_argument("--output")
    parser.add_argument("--reviewer", default="ai_auto")
    args = parser.parse_args()

    result = auto_review_csv(
        input_csv=Path(args.input_csv),
        output_csv=Path(args.output) if args.output else None,
        reviewer=args.reviewer,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
