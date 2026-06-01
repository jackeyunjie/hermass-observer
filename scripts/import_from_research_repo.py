#!/usr/bin/env python3
"""Import standard research outputs into the lightweight product shell."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = PRODUCT_ROOT.parent / "hongrun-chaos-trading-system"

SOURCE_DAILY_FIXTURE = (
    RESEARCH_ROOT
    / "reports/p108_daily_consumer_observation_card_20260518/fixtures/daily_observation_card.json"
)
SOURCE_DAILY_HTML = RESEARCH_ROOT / "reports/p108_daily_consumer_observation_card_20260518/index.html"
SOURCE_OMNI_SUMMARY = (
    RESEARCH_ROOT
    / "reports/p116_data_foundation_acceleration_20260518/p116d_ashare_omni_cycle_alignment_summary.json"
)
SOURCE_STATE_DB = (
    RESEARCH_ROOT / "outputs/p116_ashare_d1_native_state_20260518/p116_ashare_d1_native_state.duckdb"
)
SOURCE_POOL_CSV = (
    RESEARCH_ROOT / "reports/p25_ashare_research_universe_20260509/ashare_research_pool_a250.csv"
)

OUT_FIXTURES = PRODUCT_ROOT / "fixtures"
OUT_PUBLIC = PRODUCT_ROOT / "public"
OUT_REPORTS = PRODUCT_ROOT / "reports"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pool_symbols(pool_path: Path) -> set[str]:
    """Load stock pool symbols from CSV."""
    symbols: set[str] = set()
    if not pool_path.exists():
        return symbols
    import csv

    with open(pool_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("symbol", "").strip()
            if sym:
                symbols.add(sym)
    return symbols


def filter_cards_from_state_db() -> tuple[list[dict], set[str], str]:
    """Filter A250 pool symbols with >=2 E/F timeframes directly from state DB."""
    import csv
    import duckdb

    pool_symbols = load_pool_symbols(SOURCE_POOL_CSV)
    pool_names: dict[str, str] = {}
    with open(SOURCE_POOL_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("symbol", "").strip()
            if sym:
                pool_names[sym] = row.get("name", "").strip()

    if not pool_symbols or not SOURCE_STATE_DB.exists():
        return [], pool_symbols, ""

    conn = duckdb.connect(str(SOURCE_STATE_DB), read_only=True)
    max_date = conn.execute("SELECT MAX(base_date) FROM ashare_d1_multitf_asof_postclose").fetchone()[0]
    placeholders = ",".join([f"'{s}'" for s in pool_symbols])

    result = conn.execute(f"""
        SELECT stock_code, MN1_state_hex, W_state_hex, D_state_hex,
               MN1_trend, W_trend, D_trend,
               MN1_position, W_position, D_position,
               MN1_compression, W_compression, D_compression,
               base_close
        FROM ashare_d1_multitf_asof_postclose
        WHERE stock_code IN ({placeholders})
        AND base_date = '{max_date}'
        AND (
            (CASE WHEN MN1_state_hex IN ('E', 'F') THEN 1 ELSE 0 END) +
            (CASE WHEN W_state_hex IN ('E', 'F') THEN 1 ELSE 0 END) +
            (CASE WHEN D_state_hex IN ('E', 'F') THEN 1 ELSE 0 END)
        ) >= 2
        ORDER BY base_close DESC
    """).fetchall()
    conn.close()

    cards = []
    for i, r in enumerate(result, 1):
        code = r[0]
        name = pool_names.get(code, "")
        ef_count = sum([r[1] in {"E", "F"}, r[2] in {"E", "F"}, r[3] in {"E", "F"}])
        cards.append(
            {
                "rank": i,
                "code": code,
                "name": name,
                "name_display_cn": name,
                "date": str(max_date),
                "close": r[13],
                "MN1_state_hex": r[1],
                "W_state_hex": r[2],
                "D_state_hex": r[3],
                "MN1_state_date": str(max_date),
                "W_state_date": str(max_date),
                "D_state_date": str(max_date),
                "MN1_trend_cn": r[4],
                "W_trend_cn": r[5],
                "D_trend_cn": r[6],
                "MN1_position_cn": r[7],
                "W_position_cn": r[8],
                "D_position_cn": r[9],
                "MN1_compression_cn": r[10],
                "W_compression_cn": r[11],
                "D_compression_cn": r[12],
                "observation_reason": f"A250股票池筛选：MN1={r[1]} W1={r[2]} D1={r[3]}（{ef_count}个周期为E/F）",
                "research_only_flag": True,
            }
        )

    return cards, pool_symbols, str(max_date)


def build_product_home(daily: dict, omni: dict, source_html_name: str, filtered_cards: list[dict]) -> str:
    cards = filtered_cards[:12]
    card_items = []
    for card in cards:
        code = card.get("code") or card.get("stock_code") or "unknown"
        name = card.get("name") or card.get("stock_name") or ""
        reason = card.get("observation_reason") or card.get("reason_cn") or "标准观察对象"
        level = card.get("data_level") or daily.get("data_level_current") or ""
        mn1 = card.get("MN1_state_hex", "")
        w1 = card.get("W_state_hex", "")
        d1 = card.get("D_state_hex", "")
        state_badge = f"MN1={mn1} | W1={w1} | D1={d1}"
        card_items.append(
            f"""
            <article class="card">
              <h3>{code} <span>{name}</span></h3>
              <p>{reason}</p>
              <small>{level} | {state_badge}</small>
            </article>
            """
        )
    if not card_items:
        card_items.append(
            '<article class="card"><h3>今日无正式观察对象</h3><p>系统没有用排序补位。</p></article>'
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Hermass Observer Product</title>
  <style>
    body {{ margin: 0; padding: 28px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f7f4; color: #17212b; }}
    header, section {{ background: #fff; border-radius: 10px; padding: 24px; margin-bottom: 22px; box-shadow: 0 1px 5px rgba(0,0,0,.08); }}
    header {{ border-top: 8px solid #116b4b; }}
    h1 {{ font-size: 38px; margin: 0 0 10px; }}
    h2 {{ font-size: 22px; margin: 0 0 14px; }}
    p {{ line-height: 1.65; color: #566474; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .card {{ border: 1px solid #dde5df; border-radius: 8px; padding: 16px; }}
    .card h3 {{ margin: 0 0 8px; font-size: 20px; }}
    .card span {{ color: #697789; font-size: 14px; }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
    .kpi {{ border: 1px solid #dde5df; border-radius: 8px; padding: 14px; }}
    .kpi small {{ color: #697789; }}
    .kpi strong {{ display: block; margin-top: 6px; font-size: 22px; }}
    .note {{ background: #eef7f2; border: 1px solid #c9e7d7; padding: 12px 14px; border-radius: 8px; color: #2f5f47; }}
    a {{ color: #116b4b; font-weight: 700; text-decoration: none; }}
  </style>
</head>
<body>
  <header>
    <h1>Hermass 每日观察产品</h1>
    <p>前端简单，后端数据说话。当前页面只展示研究母库已经验收的观察对象，不在产品层重新计算公式。</p>
    <p class="note">当前 as_of_date：{daily.get("as_of_date", "unknown")}；数据层级：{daily.get("data_level_current", "unknown")}；Research-only。</p>
  </header>

  <section>
    <h2>Observer / Omni 数据底座</h2>
    <div class="kpis">
      <div class="kpi"><small>D1 observer rows</small><strong>{omni.get("d1_observer_rows", "NA")}</strong></div>
      <div class="kpi"><small>W1 observer rows</small><strong>{omni.get("w1_observer_rows", "NA")}</strong></div>
      <div class="kpi"><small>MN1 observer rows</small><strong>{omni.get("mn1_observer_rows", "NA")}</strong></div>
      <div class="kpi"><small>Omni rows</small><strong>{omni.get("omni_rows", "NA")}</strong></div>
      <div class="kpi"><small>Latest sync date</small><strong>{omni.get("latest_sync_date", "NA")}</strong></div>
      <div class="kpi"><small>Symbols</small><strong>{omni.get("symbol_count", "NA")}</strong></div>
    </div>
  </section>

  <section>
    <h2>今日观察卡</h2>
    <div class="grid">{"".join(card_items)}</div>
  </section>

  <section>
    <h2>原始母库页面</h2>
    <p><a href="../reports/{source_html_name}">查看导入的 P108 页面副本</a></p>
  </section>
</body>
</html>
"""


def main() -> int:
    for path in [SOURCE_DAILY_FIXTURE, SOURCE_DAILY_HTML, SOURCE_OMNI_SUMMARY]:
        require(path)
    OUT_FIXTURES.mkdir(parents=True, exist_ok=True)
    OUT_PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT_REPORTS.mkdir(parents=True, exist_ok=True)

    daily = load_json(SOURCE_DAILY_FIXTURE)
    omni = load_json(SOURCE_OMNI_SUMMARY)

    # Filter cards from A250 pool using state DB
    filtered_cards, pool_symbols, max_date = filter_cards_from_state_db()

    daily_out = OUT_FIXTURES / "daily_observation_card.json"
    omni_out = OUT_FIXTURES / "p116d_omni_summary.json"
    html_copy = OUT_REPORTS / "p108_source_index.html"
    shutil.copy2(SOURCE_OMNI_SUMMARY, omni_out)
    shutil.copy2(SOURCE_DAILY_HTML, html_copy)

    # Build filtered product home
    product_home = build_product_home(daily, omni, html_copy.name, filtered_cards)
    (OUT_PUBLIC / "index.html").write_text(product_home, encoding="utf-8")

    # Write filtered daily_observation_card.json
    filtered_daily = dict(daily)
    filtered_daily["cards"] = filtered_cards
    filtered_daily["card_count"] = len(filtered_cards)
    filtered_daily["latest_date_count"] = len(filtered_cards)
    filtered_daily["universe_count"] = len(pool_symbols) if pool_symbols else daily.get("universe_count", 0)
    if max_date:
        filtered_daily["as_of_date"] = max_date
    (OUT_FIXTURES / "daily_observation_card.json").write_text(
        json.dumps(filtered_daily, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "schema_version": "hermass_observer_product_import_v0_1",
        "generated_at": now_iso(),
        "research_root": str(RESEARCH_ROOT),
        "sources": {
            "daily_fixture": str(SOURCE_DAILY_FIXTURE),
            "daily_html": str(SOURCE_DAILY_HTML),
            "omni_summary": str(SOURCE_OMNI_SUMMARY),
            "state_db": str(SOURCE_STATE_DB),
            "pool_csv": str(SOURCE_POOL_CSV),
        },
        "outputs": {
            "daily_fixture": str(daily_out),
            "omni_summary": str(omni_out),
            "source_html_copy": str(html_copy),
            "product_home": str(OUT_PUBLIC / "index.html"),
        },
        "as_of_date": max_date or daily.get("as_of_date"),
        "daily_data_level": daily.get("data_level_current"),
        "omni_data_level": omni.get("data_level"),
        "research_only_flag": True,
    }
    (OUT_REPORTS / "import_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
