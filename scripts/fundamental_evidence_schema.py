#!/usr/bin/env python3
"""Fundamental evidence schema — DuckDB 建表。

四张核心表 + 一张审核队列表，存入 outputs/fundamental/fundamental_evidence.duckdb：
  - ifind_financial_metrics     财务指标
  - ifind_capital_events         资本事件
  - fundamental_evidence_packet  证据包
  - fundamental_profile          基本面画像
  - fundamental_review_queue     待人工审核
  - stock_research_ledger        单股研究账本
  - ifind_tracking_pool          iFinD 本地基本面跟踪池
  - ifind_excel_facts            iFinD GUI Excel 下载事实层
  - ifind_industry_chain_profile iFinD 产业链/主营业务身份层
  - ifind_business_segment_facts iFinD 主营构成数值事实层

用法：
  python3 scripts/fundamental_evidence_schema.py
"""

from __future__ import annotations

import duckdb
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "fundamental_evidence_v1"

CREATE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ifind_financial_metrics (
        stock_code       VARCHAR    NOT NULL,
        report_period    VARCHAR    NOT NULL,
        report_type      VARCHAR,
        pe_ttm           DOUBLE,
        pb               DOUBLE,
        roe              DOUBLE,
        gross_margin     DOUBLE,
        revenue_yoy      DOUBLE,
        net_profit_yoy   DOUBLE,
        operating_cashflow DOUBLE,
        debt_ratio       DOUBLE,
        source_vendor    VARCHAR    DEFAULT 'iFind',
        source_query     VARCHAR,
        source_api       VARCHAR,
        collected_at     VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, report_period)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_tracking_pool (
        stock_code          VARCHAR    PRIMARY KEY,
        stock_name          VARCHAR,
        sw_l1               VARCHAR,
        sw_l2               VARCHAR,
        sw_l3               VARCHAR,
        source_pool         VARCHAR,
        first_added         VARCHAR    NOT NULL,
        last_seen           VARCHAR    NOT NULL,
        priority_tier       VARCHAR    DEFAULT 'watch',
        refresh_frequency   VARCHAR    DEFAULT 'weekly',
        last_fundamental_refresh VARCHAR,
        last_analysis_refresh VARCHAR,
        active              BOOLEAN    DEFAULT TRUE,
        notes               VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_derived_metrics (
        stock_code        VARCHAR    NOT NULL,
        as_of_date        VARCHAR    NOT NULL,
        revenue_rank_sw_l2      INTEGER,
        revenue_rank_pct        DOUBLE,
        gross_margin_rank_pct   DOUBLE,
        roe_rank_pct            DOUBLE,
        rd_ratio_rank_pct       DOUBLE,
        market_cap_rank_pct     DOUBLE,
        revenue_cagr_3y         DOUBLE,
        roe_trend_direction     VARCHAR,
        gross_margin_trend      VARCHAR,
        cashflow_trend          VARCHAR,
        debt_ratio              DOUBLE,
        peer_count              INTEGER,
        computed_at             VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_macro_indicators (
        indicator_code   VARCHAR    NOT NULL,
        as_of_date       VARCHAR    NOT NULL,
        indicator_name   VARCHAR,
        value            DOUBLE,
        unit             VARCHAR,
        frequency        VARCHAR,
        source_query     VARCHAR,
        source_api       VARCHAR    DEFAULT 'THS_EDB',
        collected_at     VARCHAR    NOT NULL,
        PRIMARY KEY (indicator_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_capital_events (
        stock_code          VARCHAR    NOT NULL,
        event_date          VARCHAR    NOT NULL,
        event_type          VARCHAR,
        event_status        VARCHAR,
        placement_price     DOUBLE,
        discount_rate       DOUBLE,
        fundraising_amount  DOUBLE,
        use_of_proceeds     VARCHAR,
        lockup_months       INTEGER,
        participant_summary VARCHAR,
        source_vendor       VARCHAR    DEFAULT 'iFind',
        source_query        VARCHAR,
        source_api          VARCHAR,
        collected_at        VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, event_date, event_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_excel_facts (
        stock_code       VARCHAR    NOT NULL,
        stock_name       VARCHAR,
        as_of_date       VARCHAR    NOT NULL,
        statement_type   VARCHAR,
        metric_name      VARCHAR    NOT NULL,
        metric_value     DOUBLE,
        report_period    VARCHAR,
        report_type      VARCHAR,
        unit             VARCHAR,
        source_file      VARCHAR,
        collected_at     VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date, metric_name, report_period, source_file)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_industry_chain_profile (
        stock_code          VARCHAR    NOT NULL,
        stock_name          VARCHAR,
        as_of_date          VARCHAR    NOT NULL,
        sw_l1               VARCHAR,
        sw_l2               VARCHAR,
        sw_l3               VARCHAR,
        ths_concepts        VARCHAR,
        main_business       VARCHAR,
        business_scope      VARCHAR,
        comparable_companies VARCHAR,
        competitor_companies VARCHAR,
        main_product_types  VARCHAR,
        main_product_names  VARCHAR,
        source_file         VARCHAR,
        collected_at        VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ifind_business_segment_facts (
        stock_code       VARCHAR    NOT NULL,
        stock_name       VARCHAR,
        as_of_date       VARCHAR    NOT NULL,
        metric_name      VARCHAR    NOT NULL,
        metric_value     DOUBLE,
        report_period    VARCHAR,
        segment_basis    VARCHAR,
        rank_label       VARCHAR,
        unit             VARCHAR,
        source_file      VARCHAR,
        collected_at     VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date, metric_name, report_period, segment_basis, rank_label, source_file)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamental_evidence_packet (
        evidence_id      VARCHAR    PRIMARY KEY,
        stock_code       VARCHAR    NOT NULL,
        as_of_date       VARCHAR    NOT NULL,
        evidence_type    VARCHAR    NOT NULL,
        evidence_text    VARCHAR,
        source_vendor    VARCHAR    DEFAULT 'iFind',
        source_query     VARCHAR,
        source_api       VARCHAR,
        source_period    VARCHAR,
        confidence       DOUBLE,
        collected_at     VARCHAR    NOT NULL,
        unmapped         BOOLEAN    DEFAULT FALSE,
        unavailable      BOOLEAN    DEFAULT FALSE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamental_quality_score (
        stock_code              VARCHAR    NOT NULL,
        as_of_date              VARCHAR    NOT NULL,
        stock_name              VARCHAR,
        
        core_business_purity    DOUBLE,    -- 经营活动净收益/利润总额
        cash_quality            DOUBLE,    -- 经营活动现金流/净利润
        earnings_quality        DOUBLE,    -- 扣非净利润/净利润
        asset_safety_ratio      DOUBLE,    -- 1 - 资产负债率
        
        quality_score           DOUBLE,    -- 综合质量得分 (0-100)
        final_fundamental_score DOUBLE,    -- 最终基本面总分 (0-100)
        
        computed_at             VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamental_profile (
        stock_code              VARCHAR    NOT NULL,
        as_of_date              VARCHAR    NOT NULL,
        industry_chain          VARCHAR    DEFAULT 'unknown',
        chain_position          VARCHAR    DEFAULT 'unknown',
        company_position        VARCHAR    DEFAULT 'unknown',
        development_cycle       VARCHAR    DEFAULT 'unknown',
        placement_assessment    VARCHAR    DEFAULT 'unknown',
        primary_drivers_json    VARCHAR,
        risk_factors_json       VARCHAR,
        evidence_ids_json       VARCHAR,
        llm_model               VARCHAR,
        llm_confidence          DOUBLE,
        analyst_pass            BOOLEAN,
        rating_agency_pass      BOOLEAN,
        cross_validated         BOOLEAN    DEFAULT FALSE,
        generated_at            VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundamental_review_queue (
        stock_code       VARCHAR    NOT NULL,
        as_of_date       VARCHAR    NOT NULL,
        conflict_type    VARCHAR    NOT NULL,
        analyst_result   VARCHAR,
        rating_agency_result VARCHAR,
        conflict_detail  VARCHAR,
        created_at       VARCHAR    NOT NULL,
        reviewed         BOOLEAN    DEFAULT FALSE,
        PRIMARY KEY (stock_code, as_of_date, conflict_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_research_ledger (
        stock_code              VARCHAR    NOT NULL,
        as_of_date              VARCHAR    NOT NULL,
        stock_name              VARCHAR,
        sw_l1                   VARCHAR,
        sw_l2                   VARCHAR,
        sw_l3                   VARCHAR,
        ledger_status           VARCHAR    DEFAULT 'active',
        technical_snapshot_json VARCHAR,
        pattern_snapshot_json   VARCHAR,
        fundamental_snapshot_json VARCHAR,
        event_digest_json       VARCHAR,
        chief_insight           VARCHAR,
        bull_case               VARCHAR,
        bear_case               VARCHAR,
        watch_points_json       VARCHAR,
        evidence_ids_json       VARCHAR,
        confidence              DOUBLE,
        generated_at            VARCHAR    NOT NULL,
        PRIMARY KEY (stock_code, as_of_date)
    )
    """,
]


def get_db_path() -> Path:
    out_dir = ROOT / "outputs" / "fundamental"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "fundamental_evidence.duckdb"


def init_schema(db_path: Path | None = None) -> Path:
    db_path = db_path or get_db_path()
    con = duckdb.connect(str(db_path))
    for stmt in CREATE_STATEMENTS:
        con.execute(stmt)
    con.execute(
        "CREATE TABLE IF NOT EXISTS schema_info (schema_version VARCHAR, created_at VARCHAR)"
    )
    con.execute("DELETE FROM schema_info")
    con.execute(
        "INSERT INTO schema_info VALUES (?, ?)",
        (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
    )
    con.close()
    return db_path


if __name__ == "__main__":
    p = init_schema()
    print(f"Fundamental evidence schema: {p}")
    print(f"Tables: financial_metrics, capital_events, evidence_packet, fundamental_profile, review_queue")
