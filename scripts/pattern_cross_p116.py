#!/usr/bin/env python3
"""长期形态 × P116 E/F 池交叉输出。

将形态生命周期与每日 E/F 标准池交叉，输出：
  - 哪些 E/F 池品种有长期 VCP/2560 结构支撑
  - VCP 候选池中有哪些今天进入了 E/F
  - 2560 候选池有哪些今天完成了金叉

用法：
  python3 scripts/pattern_cross_p116.py --date 2026-05-21
    → outputs/pattern_lifecycle/pattern_cross_ef_20260521.json
    → outputs/pattern_lifecycle/pattern_cross_ef_20260521.csv
    → public/pattern_cross_ef_20260521.html
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_DB = ROOT / "outputs" / "pattern_lifecycle" / "pattern_lifecycle.duckdb"


def ymd(d: str) -> str:
    return d.replace("-", "")


def build_cross(date_str: str) -> dict[str, Any]:
    db = LIFECYCLE_DB
    con = duckdb.connect(str(db), read_only=True)

    # 1. E/F 池中哪些有 VCP 结构支撑
    ef_vcp = con.execute(f"""
        SELECT
            o.stock_code,
            o.close,
            o.ef_count,
            o.vcp_phase,
            o.vcp_contraction_days,
            o.ma2560_phase,
            vcp.first_detected AS vcp_since,
            vcp.quality_tier AS vcp_quality_tier,
            vcp.contraction_count AS vcp_contraction_total,
            vcp.lowest_range_ratio,
            ma2560.first_detected AS ma2560_since,
            ma2560.alignment_days,
            CASE
                WHEN vcp.status = 'active' AND ma2560.status = 'active' THEN 'dual_structure'
                WHEN vcp.status = 'active' THEN 'vcp_only'
                WHEN ma2560.status = 'active' THEN 'ma2560_only'
                ELSE 'none'
            END AS structure_type
        FROM pattern_observation_daily o
        LEFT JOIN vcp_candidate_pool vcp
          ON o.stock_code = vcp.stock_code
         AND vcp.status = 'active'
        LEFT JOIN ma2560_candidate_pool ma2560
          ON o.stock_code = ma2560.stock_code
         AND ma2560.status = 'active'
        WHERE o.obs_date = '{date_str}'
          AND o.in_ef_pool = TRUE
          AND (vcp.status = 'active' OR ma2560.status = 'active')
        ORDER BY o.ef_count DESC, o.close DESC
    """).fetchall()

    # 2. VCP 候选池中今天新进入 E/F 的
    vcp_entered_ef = con.execute(f"""
        SELECT
            vcp.stock_code,
            vcp.first_detected,
            vcp.contraction_count,
            o.close,
            o.ef_count
        FROM vcp_candidate_pool vcp
        JOIN pattern_observation_daily o
          ON vcp.stock_code = o.stock_code
         AND o.obs_date = '{date_str}'
        WHERE vcp.status = 'active'
          AND o.in_ef_pool = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM pattern_observation_daily p
              WHERE p.stock_code = vcp.stock_code
                AND p.obs_date = DATE '{date_str}' - 1
                AND p.in_ef_pool = TRUE
          )
        ORDER BY o.close DESC
    """).fetchall()

    # 3. 2560 今日金叉 + E/F
    golden_cross_ef = con.execute(f"""
        SELECT
            e.stock_code,
            e.close,
            o.ef_count,
            e.detail
        FROM pattern_events e
        JOIN pattern_observation_daily o
          ON e.stock_code = o.stock_code
         AND o.obs_date = '{date_str}'
        WHERE e.event_date = '{date_str}'
          AND e.pattern_type = 'ma2560'
          AND e.event = 'golden_cross'
          AND o.in_ef_pool = TRUE
        ORDER BY e.close DESC
    """).fetchall()

    # 4. 大盘周期
    macro = con.execute(f"""
        SELECT asset_code, asset_type, mn1_state_hex, w1_state_hex, d1_state_hex, ef_count
        FROM macro_regime_daily
        WHERE regime_date = '{date_str}'
        ORDER BY ef_count DESC
    """).fetchall()

    con.close()

    ef_vcp_rows = [
        {
            "stock_code": r[0],
            "close": round(r[1], 2) if r[1] else None,
            "ef_count": r[2],
            "vcp_phase": r[3],
            "vcp_contraction_days": r[4],
            "ma2560_phase": r[5],
            "vcp_since": str(r[6]) if r[6] else None,
            "vcp_quality_tier": r[7],
            "vcp_contraction_total": r[8],
            "lowest_range_ratio": round(r[9], 5) if r[9] else None,
            "ma2560_since": str(r[10]) if r[10] else None,
            "alignment_days": r[11],
            "structure_type": r[12],
        }
        for r in ef_vcp
    ]

    vcp_entered_rows = [
        {
            "stock_code": r[0],
            "first_detected": str(r[1]),
            "contraction_count": r[2],
            "close": round(r[3], 2) if r[3] else None,
            "ef_count": r[4],
        }
        for r in vcp_entered_ef
    ]

    golden_rows = [
        {
            "stock_code": r[0],
            "close": round(r[1], 2) if r[1] else None,
            "ef_count": r[2],
            "detail": r[3],
        }
        for r in golden_cross_ef
    ]

    macro_rows = [
        {
            "asset_code": r[0],
            "asset_type": r[1],
            "mn1": r[2],
            "w1": r[3],
            "d1": r[4],
            "ef_count": r[5],
        }
        for r in macro
    ]

    return {
        "schema_version": "pattern_cross_p116_v1",
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ef_vcp_count": len(ef_vcp_rows),
        "vcp_entered_ef_count": len(vcp_entered_rows),
        "golden_cross_ef_count": len(golden_rows),
        "macro_regime": macro_rows,
        "ef_with_structure": ef_vcp_rows,
        "vcp_entered_ef": vcp_entered_rows,
        "golden_cross_ef": golden_rows,
        "research_only": True,
    }


def write_outputs(payload: dict[str, Any], date_str: str) -> dict[str, Path]:
    out_dir = ROOT / "outputs" / "pattern_lifecycle"
    pub_dir = ROOT / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    pub_dir.mkdir(parents=True, exist_ok=True)
    date_ymd = ymd(date_str)

    json_path = out_dir / f"pattern_cross_ef_{date_ymd}.json"
    csv_path = out_dir / f"pattern_cross_ef_{date_ymd}.csv"
    html_path = pub_dir / f"pattern_cross_ef_{date_ymd}.html"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV
    rows = payload["ef_with_structure"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # HTML
    macro_items = "".join(
        f"<span class='chip {r['asset_type']}'>{r['asset_code']} {r['mn1']}/{r['w1']}/{r['d1']} EF={r['ef_count']}</span>"
        for r in payload["macro_regime"]
    )

    table_rows = ""
    for r in payload["ef_with_structure"][:100]:
        stype = r.get("structure_type", "none")
        badge = {"dual_structure": "🔴双结构", "vcp_only": "🟡VCP", "ma2560_only": "🔵2560"}.get(stype, stype)
        table_rows += (
            f"<tr>"
            f"<td>{html.escape(r['stock_code'])}</td>"
            f"<td>{r['ef_count']}</td>"
            f"<td>{r.get('vcp_phase', '')}</td>"
            f"<td>{r.get('vcp_contraction_days', 0)}天</td>"
            f"<td>{r.get('vcp_quality_tier', '')}</td>"
            f"<td>{r.get('ma2560_phase', '')}</td>"
            f"<td>{r.get('vcp_since', '')}</td>"
            f"<td>{r.get('ma2560_since', '')}</td>"
            f"<td>{badge}</td>"
            f"</tr>"
        )

    golden_table = ""
    for r in payload["golden_cross_ef"]:
        golden_table += (
            f"<tr><td>{html.escape(r['stock_code'])}</td>"
            f"<td>{r['ef_count']}</td>"
            f"<td>{html.escape(r.get('detail', ''))}</td></tr>"
        )

    email = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>形态 × P116 交叉报告 {date_str}</title>
<style>body{{margin:0;padding:20px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f5f7f4;color:#17212b}}
section{{background:#fff;border-radius:8px;padding:18px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
h2{{margin:0 0 12px}} table{{border-collapse:collapse;width:100%}}
th,td{{padding:6px 10px;border-bottom:1px solid #e5ebf0;text-align:left;font-size:13px}}
th{{background:#f8fafb;position:sticky;top:0}}
.chip{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px}}
.index{{background:#e3f2fd}} .etf{{background:#e8f5e9}}
.badge{{font-weight:700}} .note{{color:#607080;font-size:12px}}
</style></head><body>
<header><h1>形态生命周期 × P116 交叉报告</h1><p>{date_str} · VCP/2560 长期观察池与三周期 E/F 交叉结果</p></header>
<section><h2>大盘 / 行业周期</h2><div>{macro_items}</div></section>
<section><h2>E/F 池中有形态结构支撑（{payload["ef_vcp_count"]}只，显示前100）</h2>
<table><thead><tr><th>代码</th><th>EF</th><th>VCP相</th><th>收缩天数</th><th>VCP等级</th><th>2560相</th><th>VCP自</th><th>2560自</th><th>结构</th></tr></thead><tbody>{table_rows}</tbody></table></section>
<section><h2>今日 2560 金叉 + E/F 池（{payload["golden_cross_ef_count"]}只）</h2>
{"<table><thead><tr><th>代码</th><th>EF</th><th>事件</th></tr></thead><tbody>" + golden_table + "</tbody></table>" if golden_table else "<p>今日无金叉+E/F品种</p>"}
</section>
<p class="note">Research-Only · 本页为形态生命周期与 P116 E/F 标准池交叉观察，不构成投资建议。</p>
</body></html>"""
    html_path.write_text(email, encoding="utf-8")

    return {"json": json_path, "csv": csv_path, "html": html_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    payload = build_cross(args.date)
    paths = write_outputs(payload, args.date)
    print(
        json.dumps(
            {
                "date": args.date,
                "ef_vcp": payload["ef_vcp_count"],
                "vcp_entered": payload["vcp_entered_ef_count"],
                "golden_cross": payload["golden_cross_ef_count"],
                "outputs": {k: str(v) for k, v in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
