#!/usr/bin/env python3
"""Calibrate per-stock scoring model against historical backfilled records.

Reads PER_STOCK_OBSERVATION records from decision_observation.duckdb,
reassigns rank-based labels using deterministic tie-breaking, and evaluates
performance across different percentile cutoffs and horizons (5d / 20d).
"""

import duckdb
import statistics
import sys
from collections import defaultdict

DB_PATH = "outputs/decision_observation/decision_observation.duckdb"


def _load_records():
    con = duckdb.connect(DB_PATH, read_only=True)
    rows = con.execute(
        """
        SELECT state_date, stock_code, final_label, final_score, future_r5, future_r20
        FROM decision_observation
        WHERE hypothesis_id = 'PER_STOCK_OBSERVATION'
          AND future_r5 IS NOT NULL
        ORDER BY state_date, stock_code
        """
    ).fetchall()
    con.close()

    return [
        {
            "state_date": state_date,
            "stock_code": stock_code,
            "final_label": final_label,
            "final_score": final_score,
            "future_r5": future_r5,
            "future_r20": future_r20,
        }
        for state_date, stock_code, final_label, final_score, future_r5, future_r20 in rows
    ]


def _assign_labels(records, observe_pct=0.10):
    """Assign labels deterministically by final_score descending, stock_code ascending."""
    grouped = defaultdict(list)
    for r in records:
        grouped[r["state_date"]].append(r)

    out = []
    for date in sorted(grouped):
        day = sorted(grouped[date], key=lambda r: (-r["final_score"], r["stock_code"]))
        n = len(day)
        for idx, rec in enumerate(day):
            rank_pct = idx / n
            if rank_pct < observe_pct:
                rec["new_label"] = "observe"
            elif rank_pct < 0.60:
                rec["new_label"] = "watch"
            else:
                rec["new_label"] = "reject"
            rec["rank_pct"] = rank_pct
            out.append(rec)
    return out


def _stats(name, returns):
    vals = [r * 100 for r in returns if r is not None]
    if not vals:
        return {"count": 0, "mean": None, "median": None, "positive_rate": None}
    return {
        "count": len(vals),
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
    }


def _evaluate(records, observe_pct=0.10):
    labeled = _assign_labels(records, observe_pct)
    by_label = defaultdict(lambda: defaultdict(list))
    top_n_returns = defaultdict(list)

    grouped = defaultdict(list)
    for r in labeled:
        grouped[r["state_date"]].append(r)

    for date, day in grouped.items():
        day_sorted = sorted(day, key=lambda r: (-r["final_score"], r["stock_code"]))
        cutoff = max(1, int(len(day_sorted) * observe_pct + 0.5))
        for r in day_sorted:
            by_label[r["new_label"]]["fr5"].append(r["future_r5"])
            by_label[r["new_label"]]["fr20"].append(r["future_r20"])
        for r in day_sorted[:cutoff]:
            top_n_returns["fr5"].append(r["future_r5"])
            top_n_returns["fr20"].append(r["future_r20"])

    observe_records = [r for r in labeled if r["new_label"] == "observe"]
    top_n_set = set()
    for date, day in grouped.items():
        day_sorted = sorted(day, key=lambda r: (-r["final_score"], r["stock_code"]))
        cutoff = max(1, int(len(day_sorted) * observe_pct + 0.5))
        for r in day_sorted[:cutoff]:
            top_n_set.add((r["state_date"], r["stock_code"]))

    observe_set = {(r["state_date"], r["stock_code"]) for r in observe_records}
    mismatch = len(observe_set.symmetric_difference(top_n_set))

    return {
        "observe_pct": observe_pct,
        "label_stats": {
            label: {"fr5": _stats(f"{label}_fr5", rets["fr5"]), "fr20": _stats(f"{label}_fr20", rets["fr20"])}
            for label, rets in by_label.items()
        },
        "top_n_stats": {
            "fr5": _stats(f"top_{int(observe_pct*100)}pct_by_score_fr5", top_n_returns["fr5"]),
            "fr20": _stats(f"top_{int(observe_pct*100)}pct_by_score_fr20", top_n_returns["fr20"]),
        },
        "mismatch": mismatch,
        "observe_count": len(observe_records),
    }


def _print_report(result):
    pct = int(result["observe_pct"] * 100)
    print(f"\n=== observe_pct={pct}% ===")
    print(f"observe count: {result['observe_count']}, label/top-N mismatch: {result['mismatch']}")
    print("Label stats:")
    for label in ["observe", "watch", "reject"]:
        st = result["label_stats"].get(label, {})
        fr5 = st.get("fr5", {"count": 0})
        fr20 = st.get("fr20", {"count": 0})
        print(f"  {label:8s}: fr5={fr5}, fr20={fr20}")
    print(f"Top-{pct}% by score: fr5={result['top_n_stats']['fr5']}")
    print(f"Top-{pct}% by score: fr20={result['top_n_stats']['fr20']}")


def main():
    records = _load_records()
    print(f"Loaded {len(records)} per-stock records with future_r5")

    # Baseline: use existing labels in DB
    by_existing = defaultdict(list)
    for r in records:
        by_existing[r["final_label"]].append(r["future_r5"])
    print("\n=== Existing DB labels (fr5) ===")
    for label in ["observe", "watch", "reject"]:
        print(f"  {label:8s}: {_stats(label, by_existing.get(label, []))}")

    by_existing20 = defaultdict(list)
    for r in records:
        by_existing20[r["final_label"]].append(r["future_r20"])
    print("\n=== Existing DB labels (fr20) ===")
    for label in ["observe", "watch", "reject"]:
        print(f"  {label:8s}: {_stats(label, by_existing20.get(label, []))}")

    for pct in [0.05, 0.10, 0.15, 0.20]:
        result = _evaluate(records, observe_pct=pct)
        _print_report(result)


if __name__ == "__main__":
    main()
