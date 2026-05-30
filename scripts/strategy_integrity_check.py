#!/usr/bin/env python3
"""Strategy integrity checker — detects simplified/bypassed strategy rules.

Scans signal ledgers and forward observation records for:
  1. Signals that bypassed full entry confirmation (volume grading, pullback count)
  2. Positions that use fixed holding period instead of real exit rules
  3. Exit records that don't match the canonical exit priority chain

Usage:
    python3 scripts/strategy_integrity_check.py --date 2026-05-20
    python3 scripts/strategy_integrity_check.py --ledger path/to/ledger.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ── Canonical exit rule signatures (must appear in this order for each strategy) ──

VCP_EXIT_CHAIN = [
    "假突破离场",
    "硬止损(-6%)",
    "ATR止损(2x)",
    "技术止损(收缩低点)",
    "时间退出(20日未达5%)",
    "移动止损(盈利回吐)",
]

MA2560_EXIT_CHAIN = [
    "跌破60日线，强制清仓",
    "跌破25日均线，止损",
    "止盈(盈利≥10%，全部清仓)",
    "止盈(盈利5-10%，减仓50%)",
]

BOLLINGER_EXIT_CHAIN = [
    "波动率异常(ATR>2x入场时)",
    "中轨跌破(50日SMA)，趋势反转",
    "递减均线止损",
    "上轨回落减仓(跌破布林上轨)",
    "时间退出(10日未达5%盈利)",
    "假突破",
]

# ── Entry confirmation required fields ──

REQUIRED_ENTRY_FIELDS = {
    "vcp": ["signal_grade", "volume_ratio", "is_limit_up"],
    "ma2560": ["vol_grade", "vol_state", "pullback_count", "ma25_upward"],
    "bollinger_bandit": ["signal_grade", "volume_ratio", "is_limit_up"],
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_latest_ledger(date_str: str | None = None) -> Path | None:
    """Find the latest strategy signal ledger."""
    ledger_dir = ROOT / "outputs" / "strategy_signals"
    if date_str:
        path = ledger_dir / f"strategy_signal_daily_{date_str.replace('-', '')}.json"
        if path.exists():
            return path
    # Find latest
    files = sorted(ledger_dir.glob("strategy_signal_daily_*.json"), reverse=True)
    return files[0] if files else None


def find_forward_observation(date_str: str | None = None) -> Path | None:
    """Find the latest forward observation ledger."""
    obs_dir = ROOT / "outputs" / "forward_observation"
    if date_str:
        path = obs_dir / f"forward_observation_{date_str.replace('-', '')}.json"
        if path.exists():
            return path
    files = sorted(obs_dir.glob("forward_observation_*.json"), reverse=True)
    return files[0] if files else None


def find_position_monitor() -> Path | None:
    """Find the latest position monitor output."""
    files = sorted(ROOT.glob("public/position_monitor_*.html"), reverse=True)
    return files[0] if files else None


# ── Check 1: Entry confirmation bypass ──

def check_entry_confirmation(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Check if signals have full entry confirmation fields."""
    violations = []
    signals = ledger.get("signals", []) or ledger.get("data", []) or []

    for sig in signals:
        strategy = sig.get("strategy_id") or sig.get("strategy", "")
        if strategy not in REQUIRED_ENTRY_FIELDS:
            continue

        required = REQUIRED_ENTRY_FIELDS[strategy]
        missing = [f for f in required if f not in sig and f not in (sig.get("entry_confirmation") or {})]

        if missing:
            violations.append({
                "check": "entry_confirmation_bypass",
                "severity": "critical",
                "strategy": strategy,
                "stock_code": sig.get("stock_code", "?"),
                "date": sig.get("date", "?"),
                "missing_fields": missing,
                "reason": f"Signal bypassed entry confirmation: missing {missing}",
            })

    return violations


# ── Check 2: Fixed holding period instead of real exit rules ──

def check_fixed_hold_exit(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Check if exits use fixed holding period instead of real exit rules."""
    violations = []
    trades = ledger.get("trades", []) or ledger.get("closed_trades", []) or []

    for trade in trades:
        exit_reason = trade.get("exit_reason", "")
        strategy = trade.get("strategy_id") or trade.get("strategy", "")
        hold_days = trade.get("hold_days", 0)

        # Detect suspicious fixed-hold patterns
        is_fixed_hold = (
            exit_reason in ("max_hold", "time_exit", "fixed_period")
            or "固定" in exit_reason
            or "到期" in exit_reason
        )

        if is_fixed_hold and hold_days > 0:
            # Check if real exit rules were never evaluated
            has_real_exit = any(
                keyword in exit_reason
                for keyword in ["止损", "止盈", "跌破", "突破", "假突破", "递减", "回落"]
            )
            if not has_real_exit:
                violations.append({
                    "check": "fixed_hold_instead_of_real_exit",
                    "severity": "critical",
                    "strategy": strategy,
                    "stock_code": trade.get("stock_code", "?"),
                    "exit_date": trade.get("exit_date", "?"),
                    "exit_reason": exit_reason,
                    "hold_days": hold_days,
                    "reason": f"Trade exited with fixed hold period ({hold_days}d) instead of real exit rules",
                })

    return violations


# ── Check 3: Exit rule chain integrity ──

def check_exit_chain_integrity(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Check if exits follow the canonical priority chain."""
    violations = []
    trades = ledger.get("trades", []) or ledger.get("closed_trades", []) or []

    for trade in trades:
        exit_reason = trade.get("exit_reason", "")
        strategy = trade.get("strategy_id") or trade.get("strategy", "")

        if strategy == "vcp":
            chain = VCP_EXIT_CHAIN
        elif strategy == "ma2560":
            chain = MA2560_EXIT_CHAIN
        elif strategy == "bollinger_bandit":
            chain = BOLLINGER_EXIT_CHAIN
        else:
            continue

        # Check if exit reason matches any canonical rule
        matched = any(keyword in exit_reason for keyword in chain)
        if not matched and exit_reason not in ("backtest_end", "max_hold"):
            violations.append({
                "check": "unknown_exit_rule",
                "severity": "warning",
                "strategy": strategy,
                "stock_code": trade.get("stock_code", "?"),
                "exit_reason": exit_reason,
                "reason": f"Exit reason '{exit_reason}' does not match any canonical rule for {strategy}",
            })

    return violations


# ── Check 4: Forward observation ledger integrity ──

def check_forward_observation(obs: dict[str, Any]) -> list[dict[str, Any]]:
    """Check forward observation records for simplified exits."""
    violations = []
    records = obs.get("observations", []) or obs.get("records", []) or []

    for rec in records:
        strategy = rec.get("strategy_id") or rec.get("strategy", "")
        exit_type = rec.get("exit_type", "")
        simulated = rec.get("simulated", False)

        # If simulated=True but no exit_rules_reference, it's suspicious
        if simulated and "exit_rules_reference" not in rec:
            violations.append({
                "check": "forward_obs_missing_exit_reference",
                "severity": "warning",
                "strategy": strategy,
                "stock_code": rec.get("stock_code", "?"),
                "date": rec.get("date", "?"),
                "reason": "Forward observation simulation lacks exit_rules_reference",
            })

        # Check for fixed-hold in forward observation
        if exit_type in ("fixed_hold", "time_based"):
            violations.append({
                "check": "forward_obs_fixed_exit",
                "severity": "critical",
                "strategy": strategy,
                "stock_code": rec.get("stock_code", "?"),
                "date": rec.get("date", "?"),
                "reason": "Forward observation uses fixed exit instead of real exit rules",
            })

    return violations


# ── Check 5: Position monitor integrity ──

def check_position_monitor(monitor_html: Path | None) -> list[dict[str, Any]]:
    """Check position monitor output for simplified rules."""
    violations = []
    if not monitor_html or not monitor_html.exists():
        return violations

    content = monitor_html.read_text(encoding="utf-8")

    # Check if monitor uses real exit check functions
    has_vcp_exit = "vcp_exit_check" in content or "假突破" in content
    has_ma2560_exit = "ma2560_exit_check" in content or "跌破60日线" in content
    has_bb_exit = "bb_full_exit_check" in content or "递减均线" in content

    if not (has_vcp_exit or has_ma2560_exit or has_bb_exit):
        violations.append({
            "check": "position_monitor_simplified",
            "severity": "critical",
            "file": str(monitor_html),
            "reason": "Position monitor does not reference real exit check functions",
        })

    # Check for Research-Only disclaimer
    if "Research-Only" not in content and "研究用途" not in content:
        violations.append({
            "check": "missing_disclaimer",
            "severity": "warning",
            "file": str(monitor_html),
            "reason": "Position monitor missing Research-Only disclaimer",
        })

    return violations


# ── Report generation ──

def generate_report(violations: list[dict[str, Any]], check_date: str | None) -> dict[str, Any]:
    """Generate integrity check report."""
    critical = [v for v in violations if v["severity"] == "critical"]
    warnings = [v for v in violations if v["severity"] == "warning"]

    return {
        "ok": len(critical) == 0,
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "check_date": check_date,
        "summary": {
            "total_violations": len(violations),
            "critical": len(critical),
            "warnings": len(warnings),
        },
        "critical_violations": critical,
        "warnings": warnings,
    }


def print_report(report: dict[str, Any]) -> None:
    """Print human-readable report."""
    print("=" * 60)
    print("🔍 Strategy Integrity Check Report")
    print("=" * 60)
    print(f"Date: {report['check_date'] or 'latest'}")
    print(f"Generated: {report['generated_at']}")
    print()

    summary = report["summary"]
    status = "✅ PASS" if report["ok"] else "❌ FAIL"
    print(f"Status: {status}")
    print(f"Total violations: {summary['total_violations']}")
    print(f"  Critical: {summary['critical']}")
    print(f"  Warnings: {summary['warnings']}")
    print()

    if report["critical_violations"]:
        print("CRITICAL VIOLATIONS:")
        for v in report["critical_violations"]:
            print(f"  ❌ [{v['check']}] {v['reason']}")
            if "stock_code" in v:
                print(f"     Stock: {v['stock_code']}, Date: {v.get('date', v.get('exit_date', '?'))}")
        print()

    if report["warnings"]:
        print("WARNINGS:")
        for v in report["warnings"]:
            print(f"  ⚠️  [{v['check']}] {v['reason']}")
        print()

    if report["ok"] and not report["warnings"]:
        print("All checks passed. No integrity violations found.")

    print("=" * 60)


# ── Main ──

def main() -> int:
    parser = argparse.ArgumentParser(description="Strategy integrity checker")
    parser.add_argument("--date", help="Date to check (YYYY-MM-DD)")
    parser.add_argument("--ledger", type=Path, help="Path to signal ledger JSON")
    parser.add_argument("--forward-obs", type=Path, help="Path to forward observation JSON")
    parser.add_argument("--output", type=Path, help="Output JSON path")
    args = parser.parse_args()

    violations: list[dict[str, Any]] = []

    # Check 1: Signal ledger
    ledger_path = args.ledger or find_latest_ledger(args.date)
    if ledger_path and ledger_path.exists():
        print(f"Checking signal ledger: {ledger_path}")
        ledger = load_json(ledger_path)
        violations.extend(check_entry_confirmation(ledger))
        violations.extend(check_fixed_hold_exit(ledger))
        violations.extend(check_exit_chain_integrity(ledger))
    else:
        print(f"Warning: No signal ledger found for {args.date or 'latest'}")

    # Check 2: Forward observation
    obs_path = args.forward_obs or find_forward_observation(args.date)
    if obs_path and obs_path.exists():
        print(f"Checking forward observation: {obs_path}")
        obs = load_json(obs_path)
        violations.extend(check_forward_observation(obs))
    else:
        print(f"Warning: No forward observation found for {args.date or 'latest'}")

    # Check 3: Position monitor
    monitor = find_position_monitor()
    violations.extend(check_position_monitor(monitor))

    # Generate report
    report = generate_report(violations, args.date)
    print_report(report)

    # Save JSON
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n📄 Report saved: {args.output}")
    else:
        default_out = ROOT / "outputs" / "project" / f"strategy_integrity_check_{args.date or 'latest'}.json"
        default_out.parent.mkdir(parents=True, exist_ok=True)
        default_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n📄 Report saved: {default_out}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
