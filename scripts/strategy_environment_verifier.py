#!/usr/bin/env python3
"""Registry-driven strategy environment verification orchestrator.

This tool is intentionally a thin read-only layer. It does not reimplement
strategy statistics; it calls the already-audited per-strategy verification
adapters registered in config/strategy_registry.json and aggregates their
outputs into one standard report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "strategy_registry.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "project"


def load_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_macro_snapshot(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise FileNotFoundError(p)
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["_source_path"] = str(p)
    return payload


def _contains_any(value: Any, candidates: tuple[str, ...]) -> bool:
    text = str(value or "").lower()
    return any(item.lower() in text for item in candidates)


def classify_macro_quadrant(macro: dict[str, Any]) -> str:
    """Classify a macro payload into a money/credit quadrant.

    The function accepts either an explicit quadrant field or loose structured
    fields. Unknown inputs remain unknown instead of being guessed.
    """
    for key in ["quadrant", "macro_quadrant", "regime", "macro_regime"]:
        if macro.get(key):
            return str(macro[key])

    money_value = (
        macro.get("money")
        or macro.get("monetary")
        or macro.get("monetary_policy")
        or macro.get("liquidity")
        or macro.get("money_condition")
        or macro.get("liquidity_condition")
    )
    credit_value = (
        macro.get("credit")
        or macro.get("credit_policy")
        or macro.get("credit_condition")
        or macro.get("social_financing_condition")
        or macro.get("financing_condition")
    )

    if _contains_any(money_value, ("宽", "loose", "easing", "easy", "宽松", "充裕")):
        money_label = "宽货币"
    elif _contains_any(money_value, ("紧", "tight", "tightening", "收紧", "偏紧")):
        money_label = "紧货币"
    else:
        money_label = "货币未知"

    if _contains_any(credit_value, ("宽", "loose", "expansion", "扩张", "宽信用", "改善")):
        credit_label = "宽信用"
    elif _contains_any(credit_value, ("紧", "tight", "contraction", "收缩", "紧信用", "走弱")):
        credit_label = "紧信用"
    else:
        credit_label = "信用未知"

    if money_label == "货币未知" and credit_label == "信用未知":
        return "宏观象限未知"
    return f"{money_label}+{credit_label}"


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _macro_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ["rows", "records", "daily", "macro_daily", "snapshots"]:
        if isinstance(payload.get(key), list):
            rows.extend(item for item in payload[key] if isinstance(item, dict))
    for key in ["by_date", "macro_by_date", "macro_quadrant_by_date", "quadrant_by_date"]:
        mapping = payload.get(key)
        if isinstance(mapping, dict):
            for d, item in mapping.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("date", d)
                else:
                    row = {"date": d, "quadrant": item}
                rows.append(row)
    return rows


def macro_quadrant_segments(payload: dict[str, Any], start_date: str, end_date: str) -> list[dict[str, str]]:
    """Return contiguous date segments grouped by macro quadrant.

    This only works when the snapshot carries date-level macro rows. A single
    current macro snapshot is intentionally not expanded across history.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    points: list[tuple[date, str]] = []
    for row in _macro_rows(payload):
        d = _parse_date(row.get("date") or row.get("obs_date") or row.get("trade_date"))
        if not d or d < start or d > end:
            continue
        points.append((d, classify_macro_quadrant(row)))
    points = sorted(set(points), key=lambda item: item[0])
    if not points:
        return []

    segments: list[dict[str, str]] = []
    seg_start, prev_date, current_q = points[0][0], points[0][0], points[0][1]
    for d, q in points[1:]:
        is_contiguous = d <= prev_date + timedelta(days=4)
        if q != current_q or not is_contiguous:
            segments.append(
                {
                    "start_date": seg_start.isoformat(),
                    "end_date": prev_date.isoformat(),
                    "quadrant": current_q,
                }
            )
            seg_start, current_q = d, q
        prev_date = d
    segments.append(
        {"start_date": seg_start.isoformat(), "end_date": prev_date.isoformat(), "quadrant": current_q}
    )
    return segments


def extract_last_json(stdout: str) -> dict[str, Any]:
    """Extract the last JSON object printed by a child verification script."""
    stripped = stdout.strip()
    if stripped:
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    parsed: list[dict[str, Any]] = []
    for idx, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(stdout[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            parsed.append(obj)
    if not parsed:
        raise ValueError("child command did not print a JSON object")
    for obj in reversed(parsed):
        if obj.get("ok") is not None:
            return obj
    return parsed[-1]


def normalized_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return str(p)


def build_adapter_command(
    strategy_id: str,
    strategy_cfg: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    adapter = Path(strategy_cfg["verification_adapter"])
    if not adapter.is_absolute():
        adapter = ROOT / adapter

    cmd = [
        sys.executable,
        str(adapter),
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--primary-window",
        str(args.primary_window),
        "--min-samples",
        str(args.min_samples or strategy_cfg.get("min_samples") or args.default_min_samples),
    ]
    if args.foundation_db:
        cmd.extend(["--foundation-db", normalized_path(args.foundation_db) or args.foundation_db])
    if args.min_ef_count is not None:
        cmd.extend(["--min-ef-count", str(args.min_ef_count)])
    if args.max_ef_count is not None:
        cmd.extend(["--max-ef-count", str(args.max_ef_count)])

    # Raw signal filters are adapter-specific. Bollinger's adapter has a fixed
    # authoritative entry definition, so it deliberately has no --raw-signal.
    raw_signals: list[str] = []
    if args.raw_signal and args.strategy != "all":
        raw_signals = [args.raw_signal]
    elif strategy_id in {"ma2560", "vcp"}:
        raw_signals = strategy_cfg.get("default_raw_signals", [])

    if strategy_id in {"ma2560", "vcp"}:
        for raw_signal in raw_signals:
            cmd.extend(["--raw-signal", raw_signal])

    return cmd


def run_adapter(strategy_id: str, strategy_cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    cmd = build_adapter_command(strategy_id, strategy_cfg, args)
    started_at = datetime.now(timezone.utc).isoformat()
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    finished_at = datetime.now(timezone.utc).isoformat()

    adapter_result: dict[str, Any] | None = None
    parse_error: str | None = None
    if completed.stdout:
        try:
            adapter_result = extract_last_json(completed.stdout)
        except Exception as exc:  # pragma: no cover - diagnostic path
            parse_error = str(exc)

    result: dict[str, Any] = {
        "strategy": strategy_id,
        "ok": completed.returncode == 0,
        "research_only": True,
        "command": cmd,
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "parse_error": parse_error,
    }

    if adapter_result:
        comparison = (
            adapter_result.get("hypothesis_comparison") or adapter_result.get("current_rule_comparison") or {}
        )
        result.update(
            {
                "selected_samples": adapter_result.get("selected_samples"),
                "labeled_samples": adapter_result.get("labeled_samples"),
                "labeled_dates": adapter_result.get("labeled_dates"),
                "outputs": adapter_result.get("outputs", {}),
                "comparison_keys": list(comparison) if isinstance(comparison, dict) else [],
            }
        )

    return result


def render_markdown(aggregate: dict[str, Any], registry: dict[str, Any]) -> str:
    lines: list[str] = [
        "# 策略环境通用验证报告",
        "",
        f"- 生成时间: {aggregate['generated_at']}",
        f"- 验证区间: {aggregate['start_date']} 至 {aggregate['end_date']}",
        f"- 主标签窗口: {aggregate['primary_window']} 日",
        f"- 最小样本门槛: {aggregate['min_samples']}",
        f"- 研究只读: {'是' if aggregate['research_only'] else '否'}",
    ]
    macro = aggregate.get("macro_split") or {}
    if macro:
        lines.append(f"- 宏观快照: `{macro.get('source_path') or ''}`")
        lines.append(f"- 当前宏观象限: {macro.get('current_quadrant') or '宏观象限未知'}")
        lines.append(f"- 宏观拆分状态: {macro.get('status') or 'recorded'}")
    lines.extend(
        [
            "",
            "## 策略汇总",
            "",
            "| 策略 | 状态 | 选中样本 | 有标签样本 | 有标签日期 | 输出 |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in aggregate["strategies"]:
        outputs = item.get("outputs") or {}
        output_bits = []
        for key in ["project_markdown", "markdown", "json"]:
            if outputs.get(key):
                output_bits.append(f"{key}: `{outputs[key]}`")
        lines.append(
            "| {strategy} | {status} | {selected} | {labeled} | {dates} | {outputs} |".format(
                strategy=item["strategy"],
                status="通过执行" if item.get("ok") else "执行失败",
                selected=item.get("selected_samples", "-"),
                labeled=item.get("labeled_samples", "-"),
                dates=item.get("labeled_dates", "-"),
                outputs="<br>".join(output_bits) if output_bits else "-",
            )
        )

    lines.extend(["", "## 本地结论摘录", ""])
    for item in aggregate["strategies"]:
        strategy_cfg = registry["strategies"].get(item["strategy"], {})
        finding = strategy_cfg.get("latest_local_finding", {})
        lines.append(f"### {item['strategy']}")
        if finding:
            lines.append(f"- 最近本地发现: {finding.get('summary', '')}")
            if finding.get("sample_count") is not None:
                lines.append(f"- 注册表样本记录: {finding.get('sample_count')}")
        comparison = item.get("comparison")
        if comparison:
            lines.append("- 本次适配器对比结果已写入对应策略报告。")
        if item.get("parse_error"):
            lines.append(f"- JSON 解析提示: {item['parse_error']}")
        if not item.get("ok"):
            lines.append(f"- stderr: `{item.get('stderr_tail', '')[-500:]}`")
        lines.append("")

    if macro.get("segments"):
        lines.extend(["", "## 宏观象限拆分", ""])
        for segment in macro["segments"]:
            lines.append(f"### {segment['quadrant']} ({segment['start_date']} 至 {segment['end_date']})")
            lines.append("")
            lines.append("| 策略 | 状态 | 选中样本 | 有标签样本 | 有标签日期 | 输出 |")
            lines.append("|---|---|---:|---:|---:|---|")
            for item in segment.get("strategies", []):
                outputs = item.get("outputs") or {}
                output_bits = []
                for key in ["project_markdown", "markdown", "json"]:
                    if outputs.get(key):
                        output_bits.append(f"{key}: `{outputs[key]}`")
                lines.append(
                    "| {strategy} | {status} | {selected} | {labeled} | {dates} | {outputs} |".format(
                        strategy=item["strategy"],
                        status="通过执行" if item.get("ok") else "执行失败",
                        selected=item.get("selected_samples", "-"),
                        labeled=item.get("labeled_samples", "-"),
                        dates=item.get("labeled_dates", "-"),
                        outputs="<br>".join(output_bits) if output_bits else "-",
                    )
                )
            lines.append("")

    lines.extend(
        [
            "## 边界",
            "",
            "- 本工具只读已有数据并调用已审计的策略验证适配器。",
            "- 输出报告不是交易规则，也不会写入正式策略配置。",
            "- 任何 KIMI/DeepSeek 研究结论必须经过本地验证后，才能人工升格到规则文件。",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(aggregate: dict[str, Any], registry: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tag = aggregate["end_date"].replace("-", "")
    strategy_tag = aggregate["strategy"]
    json_path = output_dir / f"strategy_environment_verification_{strategy_tag}_{tag}.json"
    md_path = output_dir / f"strategy_environment_verification_{strategy_tag}_{tag}.md"
    json_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(aggregate, registry), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run registry-driven strategy environment verification.")
    parser.add_argument("--strategy", default="all", help="Strategy id from registry, or all.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--foundation-db", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--primary-window", type=int, default=20)
    parser.add_argument("--min-samples", type=int)
    parser.add_argument("--default-min-samples", type=int, default=30)
    parser.add_argument("--raw-signal", help="Optional single raw signal override for one strategy.")
    parser.add_argument("--min-ef-count", type=int)
    parser.add_argument("--max-ef-count", type=int)
    parser.add_argument(
        "--macro-snapshot", type=Path, help="Optional macro snapshot JSON for quadrant metadata/splitting."
    )
    return parser.parse_args()


def verify_with_macro_split(
    strategy_ids: list[str],
    strategies: dict[str, Any],
    args: argparse.Namespace,
    macro_snapshot_path: str | Path,
) -> dict[str, Any]:
    """Run the same verification by macro quadrant when dated macro rows exist."""
    macro = load_macro_snapshot(macro_snapshot_path)
    current_quadrant = classify_macro_quadrant(macro)
    segments = macro_quadrant_segments(macro, args.start_date, args.end_date)
    macro_result: dict[str, Any] = {
        "source_path": macro.get("_source_path"),
        "current_quadrant": current_quadrant,
        "segments": [],
    }
    if not segments:
        macro_result["status"] = "snapshot_only_no_dated_segments"
        return macro_result

    original_start, original_end = args.start_date, args.end_date
    for segment in segments:
        args.start_date = segment["start_date"]
        args.end_date = segment["end_date"]
        segment_results = [
            run_adapter(strategy_id, strategies[strategy_id], args) for strategy_id in strategy_ids
        ]
        macro_result["segments"].append(
            {
                "quadrant": segment["quadrant"],
                "start_date": segment["start_date"],
                "end_date": segment["end_date"],
                "ok": all(item["ok"] for item in segment_results),
                "strategies": segment_results,
            }
        )
    args.start_date, args.end_date = original_start, original_end
    macro_result["status"] = "split_executed"
    return macro_result


def main() -> int:
    args = parse_args()
    registry_path = args.registry if args.registry.is_absolute() else ROOT / args.registry
    registry = load_registry(registry_path)
    strategies = registry.get("strategies", {})
    if args.strategy == "all":
        strategy_ids = list(strategies)
    else:
        if args.strategy not in strategies:
            raise SystemExit(f"unknown strategy: {args.strategy}")
        strategy_ids = [args.strategy]

    macro_split = (
        verify_with_macro_split(strategy_ids, strategies, args, args.macro_snapshot)
        if args.macro_snapshot
        else {}
    )
    results = [run_adapter(strategy_id, strategies[strategy_id], args) for strategy_id in strategy_ids]
    aggregate = {
        "ok": all(item["ok"] for item in results),
        "research_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry": str(registry_path),
        "strategy": args.strategy,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "foundation_db": normalized_path(args.foundation_db),
        "primary_window": args.primary_window,
        "min_samples": args.min_samples or args.default_min_samples,
        "strategies": results,
    }
    if macro_split:
        aggregate["macro_split"] = macro_split
    outputs = write_outputs(
        aggregate, registry, args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    )
    aggregate["outputs"] = outputs
    Path(outputs["json"]).write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    cli_strategies = [
        {
            "strategy": item["strategy"],
            "ok": item["ok"],
            "selected_samples": item.get("selected_samples"),
            "labeled_samples": item.get("labeled_samples"),
            "labeled_dates": item.get("labeled_dates"),
            "outputs": item.get("outputs", {}),
        }
        for item in results
    ]
    print(
        json.dumps(
            {"ok": aggregate["ok"], "research_only": True, "outputs": outputs, "strategies": cli_strategies},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if aggregate["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
