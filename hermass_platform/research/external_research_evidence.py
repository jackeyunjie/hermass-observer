from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from hermass_platform.agents.base_agent import find_foundation_db

ROOT = Path(__file__).resolve().parents[2]
FUNDAMENTAL_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
SIGNAL_DB = ROOT / "outputs" / "strategy_signals" / "strategy_signals.duckdb"

REQUIRED_MODULES = {
    "company_profile": 0.15,
    "financial_trend": 0.30,
    "industry_state": 0.15,
    "state_core": 0.30,
    "risk_flags": 0.10,
}

OPTIONAL_MODULES = {
    "valuation_reference": 0.50,
    "market_views": 0.50,
}

STATUS_SCORE = {
    "sufficient": 1.0,
    "partial": 0.5,
    "missing": 0.0,
}

SOURCE_TIER_BY_TYPE = {
    "foundation": "tier_1_core",
    "ifind": "tier_2_high",
    "akshare": "tier_2_high",
    "derived": "tier_derived",
    "manual": "tier_3_general",
}

SOURCE_POLICY = {
    "tier_definitions": {
        "tier_1_core": "监管机构、交易所、上市公司公告或系统状态底座等核心可信来源",
        "tier_2_high": "iFinD、AKShare、巨潮等结构化数据源",
        "tier_3_general": "一般公开资料，仅作补充说明",
        "tier_derived": "基于结构化数据按规则派生生成",
    },
    "banned_source_patterns": [
        "guba",
        "股吧",
        "自媒体",
        "营销号",
        "论坛",
        "个人博客",
        "weibo",
        "zhihu",
        "网友称",
        "据传",
        "爆料",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digits_only(stock_code: str) -> str:
    return "".join(ch for ch in stock_code.split(".", 1)[0] if ch.isdigit())


def _canonical_stock_code(stock_code: str, con: duckdb.DuckDBPyConnection | None = None) -> str:
    if "." in stock_code:
        return stock_code.upper()
    digits = _digits_only(stock_code)
    if con is not None:
        row = con.execute(
            """
            SELECT stock_code
            FROM ifind_tracking_pool
            WHERE split_part(stock_code, '.', 1) = ?
            ORDER BY stock_code
            LIMIT 1
            """,
            [digits],
        ).fetchone()
        if row:
            return str(row[0]).upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _resolve_foundation_db(as_of_date: str, foundation_db: str | Path | None) -> Path:
    if foundation_db:
        return Path(foundation_db)
    path = find_foundation_db(as_of_date)
    if not path:
        raise FileNotFoundError(f"No foundation DB available for date={as_of_date}")
    return path


def _open_readonly(path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)


def _parse_period_label(label: str) -> tuple[int, str]:
    text = str(label or "")
    year = 0
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 4:
        year = int(digits[:4])
    if "年报" in text:
        return year * 10 + 4, f"{year}Q4"
    if "一季" in text:
        return year * 10 + 1, f"{year}Q1"
    if "中报" in text or "半年" in text:
        return year * 10 + 2, f"{year}Q2"
    if "三季" in text:
        return year * 10 + 3, f"{year}Q3"
    return year * 10, text or "unknown"


def _period_quarter(label: str) -> str:
    text = str(label or "")
    if text.endswith("Q1"):
        return "Q1"
    if text.endswith("Q2"):
        return "Q2"
    if text.endswith("Q3"):
        return "Q3"
    if text.endswith("Q4"):
        return "Q4"
    return ""


def _industry_keyword_text(company_profile: dict[str, Any]) -> str:
    return " ".join(
        [
            str(company_profile.get("sw_l1") or ""),
            str(company_profile.get("sw_l2") or ""),
            str(company_profile.get("sw_l3") or ""),
            str(company_profile.get("main_business") or ""),
            str(company_profile.get("main_product_types") or ""),
        ]
    )


def _metric_importance(company_profile: dict[str, Any], metric: str) -> tuple[bool, str]:
    text = _industry_keyword_text(company_profile)
    bank_like = any(token in text for token in ["银行", "保险", "证券", "多元金融"])
    light_asset_chip = any(token in text for token in ["半导体", "芯片", "集成电路", "软件", "SaaS"])
    heavy_asset = any(token in text for token in ["电力", "公用事业", "地产", "建筑", "钢铁", "化工", "机械", "制造"])

    if metric == "revenue":
        return True, "营收同比通常直接反映需求、订单和出货节奏变化。"
    if metric == "net_profit":
        return True, "净利润同比通常直接反映盈利兑现和经营弹性变化。"
    if metric == "operating_cashflow":
        if bank_like:
            return False, "金融行业经营现金流口径可比性弱，默认不作为前台核心风险提示。"
        if heavy_asset or not light_asset_chip:
            return True, "经营现金流同比对制造、周期和重资产行业的经营质量判断更关键。"
        return False, "对轻资产或器件设计类行业，经营现金流短期波动不总是前台关键信息。"
    if metric == "debt_ratio":
        if bank_like:
            return False, "金融行业杠杆口径特殊，资产负债率不适合作为统一前台风险提示。"
        if heavy_asset:
            return True, "资产负债率对重资产行业的偿债压力和扩张约束更关键。"
        return False, "对轻资产行业，资产负债率通常不是第一优先级风险提示。"
    return True, ""


def _risk_item(risk: str, significance: str = "中", reason: str = "") -> dict[str, Any]:
    return {
        "risk": risk,
        "significance": significance,
        "reason": reason,
    }


def _compute_same_quarter_series(
    period_rows: list[dict[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, current_row in enumerate(period_rows):
        current_val = current_row.get(field)
        current_quarter = _period_quarter(current_row.get("report_period"))
        if current_val in (None, 0) or not current_quarter:
            continue
        for jdx in range(idx + 1, len(period_rows)):
            compare_row = period_rows[jdx]
            if _period_quarter(compare_row.get("report_period")) != current_quarter:
                continue
            previous_same_quarter = compare_row.get(field)
            if previous_same_quarter not in (None, 0):
                yoy_val = (float(current_val) / float(previous_same_quarter) - 1) * 100
                out.append(
                    {
                        "report_period": current_row["report_period"],
                        "base_period": compare_row["report_period"],
                        "value": round(yoy_val, 2),
                    }
                )
            break
    return out


def _find_latest_file(directory: Path, prefix: str, suffix: str, as_of_date: str) -> Path | None:
    cutoff = as_of_date.replace("-", "")
    candidates: list[tuple[str, Path]] = []
    for path in directory.glob(f"{prefix}_*{suffix}"):
        tail = path.stem.split("_")[-1]
        if len(tail) == 8 and tail.isdigit() and tail <= cutoff:
            candidates.append((tail, path))
    if not candidates:
        for path in directory.glob(f"{prefix}_*{suffix}"):
            tail = path.stem.split("_")[-1]
            if len(tail) == 8 and tail.isdigit():
                candidates.append((tail, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _json_load(path: Path | None) -> Any:
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_reminder_path(as_of_date: str) -> Path | None:
    directory = ROOT / "outputs" / "strategy_reminders"
    if not directory.exists():
        return None
    cutoff = as_of_date.replace("-", "")
    candidates: list[tuple[str, Path]] = []
    for path in directory.glob("reminder_*.json"):
        tail = path.stem.split("_")[-1]
        if len(tail) == 8 and tail.isdigit() and tail <= cutoff:
            candidates.append((tail, path))
    if not candidates:
        for path in directory.glob("reminder_*.json"):
            tail = path.stem.split("_")[-1]
            if len(tail) == 8 and tail.isdigit():
                candidates.append((tail, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _source_entry(
    source_type: str,
    source_table: str | None,
    source_field: str | None,
    updated_at: str,
    report_period: str | None = None,
    source_confidence: float = 0.95,
    derivation: str | None = None,
) -> dict[str, Any]:
    entry = {
        "source_type": source_type,
        "source_tier": SOURCE_TIER_BY_TYPE.get(source_type, "tier_3_general"),
        "source_table": source_table,
        "source_field": source_field,
        "report_period": report_period,
        "updated_at": updated_at,
        "source_confidence": source_confidence,
    }
    if derivation:
        entry["derivation"] = derivation
    return entry


def _classify_market_phase(row: dict[str, Any]) -> str:
    ef_count = int(row.get("ef_count") or 0)
    d1_trend = str(row.get("d1_trend") or "")
    if ef_count >= 3:
        return "progression"
    if ef_count == 2:
        return "constructive"
    if ef_count == 1 and d1_trend.startswith("bull"):
        return "emerging"
    if d1_trend == "bull_trend":
        return "watchlist_bull"
    return "transition"


def _state_duration_label(days: Any) -> str:
    if not isinstance(days, (int, float)):
        return "未知"
    if days <= 3:
        return "刚形成"
    if days <= 10:
        return "延续初段"
    if days <= 30:
        return "持续推进"
    return "长周期延续"


def _state_prior_view(state_core: dict[str, Any], duration: dict[str, Any]) -> str:
    mn1_days = duration.get("mn1_ef_duration")
    w1_days = duration.get("w1_ef_duration")
    d1_days = duration.get("d1_ef_duration")
    all_days = duration.get("all_three_ef_duration")
    ef_count = state_core.get("ef_count")
    d1_state = str(state_core.get("d1_state_hex") or "")
    w1_state = str(state_core.get("w1_state_hex") or "")
    mn1_state = str(state_core.get("mn1_state_hex") or "")

    if ef_count == 3:
        if isinstance(all_days, (int, float)) and all_days <= 3:
            return "三周期共振刚形成，先验上更偏向观察共振能否延续，而不是直接外推强度。"
        if d1_state == "F":
            return "大周期保持扩张趋势，D1 处于突破后的活跃推进段，先验上更容易先出现短周期节奏切换。"
        return "三周期共振处于延续状态，先验上重点观察 D1 是否维持推进以及 W1 是否继续支撑。"
    if ef_count == 2:
        if d1_state not in {"E", "F"} and (mn1_state in {"E", "F"} or w1_state in {"E", "F"}):
            return "大周期或中周期已有支撑，但短周期尚未补齐，先验上更关注 D1 是否转入 E/F。"
        return "双周期共振已经出现，先验上需要观察缺失周期是否跟随。"
    if ef_count == 1:
        return "当前只有单周期进入 E/F，先验上仍属于局部结构，需等待更多周期确认。"
    return "当前未形成 E/F 共振，先验上以观察结构是否重新扩张为主。"


def _next_state_change_hint(state_core: dict[str, Any], duration: dict[str, Any]) -> str:
    mn1_days = duration.get("mn1_ef_duration")
    w1_days = duration.get("w1_ef_duration")
    d1_days = duration.get("d1_ef_duration")
    ef_count = state_core.get("ef_count")
    d1_state = str(state_core.get("d1_state_hex") or "")
    w1_state = str(state_core.get("w1_state_hex") or "")
    mn1_state = str(state_core.get("mn1_state_hex") or "")

    if d1_state in {"F", "E"} and isinstance(d1_days, (int, float)) and d1_days <= 3:
        return "短周期 D1 刚进入强状态不久，最可能先变化的仍是 D1。"
    if ef_count == 3 and isinstance(d1_days, (int, float)) and isinstance(w1_days, (int, float)) and d1_days < w1_days:
        return "三周期共振已形成，但最短的是 D1 持续段，后续若有变化通常先从 D1 开始。"
    if ef_count == 2 and d1_state not in {"E", "F"} and w1_state in {"E", "F"}:
        return "中周期已保持强势，短周期 D1 仍在确认，下一步最值得观察的是 D1 是否补齐。"
    if ef_count == 1 and mn1_state in {"E", "F"}:
        return "当前更多是大级别背景支撑，下一步最值得观察的是 W1 / D1 是否跟随增强。"
    if isinstance(mn1_days, (int, float)) and isinstance(w1_days, (int, float)) and isinstance(d1_days, (int, float)):
        min_cycle = min(
            [("MN1", mn1_days), ("W1", w1_days), ("D1", d1_days)],
            key=lambda item: item[1],
        )[0]
        return f"当前最短的强状态持续段在 {min_cycle}，后续结构变化通常先从这一周期体现。"
    return "当前结构仍以 D1 与 W1 的同步强化情况最值得跟踪。"


def _compute_state_duration_from_foundation(
    foundation_con: duckdb.DuckDBPyConnection,
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    duration = {
        "mn1_ef_duration": None,
        "w1_ef_duration": None,
        "d1_ef_duration": None,
        "all_three_ef_duration": None,
    }
    source_map: dict[str, Any] = {}
    rows = foundation_con.execute(
        """
        SELECT state_date, mn1_state_hex, w1_state_hex, d1_state_hex, ef_count
        FROM d1_perspective_state
        WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
          AND state_date <= CAST(? AS DATE)
        ORDER BY state_date DESC
        LIMIT 260
        """,
        [stock_code, _digits_only(stock_code), as_of_date],
    ).fetchall()
    if not rows:
        return duration, source_map, {"snapshot_date": None}
    latest = rows[0]
    snapshot_date = str(latest[0])
    checks = {
        "mn1_ef_duration": lambda row: str(row[1] or "") in {"E", "F"},
        "w1_ef_duration": lambda row: str(row[2] or "") in {"E", "F"},
        "d1_ef_duration": lambda row: str(row[3] or "") in {"E", "F"},
        "all_three_ef_duration": lambda row: int(row[4] or 0) == 3,
    }
    for field, predicate in checks.items():
        count = 0
        for row in rows:
            if not predicate(row):
                break
            count += 1
        duration[field] = count if count > 0 else 0
        source_map[f"state_core.{field}"] = _source_entry(
            "derived",
            "d1_perspective_state",
            field,
            snapshot_date,
            source_confidence=0.95,
            derivation="continuous trading-day count while state remains E/F or ef_count=3",
        )
    return duration, source_map, {"snapshot_date": snapshot_date}


def _load_state_duration(
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    duration = {
        "mn1_ef_duration": None,
        "w1_ef_duration": None,
        "d1_ef_duration": None,
        "all_three_ef_duration": None,
    }
    source_map: dict[str, Any] = {}
    meta = {"snapshot_date": None}
    reminder_path = _latest_reminder_path(as_of_date)
    payload = _json_load(reminder_path)
    if not isinstance(payload, dict):
        return duration, source_map, meta
    reminders = payload.get("reminders") or []
    canonical = _canonical_stock_code(stock_code)
    digits = _digits_only(stock_code)
    matched = None
    for item in reminders:
        code = str(item.get("stock_code") or "").upper()
        code6 = str(item.get("stock_code_6") or "")
        if code == canonical or code6 == digits:
            matched = item
            break
    if not matched:
        return duration, source_map, meta
    state_duration = matched.get("state_duration") or {}
    snapshot_date = str(payload.get("date") or "")
    for field in duration:
        if state_duration.get(field) is not None:
            duration[field] = state_duration.get(field)
            source_map[f"state_core.{field}"] = _source_entry(
                "derived",
                "strategy_reminders",
                field,
                snapshot_date or _utc_now(),
                source_confidence=0.9,
                derivation="state_duration carried from reminder state context",
            )
    meta["snapshot_date"] = snapshot_date or None
    return duration, source_map, meta


def _is_seasonal_industry(company_profile: dict[str, Any]) -> bool:
    sw_l1 = str(company_profile.get("sw_l1") or "")
    sw_l2 = str(company_profile.get("sw_l2") or "")
    main_business = str(company_profile.get("main_business") or "")
    seasonal_tokens = [
        "银行",
        "白酒",
        "食品饮料",
        "零售",
        "商贸零售",
    ]
    haystack = f"{sw_l1} {sw_l2} {main_business}"
    return any(token in haystack for token in seasonal_tokens)


def _load_company_profile(
    con: duckdb.DuckDBPyConnection,
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row = con.execute(
        """
        SELECT stock_code, stock_name, as_of_date, sw_l1, sw_l2, sw_l3, ths_concepts,
               main_business, comparable_companies, competitor_companies,
               main_product_types, main_product_names, collected_at
        FROM ifind_industry_chain_profile
        WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
          AND as_of_date <= ?
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        [stock_code, _digits_only(stock_code), as_of_date],
    ).fetchone()
    profile = {
        "stock_code": stock_code,
        "stock_name": "",
        "sw_l1": "",
        "sw_l2": "",
        "sw_l3": "",
        "main_business": "",
        "main_product_types": "",
        "main_product_names": "",
        "comparable_companies": "",
        "competitor_companies": "",
        "ths_concepts": "",
    }
    source_map: dict[str, Any] = {}
    meta = {"snapshot_date": None}
    if not row:
        return profile, source_map, meta
    profile.update(
        {
            "stock_code": str(row[0]).upper(),
            "stock_name": row[1] or "",
            "sw_l1": row[3] or "",
            "sw_l2": row[4] or "",
            "sw_l3": row[5] or "",
            "ths_concepts": row[6] or "",
            "main_business": row[7] or "",
            "comparable_companies": row[8] or "",
            "competitor_companies": row[9] or "",
            "main_product_types": row[10] or "",
            "main_product_names": row[11] or "",
        }
    )
    updated_at = row[12] or row[2]
    meta["snapshot_date"] = row[2]
    for field, source_field in [
        ("stock_name", "stock_name"),
        ("sw_l1", "sw_l1"),
        ("sw_l2", "sw_l2"),
        ("sw_l3", "sw_l3"),
        ("main_business", "main_business"),
        ("ths_concepts", "ths_concepts"),
        ("main_product_types", "main_product_types"),
        ("main_product_names", "main_product_names"),
        ("comparable_companies", "comparable_companies"),
        ("competitor_companies", "competitor_companies"),
    ]:
        if profile.get(field):
            source_map[f"company_profile.{field}"] = _source_entry(
                "ifind",
                "ifind_industry_chain_profile",
                source_field,
                str(updated_at),
                source_confidence=0.95,
            )
    return profile, source_map, meta


def _load_financial_trend(
    con: duckdb.DuckDBPyConnection,
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = con.execute(
        """
        SELECT MAX(as_of_date)
        FROM ifind_excel_facts
        WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
          AND as_of_date <= ?
        """,
        [stock_code, _digits_only(stock_code), as_of_date],
    ).fetchone()
    latest_snapshot = snapshot[0] if snapshot else None
    trend = {
        "period_rows": [],
        "latest_report_period": "",
        "period_count": 0,
        "data_type": "raw",
    }
    source_map: dict[str, Any] = {}
    meta = {"snapshot_date": latest_snapshot}
    if not latest_snapshot:
        return trend, source_map, meta

    rows = con.execute(
        """
        SELECT report_period, metric_name, metric_value, statement_type, collected_at
        FROM ifind_excel_facts
        WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
          AND as_of_date = ?
          AND report_period NOT LIKE '最新一期%'
        ORDER BY report_period DESC, metric_name
        """,
        [stock_code, _digits_only(stock_code), latest_snapshot],
    ).fetchall()
    by_period: dict[str, dict[str, Any]] = {}
    for report_period, metric_name, metric_value, statement_type, collected_at in rows:
        period = str(report_period)
        node = by_period.setdefault(
            period,
            {
                "__collected_at": collected_at,
                "__statement_type": statement_type,
            },
        )
        node[str(metric_name)] = metric_value

    ranked_periods = sorted(by_period.keys(), key=lambda item: _parse_period_label(item)[0], reverse=True)[:3]
    period_rows: list[dict[str, Any]] = []
    revenue_series: list[float] = []
    for raw_period in ranked_periods:
        facts = by_period[raw_period]
        normalized_period = _parse_period_label(raw_period)[1]
        revenue = facts.get("营业总收入")
        if revenue is None:
            revenue = facts.get("营业收入")
        net_profit = facts.get("归属于母公司所有者的净利润")
        if net_profit is None:
            net_profit = facts.get("净利润")
        total_assets = facts.get("资产总计")
        total_liabilities = facts.get("负债合计")
        debt_ratio = None
        if total_assets not in (None, 0) and total_liabilities is not None:
            debt_ratio = float(total_liabilities) / float(total_assets) * 100
        row = {
            "report_period": normalized_period,
            "revenue": revenue,
            "net_profit": net_profit,
            "eps": facts.get("基本每股收益"),
            "roe": None,
            "gross_margin": None,
            "debt_ratio": debt_ratio,
            "operating_cashflow": facts.get("经营活动产生的现金流量净额"),
            "source": {
                "source_type": "ifind",
                "source_table": "ifind_excel_facts",
                "updated_at": str(facts.get("__collected_at") or latest_snapshot),
            },
            "report_period_consistency": True,
        }
        period_rows.append(row)
        if revenue is not None:
            revenue_series.append(float(revenue))
        updated_at = str(facts.get("__collected_at") or latest_snapshot)
        field_map = {
            "revenue": "营业总收入" if facts.get("营业总收入") is not None else "营业收入",
            "net_profit": "归属于母公司所有者的净利润" if facts.get("归属于母公司所有者的净利润") is not None else "净利润",
            "eps": "基本每股收益",
            "operating_cashflow": "经营活动产生的现金流量净额",
            "debt_ratio": "负债合计/资产总计",
        }
        for field_name, source_field in field_map.items():
            if row.get(field_name) is not None:
                key = f"financial_trend.period_rows[{normalized_period}].{field_name}"
                if field_name == "debt_ratio":
                    source_map[key] = _source_entry(
                        "derived",
                        None,
                        None,
                        updated_at,
                        report_period=normalized_period,
                        source_confidence=0.9,
                        derivation="负债合计 / 资产总计 * 100",
                    )
                else:
                    source_map[key] = _source_entry(
                        "ifind",
                        "ifind_excel_facts",
                        source_field,
                        updated_at,
                        report_period=normalized_period,
                        source_confidence=0.95,
                    )
    trend["period_rows"] = period_rows
    trend["period_count"] = len(period_rows)
    if period_rows:
        trend["latest_report_period"] = period_rows[0]["report_period"]
    if len(revenue_series) >= 2:
        prev_period_change = []
        same_quarter_yoy = []
        for idx in range(len(period_rows)):
            current_row = period_rows[idx]
            current = current_row.get("revenue")
            if idx + 1 < len(period_rows):
                previous = period_rows[idx + 1].get("revenue")
                if current not in (None, 0) and previous not in (None, 0):
                    change_val = (float(current) / float(previous) - 1) * 100
                    prev_period_change.append(round(change_val, 2))
                    key = f"financial_trend.period_rows[{current_row['report_period']}].revenue_change_vs_prev_period"
                    source_map[key] = _source_entry(
                        "derived",
                        None,
                        None,
                        _utc_now(),
                        report_period=current_row["report_period"],
                        source_confidence=0.9,
                        derivation="revenue[i] / revenue[i+1] - 1",
                    )
        if prev_period_change:
            trend["revenue_change_vs_prev_period"] = prev_period_change
    metric_specs = [
        ("revenue", "revenue_yoy_same_quarter"),
        ("net_profit", "net_profit_yoy_same_quarter"),
        ("operating_cashflow", "operating_cashflow_yoy_same_quarter"),
    ]
    for field, trend_key in metric_specs:
        same_quarter_yoy = _compute_same_quarter_series(period_rows, field)
        if same_quarter_yoy:
            trend[trend_key] = same_quarter_yoy
            for item in same_quarter_yoy:
                key = f"financial_trend.period_rows[{item['report_period']}].{trend_key}"
                source_map[key] = _source_entry(
                    "derived",
                    None,
                    None,
                    _utc_now(),
                    report_period=item["report_period"],
                    source_confidence=0.9,
                    derivation=f"{field}[{item['report_period']}] / {field}[{item['base_period']}] - 1",
                )
    return trend, source_map, meta


def _load_state_core(
    foundation_con: duckdb.DuckDBPyConnection,
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    row = foundation_con.execute(
        """
        SELECT state_date, mn1_state_hex, w1_state_hex, d1_state_hex,
               mn1_state_score, w1_state_score, d1_state_score,
               ef_count, d1_trend
        FROM d1_perspective_state
        WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
          AND state_date <= CAST(? AS DATE)
        ORDER BY state_date DESC
        LIMIT 1
        """,
        [stock_code, _digits_only(stock_code), as_of_date],
    ).fetchone()
    state_core = {
        "mn1_state_hex": "",
        "w1_state_hex": "",
        "d1_state_hex": "",
        "mn1_state_score": None,
        "w1_state_score": None,
        "d1_state_score": None,
        "ef_count": None,
        "market_phase": "",
        "mn1_ef_duration": None,
        "w1_ef_duration": None,
        "d1_ef_duration": None,
        "all_three_ef_duration": None,
        "next_likely_change": "",
        "state_prior_view": "",
    }
    source_map: dict[str, Any] = {}
    meta = {"snapshot_date": None}
    if not row:
        return state_core, source_map, meta
    snapshot_date = str(row[0])
    state_core.update(
        {
            "mn1_state_hex": row[1] or "",
            "w1_state_hex": row[2] or "",
            "d1_state_hex": row[3] or "",
            "mn1_state_score": row[4],
            "w1_state_score": row[5],
            "d1_state_score": row[6],
            "ef_count": row[7],
        }
    )
    state_core["market_phase"] = _classify_market_phase(
        {
            "ef_count": row[7],
            "d1_trend": row[8],
        }
    )
    duration, duration_sources, duration_meta = _compute_state_duration_from_foundation(
        foundation_con,
        stock_code,
        as_of_date,
    )
    if not any(value is not None for value in duration.values()):
        duration, duration_sources, duration_meta = _load_state_duration(stock_code, as_of_date)
    state_core.update(duration)
    state_core["next_likely_change"] = _next_state_change_hint(state_core, duration)
    state_core["state_prior_view"] = _state_prior_view(state_core, duration)
    meta["snapshot_date"] = snapshot_date
    for field in [
        "mn1_state_hex",
        "w1_state_hex",
        "d1_state_hex",
        "mn1_state_score",
        "w1_state_score",
        "d1_state_score",
        "ef_count",
    ]:
        if state_core.get(field) not in ("", None):
            source_map[f"state_core.{field}"] = _source_entry(
                "foundation",
                "d1_perspective_state",
                field,
                snapshot_date,
                source_confidence=1.0,
            )
    source_map["state_core.market_phase"] = _source_entry(
        "derived",
        None,
        None,
        _utc_now(),
        source_confidence=0.9,
        derivation="classify_market_phase(ef_count, d1_trend)",
    )
    source_map.update(duration_sources)
    source_map["state_core.next_likely_change"] = _source_entry(
        "derived",
        None,
        None,
        _utc_now(),
        source_confidence=0.85,
        derivation="rule-based next state change hint from state_duration + current state_core",
    )
    source_map["state_core.state_prior_view"] = _source_entry(
        "derived",
        None,
        None,
        _utc_now(),
        source_confidence=0.85,
        derivation="rule-based prior view from cross-period state + continuous duration",
    )
    if duration_meta.get("snapshot_date"):
        meta["duration_snapshot_date"] = duration_meta["snapshot_date"]
    return state_core, source_map, meta


def _load_strategy_fit_overlay(
    stock_code: str,
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    overlay = {
        "lifecycle_stage": "",
        "strategy_environment_fit": "",
        "fit_strategy": "",
        "env_category": "",
    }
    if not SIGNAL_DB.exists():
        return overlay, {}, {"snapshot_date": None}
    con = _open_readonly(SIGNAL_DB)
    try:
        row = con.execute(
            """
            SELECT signal_date, lifecycle_stage, strategy_environment_fit, strategy_id, env_category
            FROM strategy_signal_daily
            WHERE (stock_code = ? OR split_part(stock_code, '.', 1) = ?)
              AND signal_date <= CAST(? AS DATE)
            ORDER BY signal_date DESC, signal_strength DESC
            LIMIT 1
            """,
            [stock_code, _digits_only(stock_code), as_of_date],
        ).fetchone()
    finally:
        con.close()
    if not row:
        return overlay, {}, {"snapshot_date": None}
    snapshot_date = str(row[0])
    overlay.update(
        {
            "lifecycle_stage": row[1] or "",
            "strategy_environment_fit": row[2] or "",
            "fit_strategy": row[3] or "",
            "env_category": row[4] or "",
        }
    )
    source_map: dict[str, Any] = {}
    for field in ["lifecycle_stage", "strategy_environment_fit", "fit_strategy", "env_category"]:
        if overlay.get(field):
            source_field = "strategy_id" if field == "fit_strategy" else field
            source_map[f"strategy_fit_overlay.{field}"] = _source_entry(
                "derived" if field == "fit_strategy" else "foundation",
                "strategy_signal_daily",
                source_field,
                snapshot_date,
                source_confidence=0.9 if field == "fit_strategy" else 0.95,
                derivation="strategy_id selected from highest signal_strength row" if field == "fit_strategy" else None,
            )
    return overlay, source_map, {"snapshot_date": snapshot_date}


def _load_json_by_date(directory: Path, prefix: str, as_of_date: str) -> tuple[Any, str | None]:
    path = _find_latest_file(directory, prefix, ".json", as_of_date)
    if not path:
        return None, None
    return _json_load(path), path.stem.split("_")[-1]


def _load_industry_state(
    company_profile: dict[str, Any],
    as_of_date: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sw_l1 = company_profile.get("sw_l1") or ""
    state = {
        "sw_l1": sw_l1,
        "prosperity_score": None,
        "prosperity_change": "",
        "chain_position": "",
        "etf_symbol": "",
        "etf_state_hex": "",
        "etf_ef_count": None,
        "etf_20d_return": None,
        "sector_resonance": None,
        "sector_resonance_count": None,
    }
    source_map: dict[str, Any] = {}
    meta = {"position_date": None, "rotation_date": None, "market_state_date": None}
    if not sw_l1:
        return state, source_map, meta

    position_payload, position_date = _load_json_by_date(ROOT / "outputs" / "industry_chain", "industry_position_summary", as_of_date)
    position_record = None
    if position_payload:
        for record in position_payload.get("records", []):
            if record.get("sw_l1") == sw_l1:
                position_record = record
                break
    if position_record:
        meta["position_date"] = position_date
        state["prosperity_score"] = position_record.get("prosperity_score")
        state["prosperity_change"] = position_record.get("prosperity_change") or ""
        state["chain_position"] = position_record.get("chain_position") or ""
        state["etf_symbol"] = position_record.get("etf_symbol") or ""
        state["etf_ef_count"] = position_record.get("etf_ef_count")
        for field in ["prosperity_score", "prosperity_change", "chain_position", "etf_symbol", "etf_ef_count"]:
            if state.get(field) not in ("", None):
                source_map[f"industry_state.{field}"] = _source_entry(
                    "derived",
                    "industry_position_summary",
                    field,
                    position_date or as_of_date.replace("-", ""),
                    source_confidence=0.9,
                )

    rotation_payload, rotation_date = _load_json_by_date(ROOT / "outputs" / "industry_rotation", "industry_rotation", as_of_date)
    rotation_record = None
    if rotation_payload:
        for record in rotation_payload.get("top_industries", []):
            if record.get("sw_l1") == sw_l1:
                rotation_record = record
                break
    if rotation_record:
        meta["rotation_date"] = rotation_date
        state["etf_symbol"] = state["etf_symbol"] or (rotation_record.get("etf_symbol") or "")
        etf_20d = rotation_record.get("etf_return_20d")
        if etf_20d is not None:
            state["etf_20d_return"] = round(float(etf_20d) * 100, 2)
            source_map["industry_state.etf_20d_return"] = _source_entry(
                "derived",
                "industry_rotation.top_industries",
                "etf_return_20d",
                rotation_date or as_of_date.replace("-", ""),
                source_confidence=0.9,
                derivation="industry_rotation.etf_return_20d * 100",
            )
        confirm_rate = rotation_record.get("moneyflow_confirm_rate")
        pool_count = int(rotation_record.get("pool_count") or 0)
        confirmed_count = int(rotation_record.get("moneyflow_confirmed_count") or 0)
        if confirm_rate is not None:
            state["sector_resonance"] = bool(float(confirm_rate) >= 0.6 and pool_count >= 5)
            state["sector_resonance_count"] = confirmed_count
            source_map["industry_state.sector_resonance"] = _source_entry(
                "derived",
                "industry_rotation.top_industries",
                "moneyflow_confirm_rate/pool_count",
                rotation_date or as_of_date.replace("-", ""),
                source_confidence=0.9,
                derivation="moneyflow_confirm_rate >= 0.6 and pool_count >= 5",
            )
            source_map["industry_state.sector_resonance_count"] = _source_entry(
                "derived",
                "industry_rotation.top_industries",
                "moneyflow_confirmed_count",
                rotation_date or as_of_date.replace("-", ""),
                source_confidence=0.9,
            )

    market_assets_payload, market_state_date = _load_json_by_date(ROOT / "outputs" / "market_assets_state", "market_assets_state", as_of_date)
    if market_assets_payload and state.get("etf_symbol"):
        meta["market_state_date"] = market_state_date
        etf_symbol = state["etf_symbol"]
        for item in market_assets_payload:
            if item.get("symbol") == etf_symbol:
                state["etf_state_hex"] = item.get("d1_state_hex") or ""
                if state.get("etf_ef_count") is None:
                    state["etf_ef_count"] = item.get("ef_count")
                if state["etf_state_hex"]:
                    source_map["industry_state.etf_state_hex"] = _source_entry(
                        "foundation",
                        "market_assets_state",
                        "d1_state_hex",
                        market_state_date or as_of_date.replace("-", ""),
                        source_confidence=1.0,
                    )
                if state.get("etf_ef_count") is not None:
                    source_map["industry_state.etf_ef_count"] = _source_entry(
                        "foundation",
                        "market_assets_state",
                        "ef_count",
                        market_state_date or as_of_date.replace("-", ""),
                        source_confidence=1.0,
                    )
                break
    return state, source_map, meta


def _load_valuation_reference(stock_code: str, as_of_date: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    parquet_path = _find_latest_file(ROOT / "data" / "akshare_fundamental", "stock_value", ".parquet", as_of_date)
    valuation = {
        "pe_ttm": None,
        "pe_static": None,
        "pb": None,
        "ps": None,
        "market_cap": None,
        "industry_pe_avg": None,
        "comparable_pe_range": None,
        "data_type": "reference",
    }
    if not parquet_path:
        return valuation, {}, {"snapshot_date": None}
    con = duckdb.connect()
    try:
        query = f"""
        SELECT 数据日期, 总市值, "PE(TTM)", "PE(静)", 市净率, 市销率
        FROM read_parquet('{parquet_path.as_posix()}')
        WHERE stock_code = ?
          AND 数据日期 <= CAST(? AS DATE)
        ORDER BY 数据日期 DESC
        LIMIT 1
        """
        row = con.execute(query, [_digits_only(stock_code), as_of_date]).fetchone()
    finally:
        con.close()
    if not row:
        return valuation, {}, {"snapshot_date": None}
    snapshot_date = str(row[0])
    valuation.update(
        {
            "market_cap": row[1],
            "pe_ttm": row[2],
            "pe_static": row[3],
            "pb": row[4],
            "ps": row[5],
        }
    )
    source_map: dict[str, Any] = {}
    field_map = {
        "market_cap": "总市值",
        "pe_ttm": "PE(TTM)",
        "pe_static": "PE(静)",
        "pb": "市净率",
        "ps": "市销率",
    }
    for field, source_field in field_map.items():
        if valuation.get(field) is not None:
            source_map[f"valuation_reference.{field}"] = _source_entry(
                "akshare",
                "stock_value",
                source_field,
                snapshot_date,
                source_confidence=0.85,
            )
    return valuation, source_map, {"snapshot_date": snapshot_date}


def _load_market_views(stock_code: str, as_of_date: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    parquet_path = _find_latest_file(ROOT / "data" / "akshare_fundamental", "stock_forecast", ".parquet", as_of_date)
    market_views = {
        "rating_distribution": {},
        "target_price_low": None,
        "target_price_high": None,
        "target_price_count": 0,
        "latest_report": None,
    }
    if not parquet_path:
        return market_views, {}, {"snapshot_date": None}
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT 发布日期, 研究机构简称, 投资评级, "目标价格-下限", "目标价格-上限"
            FROM read_parquet('{parquet_path.as_posix()}')
            WHERE 证券代码 = ?
              AND 发布日期 <= ?
            ORDER BY 发布日期 DESC
            """,
            [_digits_only(stock_code), as_of_date],
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return market_views, {}, {"snapshot_date": None}
    rating_distribution: dict[str, int] = {}
    target_prices: list[float] = []
    for row in rows:
        rating = row[2] or "未知"
        rating_distribution[rating] = rating_distribution.get(rating, 0) + 1
        for price in [row[3], row[4]]:
            if price is not None:
                target_prices.append(float(price))
    latest = rows[0]
    market_views["rating_distribution"] = rating_distribution
    if target_prices:
        market_views["target_price_low"] = min(target_prices)
        market_views["target_price_high"] = max(target_prices)
        market_views["target_price_count"] = len(target_prices)
    market_views["latest_report"] = {
        "institution": latest[1] or "",
        "date": latest[0],
        "rating": latest[2] or "",
        "target_price": next((price for price in [latest[4], latest[3]] if price is not None), None),
    }
    snapshot_date = str(latest[0])
    source_map: dict[str, Any] = {
        "market_views.rating_distribution": _source_entry(
            "akshare",
            "stock_forecast",
            "投资评级",
            snapshot_date,
            source_confidence=0.85,
        ),
        "market_views.latest_report": _source_entry(
            "akshare",
            "stock_forecast",
            "发布日期/研究机构简称/投资评级/目标价格",
            snapshot_date,
            source_confidence=0.85,
        ),
    }
    if market_views["target_price_low"] is not None:
        source_map["market_views.target_price_low"] = _source_entry(
            "akshare",
            "stock_forecast",
            "目标价格-下限",
            snapshot_date,
            source_confidence=0.85,
        )
        source_map["market_views.target_price_high"] = _source_entry(
            "akshare",
            "stock_forecast",
            "目标价格-上限",
            snapshot_date,
            source_confidence=0.85,
        )
        source_map["market_views.target_price_count"] = _source_entry(
            "derived",
            None,
            None,
            snapshot_date,
            source_confidence=0.9,
            derivation="count(non-null target prices from stock_forecast rows)",
        )
    return market_views, source_map, {"snapshot_date": snapshot_date}


def _build_risk_flags(
    company_profile: dict[str, Any],
    financial_trend: dict[str, Any],
    industry_state: dict[str, Any],
    valuation_reference: dict[str, Any],
    completeness: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    risks = {
        "financial_risks": [],
        "industry_risks": [],
        "valuation_risks": [],
        "policy_risks": [],
        "data_risks": [],
    }
    latest_row = financial_trend.get("period_rows", [{}])[0] if financial_trend.get("period_rows") else {}
    debt_ratio = latest_row.get("debt_ratio")
    cashflow = latest_row.get("operating_cashflow")
    def _latest_same_quarter(metric_key: str) -> float | None:
        rows = financial_trend.get(metric_key) or []
        if rows:
            return rows[0].get("value")
        return None

    revenue_yoy_same_quarter = _latest_same_quarter("revenue_yoy_same_quarter")
    net_profit_yoy_same_quarter = _latest_same_quarter("net_profit_yoy_same_quarter")
    operating_cashflow_yoy_same_quarter = _latest_same_quarter("operating_cashflow_yoy_same_quarter")

    debt_important, debt_reason = _metric_importance(company_profile, "debt_ratio")
    cashflow_important, cashflow_reason = _metric_importance(company_profile, "operating_cashflow")
    revenue_important, revenue_reason = _metric_importance(company_profile, "revenue")
    profit_important, profit_reason = _metric_importance(company_profile, "net_profit")

    if debt_ratio is not None and float(debt_ratio) >= 60 and debt_important:
        risks["financial_risks"].append(
            _risk_item(
                risk=f"资产负债率 {float(debt_ratio):.1f}%，偏高，需关注偿债压力。",
                significance="中",
                reason=debt_reason,
            )
        )
    if cashflow is not None and float(cashflow) < 0 and cashflow_important:
        risks["financial_risks"].append(
            _risk_item(
                risk="最新一期经营活动现金流为负，现金质量需复核。",
                significance="高",
                reason=cashflow_reason,
            )
        )
    if revenue_yoy_same_quarter is not None and float(revenue_yoy_same_quarter) < 0 and revenue_important:
        risks["financial_risks"].append(
            _risk_item(
                risk=f"最近一期收入较上年同期下降 {abs(float(revenue_yoy_same_quarter)):.1f}%，增长趋势偏弱。",
                significance="高",
                reason=revenue_reason,
            )
        )
    if net_profit_yoy_same_quarter is not None and float(net_profit_yoy_same_quarter) < 0 and profit_important:
        risks["financial_risks"].append(
            _risk_item(
                risk=f"最近一期净利润较上年同期下降 {abs(float(net_profit_yoy_same_quarter)):.1f}%，盈利兑现承压。",
                significance="高",
                reason=profit_reason,
            )
        )
    if operating_cashflow_yoy_same_quarter is not None and float(operating_cashflow_yoy_same_quarter) < 0 and cashflow_important:
        risks["financial_risks"].append(
            _risk_item(
                risk=f"最近一期经营现金流较上年同期下降 {abs(float(operating_cashflow_yoy_same_quarter)):.1f}%，经营质量需复核。",
                significance="高",
                reason=cashflow_reason,
            )
        )

    prosperity = industry_state.get("prosperity_score")
    if prosperity is not None and float(prosperity) < 4:
        risks["industry_risks"].append(
            _risk_item(
                risk=f"行业景气分 {float(prosperity):.2f}，处于偏弱区间。",
                significance="中",
                reason="行业景气偏弱通常意味着需求扩张和估值扩张空间受限。",
            )
        )
    if industry_state.get("sector_resonance") is False:
        risks["industry_risks"].append(
            _risk_item(
                risk="板块共振确认不足，行业合力偏弱。",
                significance="中",
                reason="行业内部缺少同步强化信号时，个股表现更依赖自身经营兑现。",
            )
        )
    if industry_state.get("etf_ef_count") == 0 and industry_state.get("etf_state_hex"):
        risks["industry_risks"].append(
            _risk_item(
                risk="行业 ETF 当前未进入 E/F 共振状态。",
                significance="中",
                reason="行业 ETF 未进入 E/F 共振，通常意味着板块层面的趋势确认不足。",
            )
        )

    pe_ttm = valuation_reference.get("pe_ttm")
    if pe_ttm is not None and float(pe_ttm) > 100:
        risks["valuation_risks"].append(
            _risk_item(
                risk=f"PE(TTM) {float(pe_ttm):.1f} 倍，估值弹性与回撤风险较高。",
                significance="中",
                reason="高 PE 往往意味着对未来增长兑现要求更高，业绩波动时回撤弹性更大。",
            )
        )
    pb = valuation_reference.get("pb")
    if pb is not None and float(pb) > 8:
        if "半导体" in str(company_profile.get("sw_l2") or "") or "数字芯片设计" in str(company_profile.get("sw_l3") or ""):
            risks["valuation_risks"].append(
                _risk_item(
                    risk=f"市净率 {float(pb):.1f} 倍，处于高位。",
                    significance="中",
                    reason="轻资产芯片设计公司 PB 往往偏高，仍需结合盈利兑现判断。",
                )
            )
        else:
            risks["valuation_risks"].append(
                _risk_item(
                    risk=f"市净率 {float(pb):.1f} 倍，估值容错空间有限。",
                    significance="中",
                    reason="高 PB 往往意味着资产端安全垫偏薄，估值容错空间有限。",
                )
            )

    for module in ["financial_trend", "industry_state", "valuation_reference", "market_views"]:
        status = completeness.get(module)
        if status == "partial":
            risks["data_risks"].append(
                _risk_item(
                    risk=f"{module} 当前仅为部分数据覆盖。",
                    significance="中",
                    reason="相关结论需要降级解释，不能按完整证据链理解。",
                )
            )
        elif status == "missing":
            risks["data_risks"].append(
                _risk_item(
                    risk=f"{module} 当前缺失，相关结论应降级处理。",
                    significance="高",
                    reason="关键证据缺失时，不应把模块结论当成高确定性判断。",
                )
            )
    if valuation_reference.get("pe_ttm") is not None:
        risks["data_risks"].append(
            _risk_item(
                risk="估值参考来自 AKShare，本期未做 iFinD 交叉验证。",
                significance="中",
                reason="单一来源估值字段更适合作为参考，而不是高确定性结论。",
            )
        )

    source_map: dict[str, Any] = {}
    if risks["financial_risks"]:
        source_map["risk_flags.financial_risks"] = _source_entry(
            "derived",
            None,
            None,
            _utc_now(),
            source_confidence=0.9,
            derivation="financial_trend-based risk rules",
        )
    if risks["industry_risks"]:
        source_map["risk_flags.industry_risks"] = _source_entry(
            "derived",
            None,
            None,
            _utc_now(),
            source_confidence=0.9,
            derivation="industry_state-based risk rules",
        )
    if risks["valuation_risks"]:
        source_map["risk_flags.valuation_risks"] = _source_entry(
            "derived",
            None,
            None,
            _utc_now(),
            source_confidence=0.9,
            derivation="valuation_reference-based risk rules",
        )
    if risks["data_risks"]:
        source_map["risk_flags.data_risks"] = _source_entry(
            "derived",
            None,
            None,
            _utc_now(),
            source_confidence=0.9,
            derivation="module completeness-based risk rules",
        )
    return risks, source_map


def _status_company_profile(profile: dict[str, Any]) -> str:
    if all(profile.get(field) for field in ["stock_code", "stock_name", "sw_l1", "main_business"]):
        return "sufficient"
    if profile.get("sw_l1"):
        return "partial"
    return "missing"


def _status_financial_trend(trend: dict[str, Any]) -> str:
    rows = trend.get("period_rows") or []
    if not rows:
        return "missing"
    all_consistent = all(bool(row.get("report_period_consistency")) for row in rows)
    if len(rows) >= 3 and all_consistent and trend.get("latest_report_period"):
        return "sufficient"
    return "partial"


def _status_industry_state(state: dict[str, Any]) -> str:
    if state.get("etf_state_hex") and state.get("etf_ef_count") is not None:
        return "sufficient"
    if state.get("sw_l1"):
        return "partial"
    return "missing"


def _status_state_core(state_core: dict[str, Any]) -> str:
    filled = sum(1 for key in ["mn1_state_hex", "w1_state_hex", "d1_state_hex"] if state_core.get(key))
    if filled == 3:
        return "sufficient"
    if filled >= 1:
        return "partial"
    return "missing"


def _status_strategy_overlay(overlay: dict[str, Any]) -> str:
    filled = sum(
        1
        for key in ["lifecycle_stage", "strategy_environment_fit", "fit_strategy", "env_category"]
        if overlay.get(key)
    )
    if filled == 0:
        return "not_available"
    if filled >= 3:
        return "sufficient"
    return "partial"


def _status_valuation_reference(valuation: dict[str, Any]) -> str:
    if valuation.get("pe_ttm") is not None and valuation.get("pb") is not None and valuation.get("industry_pe_avg") is not None:
        return "sufficient"
    if valuation.get("pe_ttm") is not None or valuation.get("pb") is not None:
        return "partial"
    return "missing"


def _status_market_views(market_views: dict[str, Any]) -> str:
    if market_views.get("rating_distribution") and market_views.get("latest_report"):
        return "sufficient"
    if market_views.get("rating_distribution"):
        return "partial"
    return "missing"


def _status_risk_flags(risk_flags: dict[str, Any]) -> str:
    if risk_flags.get("financial_risks") or risk_flags.get("industry_risks"):
        return "sufficient"
    if risk_flags.get("data_risks"):
        return "partial"
    return "missing"


def _compute_completeness(payload: dict[str, Any]) -> dict[str, Any]:
    module_status = {
        "company_profile": _status_company_profile(payload["company_profile"]),
        "financial_trend": _status_financial_trend(payload["financial_trend"]),
        "industry_state": _status_industry_state(payload["industry_state"]),
        "state_core": _status_state_core(payload["state_core"]),
        "strategy_fit_overlay": _status_strategy_overlay(payload["strategy_fit_overlay"]),
        "valuation_reference": _status_valuation_reference(payload["valuation_reference"]),
        "market_views": _status_market_views(payload["market_views"]),
        "risk_flags": _status_risk_flags(payload["risk_flags"]),
    }
    required_total = 0.0
    for module, weight in REQUIRED_MODULES.items():
        required_total += weight * STATUS_SCORE.get(module_status[module], 0.0)
    optional_total = 0.0
    for module, weight in OPTIONAL_MODULES.items():
        status = module_status.get(module)
        if status is None:
            optional_total += weight * 0.5
        else:
            optional_total += weight * STATUS_SCORE.get(status, 0.0)
    overall_score = required_total * 0.85 + optional_total * 0.15
    if overall_score >= 0.75:
        overall = "sufficient"
    elif overall_score >= 0.40:
        overall = "partial"
    else:
        overall = "missing"
    return {
        **module_status,
        "required_modules_score": round(required_total, 3),
        "optional_modules_score": round(optional_total, 3),
        "overall_score": round(overall_score, 3),
        "overall": overall,
    }


def build_external_research_evidence(
    stock_code: str,
    as_of_date: str,
    foundation_db: str | Path | None = None,
    fundamental_db: str | Path | None = None,
) -> dict[str, Any]:
    foundation_path = _resolve_foundation_db(as_of_date, foundation_db)
    fundamental_path = Path(fundamental_db) if fundamental_db else FUNDAMENTAL_DB
    if not fundamental_path.exists():
        raise FileNotFoundError(f"Fundamental DB not found: {fundamental_path}")

    warnings: list[str] = []
    canonical_code = _canonical_stock_code(stock_code)
    company_profile = {
        "stock_code": canonical_code,
        "stock_name": "",
        "sw_l1": "",
        "sw_l2": "",
        "sw_l3": "",
        "main_business": "",
        "main_product_types": "",
        "main_product_names": "",
        "comparable_companies": "",
        "competitor_companies": "",
        "ths_concepts": "",
    }
    company_sources: dict[str, Any] = {}
    company_meta: dict[str, Any] = {"snapshot_date": None}
    financial_trend = {
        "period_rows": [],
        "latest_report_period": "",
        "period_count": 0,
        "data_type": "raw",
    }
    financial_sources: dict[str, Any] = {}
    financial_meta: dict[str, Any] = {"snapshot_date": None}

    foundation_con = _open_readonly(foundation_path)
    try:
        fund_con: duckdb.DuckDBPyConnection | None = None
        try:
            fund_con = _open_readonly(fundamental_path)
        except duckdb.IOException as exc:
            warnings.append(
                "fundamental_evidence.duckdb 当前被采集进程占用，基础资料已降级；"
                "研究页仍可展示 State、策略与参考信息。"
            )
            company_meta["error"] = str(exc)
            financial_meta["error"] = str(exc)
        if fund_con is not None:
            try:
                canonical_code = _canonical_stock_code(stock_code, fund_con)
                company_profile, company_sources, company_meta = _load_company_profile(
                    fund_con,
                    canonical_code,
                    as_of_date,
                )
                canonical_code = company_profile.get("stock_code") or canonical_code
                financial_trend, financial_sources, financial_meta = _load_financial_trend(
                    fund_con,
                    canonical_code,
                    as_of_date,
                )
            finally:
                fund_con.close()
        state_core, state_sources, state_meta = _load_state_core(foundation_con, canonical_code, as_of_date)
    finally:
        foundation_con.close()

    strategy_fit_overlay, overlay_sources, overlay_meta = _load_strategy_fit_overlay(canonical_code, as_of_date)
    industry_state, industry_sources, industry_meta = _load_industry_state(company_profile, as_of_date)
    valuation_reference, valuation_sources, valuation_meta = _load_valuation_reference(canonical_code, as_of_date)
    market_views, market_view_sources, market_views_meta = _load_market_views(canonical_code, as_of_date)

    payload: dict[str, Any] = {
        "contract_version": "evidence_v1",
        "meta": {
            "stock_code": canonical_code,
            "stock_name": company_profile.get("stock_name") or canonical_code,
            "as_of_date": as_of_date,
            "generated_at": _utc_now(),
            "research_only": True,
            "warnings": warnings,
            "degraded_modules": ["company_profile", "financial_trend"] if warnings else [],
            "source_policy": SOURCE_POLICY,
            "foundation_db": str(foundation_path),
            "fundamental_db": str(fundamental_path),
            "data_snapshots": {
                "company_profile": company_meta.get("snapshot_date"),
                "financial_trend": financial_meta.get("snapshot_date"),
                "state_core": state_meta.get("snapshot_date"),
                "strategy_fit_overlay": overlay_meta.get("snapshot_date"),
                "industry_state": {
                    "industry_position": industry_meta.get("position_date"),
                    "industry_rotation": industry_meta.get("rotation_date"),
                    "market_assets_state": industry_meta.get("market_state_date"),
                },
                "valuation_reference": valuation_meta.get("snapshot_date"),
                "market_views": market_views_meta.get("snapshot_date"),
            },
        },
        "company_profile": company_profile,
        "financial_trend": financial_trend,
        "industry_state": industry_state,
        "state_core": state_core,
        "strategy_fit_overlay": strategy_fit_overlay,
        "valuation_reference": valuation_reference,
        "market_views": market_views,
        "risk_flags": {},
        "source_map": {},
        "completeness": {},
    }
    pre_risk_completeness = {
        "financial_trend": _status_financial_trend(financial_trend),
        "industry_state": _status_industry_state(industry_state),
        "valuation_reference": _status_valuation_reference(valuation_reference),
        "market_views": _status_market_views(market_views),
    }
    risk_flags, risk_sources = _build_risk_flags(
        company_profile=company_profile,
        financial_trend=financial_trend,
        industry_state=industry_state,
        valuation_reference=valuation_reference,
        completeness=pre_risk_completeness,
    )
    payload["risk_flags"] = risk_flags
    payload["source_map"] = {
        **company_sources,
        **financial_sources,
        **industry_sources,
        **state_sources,
        **overlay_sources,
        **valuation_sources,
        **market_view_sources,
        **risk_sources,
    }
    payload["completeness"] = _compute_completeness(payload)
    return payload
