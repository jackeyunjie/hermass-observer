from __future__ import annotations

from typing import Any

from hermass_platform.chat.compliance_filter import apply_disclaimer, check_compliance

DEFAULT_DISCLAIMER = (
    "以上为基于公开数据的研究观察，不构成投资建议。"
    "历史数据不代表未来表现。投资决策应由投资者独立做出。"
)

RENDER_PROFILES = {"quick", "standard", "full", "value"}


def _status_label(status: str | None) -> str:
    mapping = {
        "sufficient": "充足",
        "partial": "部分",
        "missing": "缺失",
        "not_available": "未覆盖",
    }
    return mapping.get(str(status or ""), str(status or "未知"))


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value):,.{digits}f}"
    except Exception:
        return str(value)


def _fmt_yi(value: Any, digits: int = 2) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value) / 1e8:.{digits}f}亿"
    except Exception:
        return str(value)


def _fmt_percent(value: Any, digits: int = 1) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        return f"{float(value):.{digits}f}%"
    except Exception:
        return str(value)


def _fmt_pe(value: Any) -> str:
    if value in (None, ""):
        return "暂无"
    try:
        val = float(value)
    except Exception:
        return str(value)
    if val <= 0:
        return "亏损（PE 不适用）"
    return f"{val:.2f}"


def _state_score_from_hex(state_hex: str) -> int | None:
    raw = str(state_hex or "").strip().upper()
    if not raw:
        return None
    sign = -1 if raw.startswith("-") else 1
    text = raw[1:] if sign < 0 else raw
    try:
        return sign * int(text, 16)
    except Exception:
        return None


def _state_alias(state_hex: str) -> str:
    score = _state_score_from_hex(state_hex)
    if score is None:
        return "暂无"
    negative = score < 0
    magnitude = abs(score)
    base_alias = "扩张" if magnitude >= 8 else "收缩"
    trend_alias = "趋势" if magnitude & 4 else "无方向"
    position_alias = "突破" if magnitude & 2 else "未突破"
    vol_alias = "活跃" if magnitude & 1 else "稳定"
    alias = f"{base_alias}·{trend_alias}·{position_alias}·{vol_alias}"
    if negative:
        alias += "（负向）"
    return alias


def _state_structure_explanation(state_core: dict[str, Any]) -> str:
    mn1 = str(state_core.get("mn1_state_hex") or "")
    w1 = str(state_core.get("w1_state_hex") or "")
    d1 = str(state_core.get("d1_state_hex") or "")
    ef_count = state_core.get("ef_count")
    if ef_count == 3 and d1 == "F":
        return "中大周期偏强，日线处于高活跃推进段"
    if ef_count == 3 and d1 == "E":
        return "中大周期偏强，日线推进结构相对稳定"
    if ef_count == 2:
        return "中大周期已有共振，短周期仍在确认"
    if ef_count == 1:
        return "只有单周期保持强势，整体共振不足"
    if ef_count == 0:
        return "当前未形成 E/F 共振，各周期未达最强状态"
    if mn1 in {"E", "F"} and d1 not in {"E", "F"}:
        return "大级别背景偏强，短期仍在确认"
    if mn1 not in {"E", "F"} and d1 in {"E", "F"}:
        return "短期已有推进，但大级别背景仍未完全配合"
    if w1 in {"E", "F"} and d1 not in {"E", "F"}:
        return "中期趋势仍在，短期节奏转入确认"
    return "当前结构仍需结合更多周期信息综合判断"


def _state_duration_lines(state_core: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    mapping = [
        ("MN1 强状态持续", state_core.get("mn1_ef_duration")),
        ("W1 强状态持续", state_core.get("w1_ef_duration")),
        ("D1 强状态持续", state_core.get("d1_ef_duration")),
        ("三周期共振持续", state_core.get("all_three_ef_duration")),
    ]
    rendered = []
    for label, value in mapping:
        if value is not None:
            rendered.append(f"{label} {value} 天")
    if rendered:
        lines.append("；".join(rendered))
    hint = str(state_core.get("next_likely_change") or "").strip()
    if hint:
        lines.append(hint)
    return lines


def _state_quick_display(state_core: dict[str, Any]) -> str:
    combo = "/".join(
        [
            state_core.get("mn1_state_hex", "") or "-",
            state_core.get("w1_state_hex", "") or "-",
            state_core.get("d1_state_hex", "") or "-",
        ]
    )
    prior = str(state_core.get("state_prior_view") or "").strip()
    if prior:
        return f"{combo}（{prior}）"
    return f"{combo}（{_state_structure_explanation(state_core)}）"


def _phase1_resonance_lines(evidence: dict[str, Any]) -> list[str]:
    state_core = evidence.get("state_core", {})
    industry = evidence.get("industry_state", {})
    enrichment = evidence.get("enrichment") or {}
    providers = enrichment.get("providers") or {}
    lines: list[str] = ["### Phase 1 多因素共振"]

    ef_count = state_core.get("ef_count")
    if ef_count == 3:
        lines.append("- State 共振：已确认（三周期 E/F 共振成立）。")
    elif ef_count == 2:
        lines.append("- State 共振：部分确认（已有双周期共振，短周期仍在确认）。")
    elif ef_count == 1:
        lines.append("- State 共振：仅单周期保持强势，整体共振不足。")
    else:
        lines.append("- State 共振：当前未形成 E/F 共振，各周期未达最强状态。")

    if industry.get("sector_resonance") is True:
        lines.append(
            f"- 行业共振：已确认（确认家数 {industry.get('sector_resonance_count') if industry.get('sector_resonance_count') is not None else '暂无'}，ETF State {industry.get('etf_state_hex') or '暂无'}）。"
        )
    elif industry.get("etf_ef_count") not in (None, "") and int(industry.get("etf_ef_count")) >= 2:
        lines.append(f"- 行业共振：ETF 已进入 E/F 支撑区（ef={industry.get('etf_ef_count')}），但板块同步强化仍需继续观察。")
    else:
        lines.append("- 行业共振：当前未见明确板块级同步强化，更多依赖个股自身兑现。")

    news_provider = providers.get("public_news_digest") or {}
    status = news_provider.get("status")
    if status == "local_market_views_already_present":
        lines.append("- 事件驱动：已有本地公开观点线索，后续外部事件摘要仅作补充。")
    elif status == "ready_for_external_news_supplement":
        lines.append("- 事件驱动：已具备外部事件补充条件，当前可按需叠加公开新闻/政策摘要。")
    elif status == "placeholder":
        lines.append("- 事件驱动：外部事件摘要尚未启用，当前以前台结构化证据为主。")
    else:
        lines.append("- 事件驱动：当前未接入真实外部摘要，事件解释能力仍属可选增强层。")

    return lines


def _top_risks(risk_flags: dict[str, Any], limit: int = 2) -> list[str]:
    out: list[str] = []
    for key in ["financial_risks", "industry_risks", "valuation_risks", "data_risks", "policy_risks"]:
        for item in risk_flags.get(key, []) or []:
            if isinstance(item, dict):
                text = str(item.get("risk") or "").strip()
            else:
                text = str(item).strip()
            if text and text not in out:
                out.append(text)
            if len(out) >= limit:
                return out
    return out


def _clean_risk_text(text: str) -> str:
    return str(text).replace("。；", "；").strip()


def _join_risk_texts(items: list[str]) -> str:
    cleaned = []
    for item in items:
        text = _clean_risk_text(item).rstrip("。.;； ")
        if text:
            cleaned.append(text)
    return "；".join(cleaned)


def _risk_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("risk") or "").strip()
    return str(item).strip()


def _risk_significance(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("significance") or "").strip()
    return ""


def _risk_reason(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("reason") or "").strip()
    return ""


def _source_summary(source_map: dict[str, Any]) -> str:
    source_types = []
    for item in source_map.values():
        source_type = item.get("source_type")
        if source_type and source_type not in source_types:
            source_types.append(source_type)
    label_map = {
        "ifind": "iFinD",
        "akshare": "AKShare",
        "foundation": "State 底座",
        "derived": "规则派生",
        "manual": "人工输入",
    }
    readable = [label_map.get(item, item) for item in source_types]
    return " + ".join(readable) if readable else "暂无来源摘要"


def _enrichment_summary_lines(evidence: dict[str, Any]) -> list[str]:
    meta = evidence.get("meta", {})
    policy = meta.get("enrichment_policy") or {}
    status = meta.get("enrichment_status")
    hints = meta.get("enrichment_hints") or []
    if not policy and not status:
        return []
    lines = [
        f"- Enrichment 状态：{status or 'configured'}",
        f"- Enrichment 策略：{policy.get('priority') or 'local_evidence_first'}",
    ]
    if hints:
        lines.append(f"- 可用增强线索：{', '.join(str(item) for item in hints)}")
    return lines


def _provider_status_lines(evidence: dict[str, Any]) -> list[str]:
    enrichment = evidence.get("enrichment") or {}
    providers = enrichment.get("providers") or {}
    if not providers:
        return []
    lines: list[str] = []
    for key in ["industry_competition_external_peers", "public_news_digest"]:
        provider = providers.get(key)
        if not provider:
            continue
        lines.append(
            "Enrichment: "
            f"{'enabled' if provider.get('enabled') else 'disabled'}"
            f" | provider: {provider.get('provider_id') or key}"
            f" | status: {provider.get('status') or 'unknown'}"
        )
    return lines


def _company_profile_lines(profile: dict[str, Any]) -> list[str]:
    lines = [
        f"- 公司名称：{profile.get('stock_name') or '暂无'}",
        f"- 行业归属：{profile.get('sw_l1') or '暂无'} / {profile.get('sw_l2') or '暂无'} / {profile.get('sw_l3') or '暂无'}",
        f"- 主营业务：{profile.get('main_business') or '暂无'}",
    ]
    if profile.get("main_product_types"):
        lines.append(f"- 产品类型：{profile.get('main_product_types')}")
    if profile.get("main_product_names"):
        lines.append(f"- 主要产品：{profile.get('main_product_names')}")
    if profile.get("ths_concepts"):
        lines.append(f"- 关联概念：{profile.get('ths_concepts')}")
    if profile.get("comparable_companies"):
        lines.append(f"- 可比公司：{profile.get('comparable_companies')}")
    if profile.get("competitor_companies"):
        lines.append(f"- 竞争对手：{profile.get('competitor_companies')}")
    return lines


def _infer_customer_profile(profile: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(profile.get("main_business") or ""),
            str(profile.get("main_product_types") or ""),
            str(profile.get("main_product_names") or ""),
        ]
    )
    if any(token in text for token in ["计量", "终端", "设备", "制造", "通讯设备", "工业", "B端"]):
        return "更偏向 ToB / 制造与终端交付场景"
    if any(token in text for token in ["芯片", "集成电路", "安全芯片", "半导体"]):
        return "更偏向 B 端器件/方案供给场景"
    if any(token in text for token in ["平台", "服务", "SaaS", "软件"]):
        return "更偏向 软件 / 服务输出场景"
    return "客户与交付场景当前以主营业务描述为准"


def _infer_operation_model(profile: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(profile.get("main_business") or ""),
            str(profile.get("sw_l2") or ""),
            str(profile.get("sw_l3") or ""),
        ]
    )
    if any(token in text for token in ["制造", "组装", "零部件", "终端"]):
        return "更接近 制造 / 组装 / 硬件交付 型模式"
    if any(token in text for token in ["芯片", "集成电路", "设计"]):
        return "更接近 芯片设计 / 器件交付 型模式"
    if any(token in text for token in ["平台", "软件", "SaaS"]):
        return "更接近 平台 / 软件服务 型模式"
    return "运营模式需结合更多业务披露进一步确认"


def _competitiveness_lines(profile: dict[str, Any], latest_row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    sw_l2 = profile.get("sw_l2") or "暂无"
    sw_l3 = profile.get("sw_l3") or "暂无"
    lines.append(f"- 行业位点：当前处于 {sw_l2} / {sw_l3} 赛道，竞争判断应围绕该细分环节展开。")
    if profile.get("comparable_companies"):
        lines.append(f"- 可比对标：当前证据层给出的可比公司为 {profile.get('comparable_companies')}。")
    elif profile.get("competitor_companies"):
        lines.append(f"- 竞争对手：当前证据层记录的竞争对手为 {profile.get('competitor_companies')}。")
    else:
        lines.append("- Peer 对标：当前证据层未覆盖显式可比公司字段，竞争判断需谨慎。")
    revenue = latest_row.get("revenue")
    cashflow = latest_row.get("operating_cashflow")
    eps = latest_row.get("eps")
    support_bits: list[str] = []
    if revenue not in (None, ""):
        support_bits.append(f"最新营收 {_fmt_yi(revenue)}")
    if eps not in (None, ""):
        support_bits.append(f"EPS {_fmt_num(eps, 4)}")
    if cashflow not in (None, ""):
        support_bits.append(f"经营现金流 {_fmt_yi(cashflow)}")
    if support_bits:
        lines.append(f"- 经营支撑：{'，'.join(support_bits)}。")
    return lines


def _business_model_section(profile: dict[str, Any], latest_row: dict[str, Any]) -> list[str]:
    customer_profile = _infer_customer_profile(profile)
    operation_model = _infer_operation_model(profile)
    product_mix = profile.get("main_product_types") or profile.get("main_product_names") or "当前仅有主营业务概述，产品层拆分有限"
    if profile.get("comparable_companies"):
        moat = f"当前主要对标 {profile.get('comparable_companies')}，可围绕细分赛道位置和执行力理解竞争壁垒。"
    elif profile.get("competitor_companies"):
        moat = f"当前竞争对手记录为 {profile.get('competitor_companies')}，竞争壁垒判断需结合公开披露进一步确认。"
    else:
        moat = "当前证据层缺少明确 peer 对标字段，竞争壁垒判断需谨慎。"
    return [
        "### 2.1 商业模式与核心竞争力",
        f"- 商业模式拆解：主营收入主要来自 {profile.get('main_business') or '暂无'}，客户侧更接近 {customer_profile}，运营组织方式 {operation_model}。",
        f"- 产品与解决方案：{product_mix}。",
        f"- 核心竞争力判断：{moat}",
        "- 阅读方式：这里不是简单判断“好不好”，而是回答公司究竟靠什么赚钱、靠什么守住利润、靠什么和同行拉开差距。",
        *_competitiveness_lines(profile, latest_row),
    ]


def _industry_driver_reasons(profile: dict[str, Any], industry: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    concepts = _split_csv_like(profile.get("ths_concepts"), limit=4)
    sw_l1 = str(profile.get("sw_l1") or "")
    sw_l2 = str(profile.get("sw_l2") or "")
    main_business = str(profile.get("main_business") or "")
    prosperity = industry.get("prosperity_score")

    if concepts:
        reasons.append(f"概念线索集中在 {', '.join(concepts)}")
    if sw_l1 == "电子":
        if any(token in (main_business + sw_l2) for token in ["半导体", "芯片", "集成电路"]):
            reasons.append("半导体国产替代与算力链需求仍是核心观察点")
        elif any(token in (main_business + sw_l2) for token in ["消费电子", "零部件", "终端"]):
            reasons.append("消费电子链条修复与终端出货节奏是主要驱动线索")
    if sw_l1 == "计算机":
        reasons.append("AI 应用落地与数字化投入节奏是主要驱动线索")
    if sw_l1 == "电力设备":
        reasons.append("新能源装机、储能与设备更新节奏是主要驱动线索")
    if industry.get("sector_resonance"):
        reasons.append("板块同步强化已被本地共振数据确认")
    if isinstance(prosperity, (int, float)) and float(prosperity) >= 8:
        reasons.append("当前行业景气分处于高位")
    return reasons[:3]


def _industry_driver_section(profile: dict[str, Any], industry: dict[str, Any]) -> list[str]:
    reasons = _industry_driver_reasons(profile, industry)
    if not reasons:
        text = "当前驱动因素仍以行业景气和主营业务线索为主，外部驱动解释需更多公开证据补充。"
    else:
        text = "；".join(reasons) + "。"
    return [
        "### 4.2 短期增速与驱动因素",
        f"- 驱动因素：{text}",
        "- 边界说明：当前以本地结构化证据和行业线索做解释，不把驱动因素外推成交易结论。",
    ]


def _industry_policy_tech_reasons(profile: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    concepts = _split_csv_like(profile.get("ths_concepts"), limit=8)
    sw_l1 = str(profile.get("sw_l1") or "")
    sw_l2 = str(profile.get("sw_l2") or "")
    main_business = str(profile.get("main_business") or "")
    news_provider = ((evidence.get("enrichment") or {}).get("providers") or {}).get("public_news_digest") or {}
    news_status = str(news_provider.get("status") or "")

    if sw_l1 == "电子":
        if any(token in concepts for token in ["第三代半导体", "先进封装", "共封装光学(CPO)", "存储芯片", "芯片概念"]):
            reasons.append("技术迭代线索集中在半导体、先进封装或算力链相关主题")
        if any(token in concepts for token in ["物联网", "智能电网", "汽车电子", "储能"]):
            reasons.append("应用扩散方向更多体现在智能终端、电力电子与车载电子场景")
    if sw_l1 == "计算机":
        reasons.append("技术变革更多围绕 AI 应用、云化与数字化投入展开")
    if sw_l1 == "电力设备":
        reasons.append("政策与技术线索更多围绕新能源装机、储能与电网升级")
    if "国企改革" in concepts or "央企国企改革" in concepts:
        reasons.append("存在国企改革相关概念，政策节奏可能影响市场预期")
    if news_status == "ready_for_external_news_supplement":
        reasons.append("如需更细的政策或事件解释，可按需叠加公开新闻摘要")
    if any(token in (main_business + sw_l2) for token in ["医疗", "器械", "医药"]):
        reasons.append("监管与产品迭代节奏往往是行业景气变化的重要变量")
    return reasons[:3]


def _industry_policy_tech_section(profile: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    reasons = _industry_policy_tech_reasons(profile, evidence)
    if not reasons:
        text = "当前更多只能确认行业与概念层线索，政策和技术变革细节仍需外部公开事件补充。"
    else:
        text = "；".join(reasons) + "。"
    return [
        "### 4.3 政策环境与技术变革",
        f"- 政策/技术线索：{text}",
        "- 边界说明：当前只做结构化线索整理，不把概念或政策主题直接转成行情判断。",
    ]


def _industry_cycle_judgement(profile: dict[str, Any], industry: dict[str, Any], state_core: dict[str, Any]) -> str:
    prosperity = industry.get("prosperity_score")
    sector_resonance = industry.get("sector_resonance")
    etf_state = str(industry.get("etf_state_hex") or "")
    market_phase = str(state_core.get("market_phase") or "")
    sw_l1 = str(profile.get("sw_l1") or "")

    if isinstance(prosperity, (int, float)) and float(prosperity) >= 8 and sector_resonance:
        return f"{sw_l1 or '当前行业'}处于高景气并伴随板块同步强化，更接近顺周期推进阶段。"
    if etf_state in {"E", "F"} and market_phase in {"progression", "constructive", "emerging"}:
        return f"{sw_l1 or '当前行业'}当前更像处于景气延续或恢复中的阶段。"
    if isinstance(prosperity, (int, float)) and float(prosperity) < 5:
        return f"{sw_l1 or '当前行业'}景气度偏低，更像处于等待修复或重新确认阶段。"
    if market_phase == "transition":
        return f"{sw_l1 or '当前行业'}仍偏过渡状态，行业节奏和个股分化都需要继续观察。"
    return f"{sw_l1 or '当前行业'}当前处于中性到偏积极的观察区间，后续更看共振是否延续。"


def _industry_cycle_section(profile: dict[str, Any], industry: dict[str, Any], state_core: dict[str, Any]) -> list[str]:
    judgement = _industry_cycle_judgement(profile, industry, state_core)
    prosperity = industry.get("prosperity_score")
    lines = [
        "### 4.4 行业周期与整体判断",
        f"- 周期位置：{judgement}",
        f"- 结构依据：景气分 {_fmt_num(prosperity)}，ETF State {industry.get('etf_state_hex') or '暂无'}，市场阶段 {state_core.get('market_phase') or '暂无'}。",
    ]
    if industry.get("sector_resonance") is True:
        lines.append(f"- 共振验证：当前已出现行业共振，确认家数 {industry.get('sector_resonance_count') if industry.get('sector_resonance_count') is not None else '暂无'}。")
    else:
        lines.append("- 共振验证：当前未见明确行业共振，整体判断仍需更多同步信号确认。")
    return lines


def _market_expectation_lines(market_views: dict[str, Any]) -> list[str]:
    rating_distribution = market_views.get("rating_distribution") or {}
    latest_report = market_views.get("latest_report") or {}
    lines = ["### 5.1 市场预期"]
    if rating_distribution:
        total = sum(int(v or 0) for v in rating_distribution.values())
        dist = " / ".join(f"{k} {v}" for k, v in rating_distribution.items())
        lines.append(f"- 机构覆盖：当前已收录 {total} 条公开评级记录，评级分布为 {dist}。")
    else:
        lines.append("- 机构覆盖：当前未取到可用的公开评级分布。")
    if latest_report:
        lines.append(
            f"- 最新公开观点：{latest_report.get('institution') or '暂无'} 于 {latest_report.get('date') or '暂无'} 给出 {latest_report.get('rating') or '暂无'}。"
        )
    else:
        lines.append("- 最新公开观点：当前未取到可用的最新研报记录。")
    lines.append("- 说明：这里展示的是公开市场预期与卖方覆盖情况，不代表系统自己的盈利预测或目标价判断。")
    return lines


def _growth_logic_section(profile: dict[str, Any], industry: dict[str, Any], state_core: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    latest = rows[0] if rows else {}
    drivers: list[str] = []
    main_business = str(profile.get("main_business") or "")
    concepts = _split_csv_like(profile.get("ths_concepts"), limit=4)
    if concepts:
        drivers.append(f"概念线索主要集中在 {', '.join(concepts)}")
    if any(token in main_business for token in ["芯片", "半导体", "集成电路"]):
        drivers.append("增长线索更多围绕国产替代、算力链需求和下游电子景气变化")
    elif any(token in main_business for token in ["设备", "终端", "制造", "零部件"]):
        drivers.append("增长线索更多围绕订单、出货节奏和下游资本开支变化")
    elif any(token in main_business for token in ["软件", "平台", "服务"]):
        drivers.append("增长线索更多围绕客户扩张、产品渗透和数字化投入")
    prosperity = industry.get("prosperity_score")
    if isinstance(prosperity, (int, float)) and float(prosperity) >= 7:
        drivers.append("当前行业景气度处于中高位，对增长线索有一定顺风支撑")
    if state_core.get("ef_count") in {2, 3}:
        drivers.append("多周期结构已有一定共振，说明增长线索正在被价格结构部分验证")
    lines = [
        "### 3.2 发展前景与增长线索",
        f"- 主营延展：{profile.get('main_business') or '暂无主营描述，增长线索需谨慎。'}",
        f"- 最新收入：{_fmt_yi(latest.get('revenue'))}，净利润：{_fmt_yi(latest.get('net_profit'))}。",
    ]
    if drivers:
        lines.append(f"- 增长线索：{'；'.join(drivers)}。")
    else:
        lines.append("- 增长线索：当前仅能确认公司处于既有主营赛道，后续增长驱动仍需更多公开证据。")
    lines.append("- 边界说明：这里是增长线索观察，不构成未来业绩预测。")
    return lines


def _governance_observation_section(profile: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    latest = rows[0] if rows else {}
    debt_ratio = latest.get("debt_ratio")
    roe = latest.get("roe")
    notes = []
    if debt_ratio not in (None, ""):
        notes.append(f"最新资产负债率 { _fmt_percent(debt_ratio) }")
    if roe not in (None, ""):
        notes.append(f"ROE { _fmt_percent(roe) }")
    if profile.get("competitor_companies") or profile.get("comparable_companies"):
        notes.append("已具备可比公司/竞争对手线索，便于做治理与执行力的横向观察")
    lines = [
        "### 3.4 管理与治理观察",
        "- 当前证据层缺少完整的管理团队与治理数据库，因此这里只做弱观察，不输出强判断。",
    ]
    if notes:
        lines.append(f"- 可观察线索：{'；'.join(notes)}。")
    lines.append("- 使用方式：更适合作为补充观察项，而不是独立下结论模块。")
    return lines


def _event_watch_section(profile: dict[str, Any], market_views: dict[str, Any]) -> list[str]:
    latest_report = market_views.get("latest_report") or {}
    lines = [
        "### 3.5 事件观察",
        "- 当前只把公开事件、机构更新和结构变化作为观察线索，不当作交易级催化剂。",
    ]
    if latest_report:
        lines.append(
            f"- 最近公开更新：{latest_report.get('institution') or '暂无'} 于 {latest_report.get('date') or '暂无'} 发布了 {latest_report.get('rating') or '暂无'} 观点。"
        )
    concepts = _split_csv_like(profile.get("ths_concepts"), limit=5)
    if concepts:
        lines.append(f"- 主题观察：{', '.join(concepts)}。")
    lines.append("- 使用方式：事件只做验证和跟踪，不替代多周期结构判断。")
    return lines


def _financial_trend_observation_section(evidence: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    lines = ["### 4. 盈利趋势观察（非预测）"]
    limited_text = _limited_module_text("financial_trend", evidence)
    if limited_text:
        lines.append(limited_text)
    if rows:
        for row in rows[:4]:
            lines.append(
                f"- {row.get('report_period')}: 营收 {_fmt_yi(row.get('revenue'))}，净利润 {_fmt_yi(row.get('net_profit'))}，EPS {_fmt_num(row.get('eps'), 4)}，ROE {_fmt_percent(row.get('roe'))}"
            )
    else:
        lines.append("- 财务趋势数据暂缺。")
    lines.append("- 说明：以上为历史趋势描述，不构成未来盈利预测。")
    return lines


def _valuation_reference_section(evidence: dict[str, Any], valuation: dict[str, Any]) -> list[str]:
    lines = ["### 5. 估值参考（非结论）"]
    valuation_text = _limited_module_text("valuation_reference", evidence)
    if valuation_text:
        lines.append(valuation_text)
    if any(valuation.get(field) is not None for field in ["pe_ttm", "pb", "market_cap", "ps"]):
        lines.append(
            f"- PE(TTM)：{_fmt_pe(valuation.get('pe_ttm'))}，PB：{_fmt_num(valuation.get('pb'))}，PS：{_fmt_num(valuation.get('ps'))}，总市值：{_fmt_yi(valuation.get('market_cap'))}。"
        )
    else:
        lines.append("- 估值参考数据暂缺。")
    lines.append("- 说明：这里只做历史与横向参考，不输出合理估值、目标价或投资建议。")
    return lines


def _risk_limit_section(shared: dict[str, Any], risks: dict[str, Any]) -> list[str]:
    lines = ["### 7. 风险与限制"]
    rendered_any_risk = False
    for section, title in [
        ("financial_risks", "财务风险"),
        ("industry_risks", "行业风险"),
        ("valuation_risks", "估值风险"),
        ("data_risks", "数据风险"),
    ]:
        values = risks.get(section) or []
        if values:
            rendered_any_risk = True
            lines.append(f"- {title}：")
            for item in values:
                lines.append(f"  - {_clean_risk_text(_risk_text(item))}")
    if not rendered_any_risk:
        lines.append("- 当前未检出明确风险提示，但这不代表未来没有风险。")
    lines.append(f"- 数据充分度：{_status_label(shared['overall_completeness'])}")
    lines.append(f"- 数据来源：{shared['source_summary']}")
    return lines


def _value_combo_research_card(
    evidence: dict[str, Any],
    shared: dict[str, Any],
    profile: dict[str, Any],
    industry: dict[str, Any],
    state_core: dict[str, Any],
    overlay: dict[str, Any],
    valuation: dict[str, Any],
    market_views: dict[str, Any],
    risks: dict[str, Any],
    rows: list[dict[str, Any]],
) -> str:
    financial_quality_lines = (
        _financial_quality_section(evidence, profile, rows)
        if rows
        else ["### 3.3 盈利质量与财务健康", "- 当前财务趋势样本不足。"]
    )
    lines = [
        f"## {shared['stock_name']} 价值研究组合卡",
        "",
        "### 1. 研究说明",
        "- 当前输出不是机械拼接字段，而是沿用你们原有价值投研工作流里可复用的行业/公司/财务框架，把它们按当前数据边界重新组织进研究卡。",
        "- 它不是恢复 8 大块长报告，也不是直接给投资建议；更像把原来长报告中真正有研究价值的骨架抽出来，放回当前 Hermass 链路里。",
        f"- 当前 State 组合：{shared['state_combo']}；结构解读：{_state_structure_explanation(state_core)}。",
        "",
        "### 2. 公司概况",
        *_company_profile_lines(profile),
        "",
        *_industry_competition_section(profile, industry),
        "",
        *_industry_driver_section(profile, industry),
        "",
        *_industry_policy_tech_section(profile, evidence),
        "",
        *_industry_cycle_section(profile, industry, state_core),
        "",
        *_business_model_section(profile, _latest_financial_row(evidence)),
        "",
        *_growth_logic_section(profile, industry, state_core, rows),
        "",
        *financial_quality_lines,
        "",
        *_governance_observation_section(profile, rows),
        "",
        *_event_watch_section(profile, market_views),
        "",
        *_financial_trend_observation_section(evidence, rows),
        "",
        *_valuation_reference_section(evidence, valuation),
        "",
        *_market_expectation_lines(market_views),
        "",
        *_risk_limit_section(shared, risks),
    ]
    if overlay.get("fit_strategy"):
        lines.insert(
            5,
            f"- 当前结构覆盖：{overlay.get('fit_strategy')}，{overlay.get('strategy_environment_fit') or '待观察'}，生命周期={overlay.get('lifecycle_stage') or '暂无'}。",
        )
    return _apply_compliance("\n".join(lines))


def _trend_direction(rows: list[dict[str, Any]], field: str) -> str:
    values = [row.get(field) for row in rows[:3] if row.get(field) not in (None, "")]
    if len(values) < 2:
        return "样本不足"
    try:
        latest = float(values[0])
        earliest = float(values[-1])
    except Exception:
        return "样本不足"
    if latest > earliest:
        return "较前期改善"
    if latest < earliest:
        return "较前期回落"
    return "基本持平"


def _same_quarter_metric_items(evidence: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return evidence.get("financial_trend", {}).get(key) or []


def _industry_metric_reason(company_profile: dict[str, Any], metric: str) -> str:
    text = " ".join(
        [
            str(company_profile.get("sw_l1") or ""),
            str(company_profile.get("sw_l2") or ""),
            str(company_profile.get("sw_l3") or ""),
            str(company_profile.get("main_business") or ""),
            str(company_profile.get("main_product_types") or ""),
        ]
    )
    bank_like = any(token in text for token in ["银行", "保险", "证券", "多元金融"])
    light_asset_chip = any(token in text for token in ["半导体", "芯片", "集成电路", "软件", "SaaS"])
    heavy_asset = any(token in text for token in ["电力", "公用事业", "地产", "建筑", "钢铁", "化工", "机械", "制造"])

    if metric == "revenue":
        return "营收同比通常更能反映需求、订单和出货节奏。"
    if metric == "net_profit":
        return "净利润同比通常更能反映盈利兑现和经营弹性。"
    if metric == "operating_cashflow":
        if bank_like:
            return "金融行业经营现金流口径可比性弱，因此默认不作为前台核心判断。"
        if heavy_asset or not light_asset_chip:
            return "这类制造/硬件交付型业务里，经营现金流同比对经营质量更关键。"
        return "对轻资产或器件设计类行业，经营现金流短期波动通常不是第一优先级。"
    return ""


def _same_quarter_commentary(evidence: dict[str, Any], company_profile: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    metric_specs = [
        ("revenue_yoy_same_quarter", "收入同比", "revenue"),
        ("net_profit_yoy_same_quarter", "净利润同比", "net_profit"),
        ("operating_cashflow_yoy_same_quarter", "经营现金流同比", "operating_cashflow"),
    ]
    for key, label, metric_name in metric_specs:
        items = _same_quarter_metric_items(evidence, key)
        if not items:
            continue
        item = items[0]
        value = item.get("value")
        if value in (None, ""):
            continue
        direction = "增长" if float(value) >= 0 else "下降"
        reason = _industry_metric_reason(company_profile, metric_name)
        lines.append(
            f"- {label}：最新可比口径为 {item.get('report_period')} 对比 {item.get('base_period')}，{direction} {abs(float(value)):.1f}%。{reason}"
        )
    return lines


def _financial_quality_section(evidence: dict[str, Any], company_profile: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    latest = rows[0] if rows else {}
    revenue_dir = _trend_direction(rows, "revenue")
    profit_dir = _trend_direction(rows, "net_profit")
    cashflow_dir = _trend_direction(rows, "operating_cashflow")
    debt_ratio = latest.get("debt_ratio")
    debt_text = "暂无"
    if debt_ratio not in (None, ""):
        try:
            debt_val = float(debt_ratio)
            debt_text = f"{debt_val:.1f}%"
        except Exception:
            debt_text = str(debt_ratio)
    net_margin = latest.get("net_margin")
    gross_margin = latest.get("gross_margin")
    margin_bits: list[str] = []
    if gross_margin not in (None, ""):
        margin_bits.append(f"毛利率 {_fmt_percent(gross_margin)}")
    if net_margin not in (None, ""):
        margin_bits.append(f"净利率 {_fmt_percent(net_margin)}")
    margin_text = "，".join(margin_bits) if margin_bits else "利润率细项当前覆盖不足"
    lines = [
        "### 3.1 盈利质量与财务健康",
        f"- 成长性观察：最近 3 个可比报告期口径下，营收表现 {revenue_dir}，净利润表现 {profit_dir}。如果两者同向改善，说明经营扩张与利润兑现相对一致；若利润明显弱于收入，则后续更要看成本、费用与需求质量。",
        f"- 盈利质量观察：最新口径下 {margin_text}，EPS {_fmt_num(latest.get('eps'), 4)}，ROE {_fmt_percent(latest.get('roe'))}。这一组指标更适合回答“赚得多不多、赚得稳不稳、回报是否够厚”。",
        f"- 现金流与财务健康：经营现金流表现 {cashflow_dir}，最新值 {_fmt_yi(latest.get('operating_cashflow'))}；资产负债率 {debt_text}。如果利润改善但现金流迟迟跟不上，就要对利润含金量保持谨慎。",
    ]
    lines.extend(_same_quarter_commentary(evidence, company_profile))
    return lines


def _split_csv_like(text: Any, limit: int = 4) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    items = [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    return items[:limit]


def _industry_competition_section(profile: dict[str, Any], industry: dict[str, Any]) -> list[str]:
    sw_l1 = profile.get("sw_l1") or "暂无"
    sw_l2 = profile.get("sw_l2") or "暂无"
    sw_l3 = profile.get("sw_l3") or "暂无"
    chain_position = industry.get("chain_position") or "暂无"
    prosperity = industry.get("prosperity_score")
    prosperity_text = _fmt_num(prosperity)
    concepts = _split_csv_like(profile.get("ths_concepts"), limit=4)
    comparable = _split_csv_like(profile.get("comparable_companies"), limit=4)
    competitors = _split_csv_like(profile.get("competitor_companies"), limit=4)

    competition_regime = "更像集中度较高、关键环节话语权更重要的赛道"
    if comparable or competitors:
        competition_regime = "至少已有一组可比公司或竞争对手可用于横向观察"
    lines = [
        "### 4.1 产业链与竞争格局",
        f"- 产业链定位：公司当前归属 {sw_l1} / {sw_l2} / {sw_l3}，本地产业链位置标记为 {chain_position}。这决定了它更像赚“技术溢价”、制造效率，还是下游渠道与品牌的钱。",
        f"- 行业景气：当前景气分 {prosperity_text}，ETF State {industry.get('etf_state_hex') or '暂无'}。从结构上看，当前赛道{competition_regime}。",
    ]
    if industry.get("sector_resonance") is True:
        lines.append(
            f"- 板块共振：当前检测到行业共振，确认家数 {industry.get('sector_resonance_count') if industry.get('sector_resonance_count') is not None else '暂无'}。"
        )
    elif industry.get("sector_resonance") is False:
        lines.append("- 板块共振：当前未形成明显行业共振，竞争格局更应回到公司自身经营与产品位置。")
    if comparable:
        lines.append(f"- 可比公司：{', '.join(comparable)}。后续理解竞争壁垒时，应优先看它与这些 Peer 在产品定位、成本结构和执行效率上的差异。")
    elif competitors:
        lines.append(f"- 竞争对手：{', '.join(competitors)}。当前更适合把竞争判断放在具体细分环节里，而不是只看泛行业标签。")
    else:
        lines.append("- 可比/竞争公司：本地证据层覆盖不足，因此当前只能先给出产业链位置判断，不能把竞争格局说得过满。")
    if concepts:
        lines.append(f"- 相关概念：{', '.join(concepts)}。")
    lines.append("- 说明：这里优先继承“产业链全景 + 价值分布 + 核心玩家对标”的研究框架，但当前输出仍以本地结构化证据为底，不把缺失数据硬补成结论。")
    return lines


def _latest_financial_row(evidence: dict[str, Any]) -> dict[str, Any]:
    rows = evidence.get("financial_trend", {}).get("period_rows") or []
    return rows[0] if rows else {}


def _shared_context(evidence: dict[str, Any]) -> dict[str, Any]:
    profile = evidence.get("company_profile", {})
    state_core = evidence.get("state_core", {})
    completeness = evidence.get("completeness", {})
    latest_financial = _latest_financial_row(evidence)
    return {
        "stock_code": profile.get("stock_code") or evidence.get("meta", {}).get("stock_code", ""),
        "stock_name": profile.get("stock_name") or evidence.get("meta", {}).get("stock_name", ""),
        "report_date": evidence.get("meta", {}).get("as_of_date", ""),
        "latest_report_period": evidence.get("financial_trend", {}).get("latest_report_period", ""),
        "overall_completeness": completeness.get("overall", "missing"),
        "major_risks": _top_risks(evidence.get("risk_flags", {}), limit=3),
        "source_summary": _source_summary(evidence.get("source_map", {})),
        "disclaimer": DEFAULT_DISCLAIMER,
        "state_combo": "/".join(
            [
                state_core.get("mn1_state_hex", "") or "-",
                state_core.get("w1_state_hex", "") or "-",
                state_core.get("d1_state_hex", "") or "-",
            ]
        ),
        "ef_count": state_core.get("ef_count"),
        "main_business_short": profile.get("main_business", ""),
        "eps_latest": latest_financial.get("eps"),
        "roe_latest": latest_financial.get("roe"),
        "pe_ttm": evidence.get("valuation_reference", {}).get("pe_ttm"),
    }


def _overlay_explanation(overlay: dict[str, Any], state_core: dict[str, Any]) -> str:
    if overlay.get("fit_strategy"):
        return ""
    combo = "/".join(
        [
            state_core.get("mn1_state_hex", "") or "-",
            state_core.get("w1_state_hex", "") or "-",
            state_core.get("d1_state_hex", "") or "-",
        ]
    )
    return f"当前 State 组合为 {combo}，尚未进入策略信号账本的有效覆盖范围。"


def _recent_period_source_keys(evidence: dict[str, Any], field: str, limit: int = 2) -> list[str]:
    rows = evidence.get("financial_trend", {}).get("period_rows") or []
    out: list[str] = []
    for row in rows[:limit]:
        period = row.get("report_period")
        if period:
            out.append(f"financial_trend.period_rows[{period}].{field}")
    return out


def _limited_module_text(module_name: str, evidence: dict[str, Any]) -> str:
    status = evidence.get("completeness", {}).get(module_name)
    if status == "partial":
        return f"{module_name} 数据当前仅部分覆盖，以下结论需谨慎参考。"
    if status in {"missing", "not_available"}:
        return f"{module_name} 数据当前缺失，暂不输出该模块结论。"
    return ""


def _apply_compliance(text: str) -> str:
    result = check_compliance(text)
    filtered = result.filtered_text
    if result.needs_disclaimer():
        filtered = apply_disclaimer(filtered)
    elif DEFAULT_DISCLAIMER not in filtered:
        filtered = filtered.rstrip() + "\n\n" + DEFAULT_DISCLAIMER
    return filtered


def _normalize_render_profile(render_profile: str | None) -> str:
    profile = str(render_profile or "full").strip().lower()
    if profile not in RENDER_PROFILES:
        return "full"
    return profile


def format_quick_research_card(evidence: dict[str, Any]) -> str:
    shared = _shared_context(evidence)
    profile = evidence.get("company_profile", {})
    industry = evidence.get("industry_state", {})
    overlay = evidence.get("strategy_fit_overlay", {})
    latest_financial = _latest_financial_row(evidence)
    risks = _top_risks(evidence.get("risk_flags", {}), limit=2)
    lines = [
        f"{shared['stock_name']}（{shared['stock_code']}）",
        "",
        f"结论摘要：当前处于 {shared['state_combo']} 的 State 环境，整体数据充分度为 {_status_label(shared['overall_completeness'])}。",
        f"主营：{profile.get('main_business') or '暂无'}",
        f"State：{_state_quick_display(evidence.get('state_core', {}))}",
        f"行业：{profile.get('sw_l1') or '暂无'} 景气 { _fmt_num(industry.get('prosperity_score')) } / ETF {industry.get('etf_state_hex') or '暂无'}",
        f"财务：营收 { _fmt_yi(latest_financial.get('revenue')) } | EPS { _fmt_num(latest_financial.get('eps'), 4) } | ROE { _fmt_percent(latest_financial.get('roe')) }",
    ]
    if overlay and overlay.get("fit_strategy"):
        lines.append(
            f"策略适配：{overlay.get('fit_strategy')}（{overlay.get('strategy_environment_fit') or '待观察'}）"
        )
    else:
        lines.append(f"策略适配：当前无策略信号覆盖，仅展示 State 环境。{_overlay_explanation(overlay, evidence.get('state_core', {}))}")
    if risks:
        lines.append(f"主要风险：{_join_risk_texts(risks)}")
    lines.append(f"数据充分度：{_status_label(shared['overall_completeness'])}")
    lines.append(f"数据来源：{shared['source_summary']}")
    return _apply_compliance("\n".join(lines))


def format_deep_research_card(evidence: dict[str, Any], render_profile: str = "full") -> str:
    profile_mode = _normalize_render_profile(render_profile)
    shared = _shared_context(evidence)
    profile = evidence.get("company_profile", {})
    industry = evidence.get("industry_state", {})
    state_core = evidence.get("state_core", {})
    overlay = evidence.get("strategy_fit_overlay", {})
    valuation = evidence.get("valuation_reference", {})
    market_views = evidence.get("market_views", {})
    risks = evidence.get("risk_flags", {})
    rows = evidence.get("financial_trend", {}).get("period_rows") or []
    latest_financial = rows[0] if rows else {}

    if profile_mode == "value":
        return _value_combo_research_card(
            evidence=evidence,
            shared=shared,
            profile=profile,
            industry=industry,
            state_core=state_core,
            overlay=overlay,
            valuation=valuation,
            market_views=market_views,
            risks=risks,
            rows=rows,
        )

    lines = [
        f"## {shared['stock_name']} 深度研究卡",
        "",
        "### 1. 结论摘要",
        f"{shared['stock_name']} 当前处于 {shared['state_combo']} 的 State 组合，整体数据充分度为 {_status_label(shared['overall_completeness'])}。",
        "",
        "### 2. 公司概况",
    ]
    lines.extend(_company_profile_lines(profile))
    if profile_mode == "full":
        lines.extend(["", *_business_model_section(profile, latest_financial)])

    lines.extend(["", "### 3. 财务趋势"])
    limited_text = _limited_module_text("financial_trend", evidence)
    if limited_text:
        lines.append(limited_text)
    if rows:
        for row in rows:
            lines.append(
                f"- {row.get('report_period')}: 营收 {_fmt_yi(row.get('revenue'))}，净利润 {_fmt_yi(row.get('net_profit'))}，EPS {_fmt_num(row.get('eps'), 4)}，经营现金流 {_fmt_yi(row.get('operating_cashflow'))}"
            )
    else:
        lines.append("财务趋势数据暂缺。")

    if profile_mode != "quick":
        lines.extend(["", *_financial_quality_section(evidence, profile, rows)]) if rows else None

    lines.extend(["", "### 4. 行业景气 / State 环境"])
    industry_text = _limited_module_text("industry_state", evidence)
    if industry_text:
        lines.append(industry_text)
    else:
        lines.append(
            f"- 行业景气：{profile.get('sw_l1') or '暂无'}，景气分 {_fmt_num(industry.get('prosperity_score'))}，ETF State {industry.get('etf_state_hex') or '暂无'}（ef={industry.get('etf_ef_count') if industry.get('etf_ef_count') is not None else '暂无'}）"
        )
    lines.append(
        f"- State 核心：MN1={state_core.get('mn1_state_hex') or '-'} / W1={state_core.get('w1_state_hex') or '-'} / D1={state_core.get('d1_state_hex') or '-'}，ef_count={state_core.get('ef_count') if state_core.get('ef_count') is not None else '暂无'}，市场阶段={state_core.get('market_phase') or '暂无'}"
    )
    lines.append(f"- 结构解读：{_state_structure_explanation(state_core)}")
    if state_core.get("state_prior_view"):
        lines.append(f"- 节奏先验：{state_core.get('state_prior_view')}")
    for item in _state_duration_lines(state_core):
        lines.append(f"- State 持续性：{item}")
    if overlay.get("fit_strategy"):
        lines.append(
            f"- 策略适配：{overlay.get('fit_strategy')}，{overlay.get('strategy_environment_fit') or '待观察'}，生命周期={overlay.get('lifecycle_stage') or '暂无'}"
        )
    else:
        lines.append(f"- 策略适配：当前无策略信号覆盖。{_overlay_explanation(overlay, state_core)}")
    lines.extend(["", *_phase1_resonance_lines(evidence)])
    if profile_mode == "full":
        lines.extend(["", *_industry_competition_section(profile, industry)])
        lines.extend(["", *_industry_driver_section(profile, industry)])
        lines.extend(["", *_industry_policy_tech_section(profile, evidence)])
        lines.extend(["", *_industry_cycle_section(profile, industry, state_core)])

    if profile_mode in {"standard", "full"}:
        lines.extend(["", "### 5. 估值参考"])
        valuation_text = _limited_module_text("valuation_reference", evidence)
        if valuation_text:
            lines.append(valuation_text)
        if any(valuation.get(field) is not None for field in ["pe_ttm", "pb", "market_cap", "ps"]):
            lines.append(
                f"- PE(TTM)：{_fmt_pe(valuation.get('pe_ttm'))}，PB：{_fmt_num(valuation.get('pb'))}，PS：{_fmt_num(valuation.get('ps'))}，总市值：{_fmt_yi(valuation.get('market_cap'))}"
            )
        else:
            lines.append("估值参考数据暂缺。")
        lines.append("仅供研究参考，不构成建议。")

    if profile_mode == "full":
        market_view_text = _limited_module_text("market_views", evidence)
        if market_view_text:
            lines.extend(["", "### 5.1 市场预期", market_view_text])
        elif market_views.get("rating_distribution") or market_views.get("latest_report"):
            lines.extend(["", *_market_expectation_lines(market_views)])
        else:
            lines.extend(["", "### 5.1 市场预期", "market_views 数据当前缺失，暂不输出该模块结论。"])

        enrichment_lines = _enrichment_summary_lines(evidence)
        if enrichment_lines:
            lines.extend(["", "### 5.2 Enrichment 状态", *enrichment_lines])

    lines.extend(["", "### 6. 风险与限制"])
    rendered_any_risk = False
    for section, title in [
        ("financial_risks", "财务风险"),
        ("industry_risks", "行业风险"),
        ("valuation_risks", "估值风险"),
        ("data_risks", "数据风险"),
    ]:
        values = risks.get(section) or []
        if values:
            rendered_any_risk = True
            lines.append(f"- {title}：")
            for item in values:
                lines.append(f"  - {_clean_risk_text(_risk_text(item))}")
    if not rendered_any_risk:
        lines.append("- 当前未检出明确风险提示，但这不代表未来没有风险。")
    lines.append(f"- 数据充分度：{_status_label(shared['overall_completeness'])}")
    lines.append(f"- 数据来源：{shared['source_summary']}")
    return _apply_compliance("\n".join(lines))


def format_evidence_card(evidence: dict[str, Any]) -> str:
    shared = _shared_context(evidence)
    completeness = evidence.get("completeness", {})
    source_map = evidence.get("source_map", {})
    lines = [
        f"## {shared['stock_name']} 证据卡",
        "",
        f"- 股票代码：{shared['stock_code']}",
        f"- 查询日期：{shared['report_date']}",
        f"- 最新报告期：{shared['latest_report_period'] or '暂无'}",
        f"- 整体充分度：{_status_label(shared['overall_completeness'])}",
        f"- 来源摘要：{shared['source_summary']}",
        "",
        "### 模块充分度",
    ]
    for key in [
        "company_profile",
        "financial_trend",
        "industry_state",
        "state_core",
        "strategy_fit_overlay",
        "valuation_reference",
        "market_views",
        "risk_flags",
    ]:
        lines.append(f"- {key}: {_status_label(completeness.get(key))}")
    lines.extend(
        [
            "",
            "### 评分",
            f"- required_modules_score: {_fmt_num(completeness.get('required_modules_score'), 3)}",
            f"- optional_modules_score: {_fmt_num(completeness.get('optional_modules_score'), 3)}",
            f"- overall_score: {_fmt_num(completeness.get('overall_score'), 3)}",
            "",
            "### State 展示",
            f"- Raw State：{shared['state_combo']}",
            f"- 结构解读：{_state_structure_explanation(evidence.get('state_core', {}))}",
            f"- 节奏先验：{evidence.get('state_core', {}).get('state_prior_view') or '暂无'}",
            f"- MN1 Alias：{_state_alias(evidence.get('state_core', {}).get('mn1_state_hex') or '')}",
            f"- W1 Alias：{_state_alias(evidence.get('state_core', {}).get('w1_state_hex') or '')}",
            f"- D1 Alias：{_state_alias(evidence.get('state_core', {}).get('d1_state_hex') or '')}",
        ]
    )
    for item in _state_duration_lines(evidence.get("state_core", {})):
        lines.append(f"- State 持续性：{item}")
    lines.extend(
        [
            "",
            *_phase1_resonance_lines(evidence),
            "",
            "### 关键来源",
        ]
    )
    shown = 0
    key_candidates = ["company_profile.main_business"]
    key_candidates.extend(_recent_period_source_keys(evidence, "revenue", limit=2))
    key_candidates.extend(["state_core.d1_state_hex", "valuation_reference.pe_ttm", "market_views.rating_distribution"])
    for key in key_candidates:
        entry = source_map.get(key)
        if entry:
            lines.append(
                f"- {key}: {entry.get('source_type')} / {entry.get('source_table') or 'derived'} / {entry.get('source_field') or '-'} / {entry.get('updated_at')}"
            )
            shown += 1
    if shown == 0:
        lines.append("- 暂无关键来源摘要。")

    source_policy = evidence.get("meta", {}).get("source_policy") or {}
    banned_patterns = source_policy.get("banned_source_patterns") or []
    if banned_patterns:
        lines.extend(
            [
                "",
                "### 信源边界",
                "- 默认优先使用 tier_1_core / tier_2_high 结构化来源。",
                f"- 禁用信源模式：{', '.join(str(item) for item in banned_patterns[:8])}{' ...' if len(banned_patterns) > 8 else ''}",
            ]
        )

    enrichment_lines = _enrichment_summary_lines(evidence)
    if enrichment_lines:
        lines.extend(["", "### Enrichment 状态", *enrichment_lines])
    provider_lines = _provider_status_lines(evidence)
    for provider_line in provider_lines:
        lines.append(f"- {provider_line}")

    explained_risks: list[tuple[str, Any]] = []
    for section, title in [
        ("financial_risks", "财务风险"),
        ("industry_risks", "行业风险"),
        ("valuation_risks", "估值风险"),
        ("data_risks", "数据风险"),
    ]:
        for item in evidence.get("risk_flags", {}).get(section) or []:
            explained_risks.append((title, item))
    if explained_risks:
        lines.extend(["", "### 风险说明层"])
        for title, item in explained_risks:
            risk_text = _risk_text(item)
            significance = _risk_significance(item)
            reason = _risk_reason(item)
            base = f"- {title} | 重要性：{significance or '未标注'} | {risk_text}"
            if reason:
                base += f" | 原因：{reason}"
            lines.append(base)

    data_risks = evidence.get("risk_flags", {}).get("data_risks") or []
    if data_risks:
        lines.extend(["", "### 来源局限", *[f"- {_risk_text(item)}" for item in data_risks]])
    return _apply_compliance("\n".join(lines))
