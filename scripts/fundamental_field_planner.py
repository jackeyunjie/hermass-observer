#!/usr/bin/env python3
"""DeepSeek Field Planner — 只输出字段计划，不输出分析结论。

用法：
  python3 scripts/fundamental_field_planner.py --date 2026-05-21

输出：
  outputs/fundamental/fundamental_field_plan_YYYYMMDD.json
  outputs/fundamental/fundamental_field_plan_latest.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deepseek_context import with_deepseek_context

SYSTEM_PROMPT = """你是一个 A 股基本面数据字段规划师。

你的唯一任务是：给定一个分析目标，列出需要从 iFind（同花顺 iFinD）获取哪些数据字段。

你绝对不能：
- 给出任何公司的分析结论
- 做行业判断、推荐股票
- 使用你的训练数据中的事实信息

你必须：
- 只输出字段计划 JSON
- 每个字段标注来源、查询提示、更新频率、过期阈值、校验规则

iFind 可用 API：
- THS_BD：股票基本资料 + 财务指标 + 预测 + 并购重组
- THS_ReportQuery：公告查询（定增、重组、增发、年报）
- THS_WCQuery：智能选股问句查询（如 "同行业营收排名"）

分析目标：
1. 行业链周期定位 — 行业处于哪个发展阶段
2. 公司地位 — 公司在行业内的竞争位次
3. 公司发展周期 — 公司自身的成长阶段
4. 定增影响 — 定增的折价、用途、参与方
5. 驱动因子 — 当前推动股价的核心因素
"""

FIELD_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string", "enum": ["company_position", "industry_chain", "development_cycle", "capital_events", "driving_factors"]},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field_name": {"type": "string"},
                                "source_api": {"type": "string", "enum": ["THS_BD", "THS_ReportQuery", "THS_WCQuery"]},
                                "source_query_hint": {"type": "string"},
                                "reason": {"type": "string"},
                                "update_frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "quarterly", "annual"]},
                                "stale_after_days": {"type": "integer", "minimum": 30, "maximum": 730},
                                "validation_rule": {"type": "string"}
                            },
                            "required": ["field_name", "source_api", "source_query_hint", "reason", "update_frequency", "stale_after_days", "validation_rule"]
                        }
                    }
                },
                "required": ["dimension", "fields"]
            }
        }
    },
    "required": ["dimensions"]
}


DIMENSION_NAMES = {"company_position", "industry_chain", "development_cycle", "capital_events", "driving_factors"}


def _stale_days(value: object) -> int:
    text = str(value or "").strip().lower()
    if not text or text in {"none", "null", "无"}:
        return 180
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return max(30, min(730, int(digits)))
    return 180


def _frequency(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "日": "daily",
        "每日": "daily",
        "daily": "daily",
        "周": "weekly",
        "每周": "weekly",
        "weekly": "weekly",
        "月": "monthly",
        "每月": "monthly",
        "monthly": "monthly",
        "季": "quarterly",
        "季度": "quarterly",
        "quarterly": "quarterly",
        "年": "annual",
        "年度": "annual",
        "annual": "annual",
        "事件": "weekly",
        "事件驱动": "weekly",
    }
    for key, out in mapping.items():
        if key in text:
            return out
    return "quarterly"


def _source_api(value: object) -> str:
    text = str(value or "").strip()
    allowed = {"THS_BD", "THS_ReportQuery", "THS_WCQuery"}
    return text if text in allowed else "THS_BD"


def normalize_plan(raw: dict, date_str: str, source: str) -> dict:
    """Normalize DeepSeek's JSON into the strict project field-plan shape."""
    dimensions: list[dict] = []

    if isinstance(raw.get("dimensions"), list):
        candidates = raw["dimensions"]
    else:
        candidates = [
            {"dimension": key, "fields": value.get("fields", [])}
            for key, value in raw.items()
            if key in DIMENSION_NAMES and isinstance(value, dict)
        ]

    for dim in candidates:
        name = dim.get("dimension")
        if name not in DIMENSION_NAMES:
            continue
        fields = []
        for field in dim.get("fields", []):
            if not isinstance(field, dict):
                continue
            field_name = field.get("field_name") or field.get("name")
            if not field_name:
                continue
            fields.append(
                {
                    "field_name": str(field_name),
                    "source_api": _source_api(field.get("source_api") or field.get("source")),
                    "source_query_hint": str(field.get("source_query_hint") or field.get("query_hint") or ""),
                    "reason": str(field.get("reason") or "DeepSeek field planner proposed this field."),
                    "update_frequency": _frequency(field.get("update_frequency")),
                    "stale_after_days": _stale_days(field.get("stale_after_days") or field.get("expiry_threshold")),
                    "validation_rule": str(field.get("validation_rule") or "value should be present and type-valid"),
                }
            )
        if fields:
            dimensions.append({"dimension": name, "fields": fields})

    if not dimensions:
        fallback = _baseline_plan(date_str)
        fallback["source"] = f"{source}_invalid_fallback"
        return fallback

    return {
        "schema_version": "fundamental_field_plan_v1",
        "as_of_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "dimensions": dimensions,
    }


def call_deepseek(prompt: str, api_key: str, api_base: str) -> dict:
    url = f"{api_base}/v1/chat/completions"
    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": with_deepseek_context(SYSTEM_PROMPT)},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"}
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return json.loads(result["choices"][0]["message"]["content"])


def generate_plan(date_str: str) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    if not api_key:
        print("Warning: DEEPSEEK_API_KEY not set. Using hardcoded baseline plan.", file=sys.stderr)
        return _baseline_plan(date_str)

    prompt = f"""当前日期：{date_str}。

请基于上述分析目标和 iFind API 能力，输出一个字段计划 JSON。

要求：
1. 至少覆盖 5 个维度：company_position、industry_chain、development_cycle、capital_events、driving_factors
2. 每个维度至少 3 个字段
3. 每个字段必须有 source_query_hint（模糊查询提示，如"SW二级行业营收排名前20"）
4. validation_rule 必须是可程序化校验的规则（如"rank must be integer and peer_count >= 5"）
5. 只返回 JSON，不要任何其他文字"""

    print(f"Calling DeepSeek field planner via {api_base}...", flush=True)
    plan = call_deepseek(prompt, api_key, api_base)
    return normalize_plan(plan, date_str, "deepseek-chat")


def _baseline_plan(date_str: str) -> dict:
    return {
        "schema_version": "fundamental_field_plan_v1",
        "as_of_date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "hardcoded_baseline",
        "dimensions": [
            {
                "dimension": "company_position",
                "fields": [
                    {"field_name": "revenue_rank_in_sw_l2", "source_api": "THS_WCQuery", "source_query_hint": "SW二级行业营收排名 top 30", "reason": "竞争位次需要同行业可比营收排位", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "rank integer, peer_count >= 5"},
                    {"field_name": "gross_margin_vs_industry_median", "source_api": "THS_BD", "source_query_hint": "ths_gross_profit_margin_ttm vs industry median", "reason": "毛利率是否高于行业中位数反映定价权", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "gross_margin > 0, industry_median must exist"},
                    {"field_name": "market_cap_rank_in_industry", "source_api": "THS_WCQuery", "source_query_hint": "SW二级行业总市值排名", "reason": "市值排位反映市场对公司的定价", "update_frequency": "daily", "stale_after_days": 7, "validation_rule": "rank integer, total > 0"}
                ]
            },
            {
                "dimension": "industry_chain",
                "fields": [
                    {"field_name": "industry_revenue_growth_3y", "source_api": "THS_WCQuery", "source_query_hint": "SW二级行业近3年营收复合增速", "reason": "行业营收增速方向判断产业链周期", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "growth_rate numeric, should not be null"},
                    {"field_name": "industry_pe_median", "source_api": "THS_WCQuery", "source_query_hint": "SW二级行业PE中位数", "reason": "行业估值水平辅助周期判断", "update_frequency": "daily", "stale_after_days": 30, "validation_rule": "pe > 0"},
                    {"field_name": "industry_rd_expense_ratio", "source_api": "THS_WCQuery", "source_query_hint": "SW二级行业研发费用率均值", "reason": "研发强度反映行业技术阶段", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "ratio between 0 and 1"}
                ]
            },
            {
                "dimension": "development_cycle",
                "fields": [
                    {"field_name": "revenue_cagr_3y", "source_api": "THS_BD", "source_query_hint": "ths_revenue_ttm_3y_cagr", "reason": "营收3年复合增速判断公司发展阶段", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "cagr numeric, not null"},
                    {"field_name": "roe_trend_3y", "source_api": "THS_BD", "source_query_hint": "ths_roe_ttm last 3 years", "reason": "ROE趋势反映盈利能力变化", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "roe values for each year must exist"},
                    {"field_name": "capex_to_revenue", "source_api": "THS_BD", "source_query_hint": "ths_capital_expenditure / ths_revenue_ttm", "reason": "资本开支占比反映扩张意愿", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "ratio >= 0"}
                ]
            },
            {
                "dimension": "capital_events",
                "fields": [
                    {"field_name": "placement_history_3y", "source_api": "THS_ReportQuery", "source_query_hint": "近3年定增公告", "reason": "定增历史分析折价和用途", "update_frequency": "annual", "stale_after_days": 180, "validation_rule": "event_date and placement_price must exist if records found"},
                    {"field_name": "major_shareholder_participation", "source_api": "THS_ReportQuery", "source_query_hint": "大股东参与定增情况", "reason": "大股东参与度反映信心", "update_frequency": "annual", "stale_after_days": 180, "validation_rule": "text not empty if placement found"},
                    {"field_name": "lockup_expiry_date", "source_api": "THS_ReportQuery", "source_query_hint": "定增解禁日期", "reason": "解禁日期影响短期供给压力", "update_frequency": "annual", "stale_after_days": 180, "validation_rule": "date format YYYY-MM-DD"}
                ]
            },
            {
                "dimension": "driving_factors",
                "fields": [
                    {"field_name": "main_business_composition", "source_api": "THS_BD", "source_query_hint": "ths_business_segment_revenue", "reason": "主营业务构成判断核心驱动力", "update_frequency": "quarterly", "stale_after_days": 210, "validation_rule": "at least 2 segments listed"},
                    {"field_name": "new_product_pipeline", "source_api": "THS_ReportQuery", "source_query_hint": "新产品线/产能扩张公告", "reason": "新产品/产能是未来驱动因子", "update_frequency": "quarterly", "stale_after_days": 180, "validation_rule": "text not empty if found"},
                    {"field_name": "institutional_ownership_change", "source_api": "THS_BD", "source_query_hint": "ths_institutional_holding_ratio quarterly change", "reason": "机构持仓变化反映专业资金态度", "update_frequency": "quarterly", "stale_after_days": 120, "validation_rule": "ratio between 0 and 100"}
                ]
            }
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek Field Planner")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    plan = generate_plan(args.date)
    date_ymd = args.date.replace("-", "")

    out_dir = ROOT / "outputs" / "fundamental"
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_path = out_dir / f"fundamental_field_plan_{date_ymd}.json"
    latest_path = out_dir / "fundamental_field_plan_latest.json"

    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
    plan_path.write_text(plan_json, encoding="utf-8")
    latest_path.write_text(plan_json, encoding="utf-8")

    print(f"Field plan written to {plan_path}")
    total_fields = sum(len(d["fields"]) for d in plan.get("dimensions", []))
    print(f"Dimensions: {len(plan.get('dimensions', []))} / Fields: {total_fields}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
