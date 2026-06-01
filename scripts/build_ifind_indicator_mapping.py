#!/usr/bin/env python3
"""Build an auditable iFinD macro indicator mapping table.

This is the P0 bridge between GUI-discovered formula/catalog evidence and
machine-runnable macro collection.  It deliberately separates:
  - verified direct iFinD EDB codes,
  - legacy direct codes that still need validation,
  - formula/catalog candidates that are not yet safe for production pulls.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ifind_macro_indicators.json"
OUT_DIR = ROOT / "outputs" / "macro"
DATA_MACRO_DIR = ROOT / "data" / "macro"
PUBLIC_DIR = ROOT / "public"


def ymd(date_str: str) -> str:
    return date_str.replace("-", "")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def latest_snapshot_for(date_str: str) -> dict[str, Any]:
    date_path = OUT_DIR / f"macro_snapshot_{ymd(date_str)}.json"
    if date_path.exists():
        return load_json(date_path)
    latest_path = OUT_DIR / "macro_snapshot_latest.json"
    return load_json(latest_path)


def observation_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("indicators", []) or []:
        code = row.get("indicator_code")
        if code:
            out[str(code)] = row
    return out


def candidate_direct_code(raw: dict[str, Any]) -> str:
    code = raw.get("code")
    if code:
        return str(code)
    nested = raw.get("nested_index_ids") or []
    if nested:
        return str(nested[0])
    formula_id = raw.get("formula_id")
    if formula_id:
        return str(formula_id)
    return ""


def mapping_status(raw: dict[str, Any], observed: dict[str, Any] | None) -> tuple[str, str]:
    status = str(raw.get("status") or "needs_ifind_code")
    code = raw.get("code")
    observed_status = str((observed or {}).get("status") or "")
    if observed_status in {"ok", "gui_imported_needs_ifind_code"}:
        return "validated_observed", "已有观测值，可进入宏观时间序列库。"
    if status == "active" and code:
        return (
            "direct_code_active_unobserved",
            "直接 iFinD 指标码已配置，但当前快照暂无观测；需 API 配额或 GUI 时间序列导入验证。",
        )
    if status == "legacy_code_needs_validation" and code:
        return "legacy_code_pending_validation", "历史指标码存在，但未通过当前 iFinD 拉数验证。"
    if status == "formula_catalog_only":
        if raw.get("nested_index_ids"):
            return (
                "formula_nested_candidate_pending_validation",
                "公式目录里含嵌套指标 ID，可作为候选；仍需直接 EDB 拉数验证。",
            )
        if raw.get("formula_id"):
            return (
                "formula_id_candidate_pending_validation",
                "只有公式/计算 ID，不等同于可直接拉取的 THS_EDB 指标码。",
            )
        return "formula_catalog_needs_direct_code", "只有 GUI 公式目录证据，缺直接指标码或日期-数值导出。"
    if status == "needs_ifind_code":
        return "needs_manual_ifind_code", "缺 iFinD 指标码，需要人工在 iFinD EDB/GUI 中定位。"
    return "pending_review", f"状态 {status} 需要人工复核。"


def build_rows(config_path: Path, date_str: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = load_json(config_path)
    snapshot = latest_snapshot_for(date_str)
    obs_by_code = observation_index(snapshot)
    rows: list[dict[str, Any]] = []
    for idx, raw in enumerate(config.get("indicators", []) or [], start=1):
        code = raw.get("code")
        candidate = candidate_direct_code(raw)
        observed = obs_by_code.get(str(code)) if code else None
        status, note = mapping_status(raw, observed)
        rows.append(
            {
                "rank": idx,
                "indicator_name": raw.get("name") or code or "",
                "category": raw.get("category") or "unknown",
                "frequency": raw.get("frequency") or "",
                "unit": raw.get("unit") or "",
                "use": raw.get("use") or "",
                "config_status": raw.get("status") or "needs_ifind_code",
                "ifind_indicator_code": code or "",
                "candidate_direct_code": candidate,
                "formula_id": raw.get("formula_id") or "",
                "nested_index_ids": ",".join(str(item) for item in (raw.get("nested_index_ids") or [])),
                "source_indicator_name": raw.get("source_indicator_name") or "",
                "formula_source_file": raw.get("formula_source_file") or raw.get("source") or "",
                "source_rtime": raw.get("source_rtime") or "",
                "source_datasource": raw.get("source_datasource") or "",
                "mapping_status": status,
                "validation_note": note,
                "snapshot_status": (observed or {}).get("status") or "",
                "latest_date": (observed or {}).get("latest_date") or "",
                "latest_value": (observed or {}).get("value") if observed else "",
                "history_count": (observed or {}).get("history_count") if observed else 0,
            }
        )
    summary = {
        "total": len(rows),
        "by_config_status": dict(Counter(row["config_status"] for row in rows)),
        "by_mapping_status": dict(Counter(row["mapping_status"] for row in rows)),
        "validated_observed_count": sum(1 for row in rows if row["mapping_status"] == "validated_observed"),
        "direct_code_active_count": sum(
            1 for row in rows if row["config_status"] == "active" and row["ifind_indicator_code"]
        ),
        "formula_catalog_count": sum(1 for row in rows if row["config_status"] == "formula_catalog_only"),
        "needs_manual_code_count": sum(1 for row in rows if row["config_status"] == "needs_ifind_code"),
        "snapshot_source": snapshot.get("date"),
        "research_only": True,
    }
    return rows, summary


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "indicator_name",
        "category",
        "frequency",
        "unit",
        "use",
        "config_status",
        "ifind_indicator_code",
        "candidate_direct_code",
        "formula_id",
        "nested_index_ids",
        "source_indicator_name",
        "formula_source_file",
        "source_rtime",
        "source_datasource",
        "mapping_status",
        "validation_note",
        "snapshot_status",
        "latest_date",
        "latest_value",
        "history_count",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_html(payload: dict[str, Any]) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    trs = []
    for row in payload["rows"]:
        trs.append(
            "<tr>"
            f"<td>{esc(row['rank'])}</td>"
            f"<td><strong>{esc(row['indicator_name'])}</strong><br><span>{esc(row['use'])}</span></td>"
            f"<td>{esc(row['category'])}</td>"
            f"<td>{esc(row['frequency'])}</td>"
            f"<td>{esc(row['config_status'])}</td>"
            f"<td>{esc(row['ifind_indicator_code'])}<br><span>{esc(row['candidate_direct_code'])}</span></td>"
            f"<td>{esc(row['mapping_status'])}</td>"
            f"<td>{esc(row['snapshot_status'])}<br><span>{esc(row['latest_date'])}</span></td>"
            f"<td>{esc(row['validation_note'])}</td>"
            "</tr>"
        )
    summary = payload["summary"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>iFinD 宏观指标映射 {esc(payload["date"])}</title>
  <style>
    body {{ margin:24px; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:#172033; }}
    h1 {{ margin:0 0 8px; font-size:22px; }}
    .summary {{ margin:14px 0; padding:12px 14px; background:#f4f7f6; border:1px solid #d9e4e0; border-radius:6px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border:1px solid #dfe6ee; padding:8px 10px; text-align:left; vertical-align:top; }}
    th {{ background:#eef3f7; position:sticky; top:0; }}
    span {{ color:#667085; font-size:12px; }}
  </style>
</head>
<body>
  <h1>iFinD 宏观指标映射</h1>
  <div class="summary">
    日期 {esc(payload["date"])} ｜ 总数 {esc(summary["total"])} ｜
    active直连码 {esc(summary["direct_code_active_count"])} ｜
    公式目录待验证 {esc(summary["formula_catalog_count"])} ｜
    缺人工码 {esc(summary["needs_manual_code_count"])} ｜
    已有观测 {esc(summary["validated_observed_count"])}
  </div>
  <table>
    <thead><tr><th>#</th><th>指标</th><th>类别</th><th>频率</th><th>配置状态</th><th>iFinD码/候选码</th><th>映射状态</th><th>观测</th><th>说明</th></tr></thead>
    <tbody>{"".join(trs)}</tbody>
  </table>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build auditable iFinD macro indicator mapping table.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    rows, summary = build_rows(Path(args.config), args.date)
    payload = {
        "schema_version": "ifind_indicator_mapping_v1",
        "date": args.date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_config": str(Path(args.config)),
        "summary": summary,
        "rows": rows,
        "research_only": True,
    }
    date_ymd = ymd(args.date)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_MACRO_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"ifind_indicator_mapping_{date_ymd}.json"
    csv_path = OUT_DIR / f"ifind_indicator_mapping_{date_ymd}.csv"
    data_csv_path = DATA_MACRO_DIR / "ifind_indicator_mapping.csv"
    html_path = PUBLIC_DIR / f"ifind_indicator_mapping_{date_ymd}.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, csv_path)
    write_csv(rows, data_csv_path)
    html_path.write_text(render_html(payload), encoding="utf-8")
    shutil.copyfile(json_path, OUT_DIR / "ifind_indicator_mapping_latest.json")
    shutil.copyfile(csv_path, OUT_DIR / "ifind_indicator_mapping_latest.csv")
    shutil.copyfile(html_path, PUBLIC_DIR / "ifind_indicator_mapping_latest.html")
    print(
        json.dumps(
            {
                "ok": True,
                "date": args.date,
                "summary": summary,
                "outputs": {
                    "json": str(json_path),
                    "csv": str(csv_path),
                    "data_csv": str(data_csv_path),
                    "html": str(html_path),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
