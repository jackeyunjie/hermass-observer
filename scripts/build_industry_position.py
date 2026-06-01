#!/usr/bin/env python3
"""
build_industry_position.py  —  产业链 Phase 2 行业景气度评分计算与写入

基于 Phase 1 填充的 chain_dynamics 期货价格数据，结合行业 ETF State 与静态画像，
按 Claude 方案计算 31 个申万一级行业的景气度评分，写入 industry_position 表并生成报告。

评分公式（Phase 2 简化版）：
    prosperity_score = 0.40 × price_score + 0.35 × etf_score + 0.25 × breadth_score

用法：
    # 每日自动运行（默认使用 chain_dynamics 最新日期）
    source .venv/bin/activate && python3 scripts/build_industry_position.py

    # 指定日期
    python3 scripts/build_industry_position.py --date 2026-05-23

    # 仅检查不写入
    python3 scripts/build_industry_position.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

# ── 路径配置 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CONFIG_DIR = PROJECT_ROOT / "config"

CHAIN_DB_PATH = OUTPUTS_DIR / "industry_chain" / "chain_dynamics.duckdb"
INDUSTRY_CHAIN_DB = OUTPUTS_DIR / "industry_chain" / "industry_chain_evidence.duckdb"
REPORT_DIR = OUTPUTS_DIR / "industry_chain"
MARKET_ASSETS_STATE_DIR = OUTPUTS_DIR / "market_assets_state"
STATE_CACHE_DIR = OUTPUTS_DIR / "state_cache"
FUNDAMENTAL_DB = OUTPUTS_DIR / "fundamental" / "fundamental_evidence.duckdb"

INDUSTRY_ROTATION_ASSETS_PATH = CONFIG_DIR / "industry_rotation_assets.json"

# ── 31 个申万一级行业列表 ─────────────────────────────
SW_L1_INDUSTRIES = [
    "农林牧渔",
    "基础化工",
    "钢铁",
    "有色金属",
    "电子",
    "家用电器",
    "食品饮料",
    "纺织服饰",
    "轻工制造",
    "医药生物",
    "公用事业",
    "交通运输",
    "房地产",
    "商贸零售",
    "社会服务",
    "综合",
    "建筑材料",
    "建筑装饰",
    "电力设备",
    "国防军工",
    "计算机",
    "传媒",
    "通信",
    "银行",
    "非银金融",
    "汽车",
    "机械设备",
    "煤炭",
    "石油石化",
    "环保",
    "美容护理",
]

# ── 产业链目录 ────────────────────────────────────────
CHAIN_CATALOG = {
    "ai_compute": {"related_sw_l1": ["电子", "通信", "计算机"]},
    "nev": {"related_sw_l1": ["有色金属", "基础化工", "电力设备", "汽车"]},
    "solar": {"related_sw_l1": ["电力设备", "机械设备"]},
    "semiconductor": {"related_sw_l1": ["电子"]},
    "military": {"related_sw_l1": ["国防军工"]},
    "consumer_spirits": {"related_sw_l1": ["食品饮料"]},
}

# ── 产业链位置映射 ────────────────────────────────────
CHAIN_POSITION_MAP = {
    "有色金属": "上游",
    "基础化工": "上游",
    "钢铁": "上游",
    "煤炭": "上游",
    "石油石化": "上游",
    "农林牧渔": "上游",
    "建筑材料": "上游",
    "电子": "综合",
    "国防军工": "综合",
    "医药生物": "综合",
    "综合": "综合",
    "电力设备": "中游",
    "机械设备": "中游",
    "通信": "中游",
    "建筑装饰": "中游",
    "轻工制造": "中游",
    "环保": "中游",
    "汽车": "下游",
    "食品饮料": "下游",
    "家用电器": "下游",
    "计算机": "下游",
    "房地产": "下游",
    "商贸零售": "下游",
    "社会服务": "下游",
    "纺织服饰": "下游",
    "传媒": "下游",
    "美容护理": "下游",
    "银行": "配套",
    "非银金融": "配套",
    "公用事业": "配套",
    "交通运输": "配套",
}

# ── trend 到数值分的映射 ──────────────────────────────
TREND_SCORE = {
    "up": 10.0,
    "turning_up": 7.5,
    "flat": 5.0,
    "turning_down": 2.5,
    "down": 0.0,
}


# ── 数据加载 ──────────────────────────────────────────


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_industry_rotation_assets() -> dict[str, dict[str, str]]:
    """加载 ETF 到 sw_l1 的映射。"""
    data = load_json(INDUSTRY_ROTATION_ASSETS_PATH)
    mapping: dict[str, dict[str, str]] = {}
    for item in data.get("industry_etf_assets", []):
        sw_l1 = item.get("sw_l1")
        symbol = item.get("symbol")
        if sw_l1 and symbol:
            mapping[sw_l1] = {"symbol": symbol, "name": item.get("name", "")}
    return mapping


def find_latest_market_assets_state(date_str: str) -> dict[str, Any] | None:
    """查找指定日期或之前最近的 market_assets_state JSON。"""
    target = date_str.replace("-", "")
    candidates = []
    for f in sorted(MARKET_ASSETS_STATE_DIR.glob("market_assets_state_*.json"), reverse=True):
        ymd = f.stem.replace("market_assets_state_", "")
        if ymd <= target:
            candidates.append((ymd, f))
    if not candidates:
        return None
    # 取最近的
    candidates.sort(key=lambda x: x[0], reverse=True)
    return load_json(candidates[0][1])


def load_etf_state(date_str: str) -> dict[str, dict[str, Any]]:
    """加载行业 ETF State，按 sw_l1 聚合 ef_count 和综合 score。"""
    data = find_latest_market_assets_state(date_str)
    if data is None:
        return {}

    etf_assets = load_industry_rotation_assets()
    result: dict[str, dict[str, Any]] = {}

    for sw_l1 in SW_L1_INDUSTRIES:
        # 查找该行业的 ETF 记录
        etf_symbol = etf_assets.get(sw_l1, {}).get("symbol")
        if not etf_symbol:
            result[sw_l1] = {"ef_count": 0, "etf_score": 5.0, "symbol": None}
            continue

        etf_row = None
        for item in data if isinstance(data, list) else []:
            if item.get("symbol") == etf_symbol and item.get("asset_type") == "industry_etf":
                etf_row = item
                break

        if etf_row is None:
            result[sw_l1] = {"ef_count": 0, "etf_score": 5.0, "symbol": etf_symbol}
            continue

        ef_count = etf_row.get("ef_count", 0)
        mn1 = etf_row.get("mn1_state_score", 0) or 0
        w1 = etf_row.get("w1_state_score", 0) or 0
        d1 = etf_row.get("d1_state_score", 0) or 0
        score_sum = mn1 + w1 + d1

        # ef_count 0-3 → 0-7.5; state score -45~+45 → 0-2.5
        ef_part = ef_count * 2.5
        state_part = max(0.0, min(2.5, (score_sum + 45) / 90 * 2.5))
        etf_score = max(0.0, min(10.0, ef_part + state_part))

        result[sw_l1] = {
            "ef_count": ef_count,
            "etf_score": round(etf_score, 2),
            "symbol": etf_symbol,
            "score_sum": score_sum,
        }

    return result


def load_chain_dynamics_latest(db_path: Path) -> list[dict]:
    """从 chain_dynamics 读取每个指标的最新记录。"""
    con = duckdb.connect(str(db_path), read_only=True)
    rows = (
        con.execute("""
        SELECT
            chain_id, chain_node, indicator_name, latest_value,
            prev_value, trend, percentile_1y, percentile_3y,
            as_of_date, collected_at
        FROM chain_dynamics
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY chain_id, chain_node, indicator_name
            ORDER BY as_of_date DESC
        ) = 1
    """)
        .fetchdf()
        .to_dict("records")
    )
    con.close()
    return rows


def load_breadth_data(date_str: str) -> dict[str, tuple[int, int]]:
    """读取各行业 EF 股票占比。返回 {sw_l1: (ef_count, total_count)}。"""
    cache_db = STATE_CACHE_DIR / "state_cache.duckdb"
    if not cache_db.exists() or not FUNDAMENTAL_DB.exists():
        return {}

    fund_con = duckdb.connect(str(FUNDAMENTAL_DB), read_only=True)
    ifind_df = fund_con.execute("SELECT stock_code, sw_l1 FROM ifind_industry_chain_profile").fetchdf()
    fund_con.close()

    cache_con = duckdb.connect(str(cache_db), read_only=True)
    # 找到最近的可用日期
    latest_row = cache_con.execute(
        f"SELECT MAX(obs_date) FROM state_ef_daily WHERE obs_date <= '{date_str}'"
    ).fetchone()
    effective_date = latest_row[0] if latest_row and latest_row[0] else date_str
    ef_df = cache_con.execute(
        f"SELECT stock_code FROM state_ef_daily WHERE obs_date = '{effective_date}'"
    ).fetchdf()
    cache_con.close()

    total_by_sw = ifind_df.groupby("sw_l1").size().to_dict()
    merged = ef_df.merge(ifind_df, on="stock_code", how="left")
    ef_by_sw = merged.groupby("sw_l1").size().to_dict()

    result: dict[str, tuple[int, int]] = {}
    for sw, total in total_by_sw.items():
        result[sw] = (ef_by_sw.get(sw, 0), total)
    return result


# ── 评分计算 ──────────────────────────────────────────


def compute_price_score(chain_rows: list[dict]) -> float | None:
    """基于趋势和分位数综合计算价格分（0-10）。"""
    if not chain_rows:
        return None

    trend_scores = []
    percentile_scores = []

    for row in chain_rows:
        trend = row.get("trend")
        if trend in TREND_SCORE:
            trend_scores.append(TREND_SCORE[trend])

        p1y = row.get("percentile_1y")
        p3y = row.get("percentile_3y")
        if p1y is not None:
            percentile_scores.append(p1y / 10.0)
        elif p3y is not None:
            percentile_scores.append(p3y / 10.0)

    avg_trend = sum(trend_scores) / len(trend_scores) if trend_scores else 5.0
    avg_percentile = sum(percentile_scores) / len(percentile_scores) if percentile_scores else 5.0

    return round(avg_trend * 0.6 + avg_percentile * 0.4, 2)


def compute_breadth_score(sw_l1: str, breadth_map: dict[str, tuple[int, int]]) -> float:
    """基于 EF 股票占比计算覆盖分（0-10）。"""
    ef_cnt, total_cnt = breadth_map.get(sw_l1, (0, 0))
    if total_cnt <= 0:
        return 0.0
    pct = ef_cnt / total_cnt * 100.0
    return round(min(10.0, pct), 2)


def derive_chain_position(sw_l1: str) -> str:
    return CHAIN_POSITION_MAP.get(sw_l1, "待确定")


def derive_chain_ids(sw_l1: str) -> list[str]:
    result = []
    for chain_id, info in CHAIN_CATALOG.items():
        if sw_l1 in info.get("related_sw_l1", []):
            result.append(chain_id)
    return result


def map_rating(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 7.0:
        return "high"
    if score >= 4.5:
        return "medium"
    return "low"


def build_industry_position(
    date_str: str,
    chain_db_path: Path,
) -> list[dict]:
    """构建 31 个申万一级行业的 industry_position 记录。"""
    chain_rows = load_chain_dynamics_latest(chain_db_path)
    etf_state = load_etf_state(date_str)
    breadth_map = load_breadth_data(date_str)
    etf_assets = load_industry_rotation_assets()

    # 按 sw_l1 分组 chain_dynamics 数据
    chain_to_sw_l1: dict[str, list[str]] = {}
    for chain_id, info in CHAIN_CATALOG.items():
        for sw_l1 in info.get("related_sw_l1", []):
            chain_to_sw_l1.setdefault(chain_id, []).append(sw_l1)

    sw_l1_chain_rows = {sw: [] for sw in SW_L1_INDUSTRIES}
    for row in chain_rows:
        for sw_l1 in chain_to_sw_l1.get(row.get("chain_id", ""), []):
            sw_l1_chain_rows[sw_l1].append(row)

    # 确定 as_of_date
    if chain_rows:
        as_of_date = max(str(r.get("as_of_date", "")) for r in chain_rows)
    else:
        as_of_date = date_str

    collected_at = datetime.now(timezone.utc).isoformat()
    results: list[dict] = []

    for sw_l1 in SW_L1_INDUSTRIES:
        rows = sw_l1_chain_rows.get(sw_l1, [])

        price_score = compute_price_score(rows)
        etf_info = etf_state.get(sw_l1, {})
        etf_score = etf_info.get("etf_score", 5.0)
        etf_count = etf_info.get("ef_count", 0)
        etf_symbol = etf_info.get("symbol") or etf_assets.get(sw_l1, {}).get("symbol")
        breadth_score = compute_breadth_score(sw_l1, breadth_map)

        # price_score 为 None 时取中性 5.0
        effective_price = price_score if price_score is not None else 5.0
        prosperity_score = round(
            max(0.0, min(10.0, 0.40 * effective_price + 0.35 * etf_score + 0.25 * breadth_score)), 2
        )

        rating = map_rating(prosperity_score)
        chain_position = derive_chain_position(sw_l1)
        chain_ids = derive_chain_ids(sw_l1)

        results.append(
            {
                "sw_l1": sw_l1,
                "chain_position": chain_position,
                "chain_ids": json.dumps(chain_ids, ensure_ascii=False) if chain_ids else None,
                "prosperity_score": prosperity_score,
                "prosperity_prev": None,
                "prosperity_change": None,
                "rating": rating,
                "rating_prev": None,
                "rating_change": None,
                "evidence_summary": f"price={price_score}, etf={etf_score}, breadth={breadth_score}",
                "upstream_score": None,
                "midstream_score": None,
                "downstream_score": None,
                "policy_support": None,
                "etf_symbol": etf_symbol,
                "etf_ef_count": etf_count,
                "dynamic_indicator_count": len(rows),
                "dynamic_event_count": 0,
                "source_vendor": "Hermass_Phase2",
                "as_of_date": as_of_date,
                "collected_at": collected_at,
                "_price_score": price_score,
                "_etf_score": etf_score,
                "_breadth_score": breadth_score,
            }
        )

    return results


# ── 数据库写入 ──────────────────────────────────────────


def write_industry_position(records: list[dict], db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS industry_position (
            sw_l1                VARCHAR    NOT NULL,
            chain_position       VARCHAR,
            chain_ids            VARCHAR,
            prosperity_score     DOUBLE,
            prosperity_prev      DOUBLE,
            prosperity_change    VARCHAR,
            rating               VARCHAR,
            rating_prev          VARCHAR,
            rating_change        VARCHAR,
            evidence_summary     VARCHAR,
            upstream_score       DOUBLE,
            midstream_score      DOUBLE,
            downstream_score     DOUBLE,
            policy_support       VARCHAR,
            etf_symbol           VARCHAR,
            etf_ef_count         INTEGER,
            dynamic_indicator_count INTEGER,
            dynamic_event_count  INTEGER,
            source_vendor        VARCHAR    DEFAULT 'Hermass_Phase2',
            as_of_date           VARCHAR    NOT NULL,
            collected_at         VARCHAR    NOT NULL,
            PRIMARY KEY (sw_l1, as_of_date)
        )
    """)

    for rec in records:
        con.execute(
            """
            INSERT OR REPLACE INTO industry_position (
                sw_l1, chain_position, chain_ids, prosperity_score,
                prosperity_prev, prosperity_change, rating, rating_prev,
                rating_change, evidence_summary, upstream_score, midstream_score,
                downstream_score, policy_support, etf_symbol, etf_ef_count,
                dynamic_indicator_count, dynamic_event_count, source_vendor,
                as_of_date, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                rec["sw_l1"],
                rec["chain_position"],
                rec["chain_ids"],
                rec["prosperity_score"],
                rec["prosperity_prev"],
                rec["prosperity_change"],
                rec["rating"],
                rec["rating_prev"],
                rec["rating_change"],
                rec["evidence_summary"],
                rec["upstream_score"],
                rec["midstream_score"],
                rec["downstream_score"],
                rec["policy_support"],
                rec["etf_symbol"],
                rec["etf_ef_count"],
                rec["dynamic_indicator_count"],
                rec["dynamic_event_count"],
                rec["source_vendor"],
                rec["as_of_date"],
                rec["collected_at"],
            ),
        )

    con.close()
    print(f"[OK] 写入 {len(records)} 条记录到 {db_path}")


# ── 报告生成 ──────────────────────────────────────────


def generate_report(records: list[dict], as_of_date: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"industry_position_report_{as_of_date.replace('-', '')}.md"

    sorted_records = sorted(records, key=lambda r: r["prosperity_score"] or -1, reverse=True)

    rating_dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for r in records:
        rating_dist[r["rating"]] = rating_dist.get(r["rating"], 0) + 1

    covered = [r for r in records if r["dynamic_indicator_count"] > 0]
    uncovered = [r for r in records if r["dynamic_indicator_count"] == 0]

    lines = [
        f"# 行业产业链景气度报告 ({as_of_date})",
        "",
        f"生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"数据日期: {as_of_date}",
        f"行业总数: {len(records)}",
        "",
        "## 1. 景气度排名",
        "",
        "| 排名 | 行业 | 产业链位置 | 景气度评分 | 评级 | 价格分 | ETF分 | 覆盖分 | 指标数 | ETF |",
        "|------|------|-----------|-----------|------|--------|-------|--------|--------|-----|",
    ]

    for i, r in enumerate(sorted_records, 1):
        ps = f"{r['_price_score']:.2f}" if r.get("_price_score") is not None else "-"
        es = f"{r['_etf_score']:.2f}" if r.get("_etf_score") is not None else "-"
        bs = f"{r['_breadth_score']:.2f}" if r.get("_breadth_score") is not None else "-"
        lines.append(
            f"| {i} | {r['sw_l1']} | {r['chain_position']} | "
            f"{r['prosperity_score'] if r['prosperity_score'] is not None else '-'} | "
            f"{r['rating']} | {ps} | {es} | {bs} | "
            f"{r['dynamic_indicator_count']} | {r['etf_symbol'] or '-'} |"
        )

    lines.extend(
        [
            "",
            "## 2. 评级分布",
            "",
            f"- **high** (景气): {rating_dist['high']} 个行业",
            f"- **medium** (中性): {rating_dist['medium']} 个行业",
            f"- **low** (低迷): {rating_dist['low']} 个行业",
            f"- **unknown** (未知): {rating_dist['unknown']} 个行业",
            "",
            "## 3. 数据覆盖情况",
            "",
            f"- **有产业链价格数据覆盖**: {len(covered)} 个行业",
            f"- **无产业链价格数据覆盖**: {len(uncovered)} 个行业",
            "",
        ]
    )

    if covered:
        lines.append("### 有数据覆盖的行业")
        lines.append("")
        for r in covered:
            lines.append(
                f"- {r['sw_l1']} ({r['chain_position']}) — 指标数: {r['dynamic_indicator_count']}, 评分: {r['prosperity_score']}"
            )
        lines.append("")

    if uncovered:
        lines.append("### 无数据覆盖的行业")
        lines.append("")
        for r in uncovered:
            lines.append(f"- {r['sw_l1']} ({r['chain_position']})")
        lines.append("")

    lines.extend(
        [
            "## 4. 评分方法说明",
            "",
            "```",
            "prosperity_score = 0.40 * price_score + 0.35 * etf_score + 0.25 * breadth_score",
            "```",
            "",
            "- **价格分**: chain_dynamics 期货价格数据的趋势(0-10)和分位数(0-10)加权，权重 60%/40%",
            "- **ETF分**: 行业 ETF 的 ef_count × 2.5 + 综合 state score 映射(0-2.5)",
            "- **覆盖分**: 该行业 EF 股票占比 × 100，上限 10 分（来自 state_ef_daily × ifind_profile）",
            "",
            "---",
            "*报告由 build_industry_position.py 自动生成*",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 报告已生成: {report_path}")
    return report_path


# ── CLI ───────────────────────────────────────────────


def infer_date() -> str:
    """从 chain_dynamics 推断最新可用日期，否则返回今天。"""
    try:
        con = duckdb.connect(str(CHAIN_DB_PATH), read_only=True)
        row = con.execute("SELECT MAX(as_of_date) FROM chain_dynamics").fetchone()
        con.close()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="产业链 Phase 2 — 行业景气度评分计算与写入")
    parser.add_argument("--date", default=None, help="基准日期 YYYY-MM-DD（默认自动推断）")
    parser.add_argument("--chain-db", default=str(CHAIN_DB_PATH), help="chain_dynamics DuckDB 路径")
    parser.add_argument("--output-db", default=str(INDUSTRY_CHAIN_DB), help="输出 DuckDB 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅计算不写入数据库")
    parser.add_argument("--skip-report", action="store_true", help="不生成 Markdown 报告")
    args = parser.parse_args()

    chain_db = Path(args.chain_db)
    output_db = Path(args.output_db)
    date_str = args.date if args.date else infer_date()

    print("=" * 60)
    print("产业链 Phase 2 — 行业景气度评分计算")
    print(f"日期: {date_str}")
    print("=" * 60)

    if not chain_db.exists():
        print(f"[ERROR] chain_dynamics.duckdb 不存在: {chain_db}")
        return 1

    records = build_industry_position(date_str, chain_db)
    as_of_date = records[0]["as_of_date"] if records else date_str

    if not args.dry_run:
        write_industry_position(records, output_db)
        # 同时写入 chain_dynamics.duckdb 保持兼容
        if output_db != chain_db:
            write_industry_position(records, chain_db)
    else:
        print(f"[DRY-RUN] 计算完成，共 {len(records)} 条记录，不写入数据库")

    if not args.skip_report:
        generate_report(records, as_of_date)

    print("=" * 60)
    print(f"Phase 2 完成 — {len(records)} 个行业")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
