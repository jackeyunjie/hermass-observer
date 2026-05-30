import hashlib
import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Optional

import duckdb

from hermass_platform.chat.intent_router import classify_intent, get_agent_for_intent
from hermass_platform.chat.compliance_filter import (
    check_compliance,
    apply_disclaimer,
    get_system_prompt,
)
from hermass_platform.chat.conversation_manager import get_conversation_manager
from hermass_platform.cognitive.cognitive_ledger import record_event, BehaviorEvent
from hermass_platform.research.external_research_evidence import build_external_research_evidence
from hermass_platform.research.external_research_formatters import (
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger("hermass.lark")

AGENT_DISPATCH = {
    "market_analyst": "hermass_platform.agents.market_analyst",
    "strategy_advisor": "hermass_platform.agents.strategy_advisor",
    "cognitive_detective": "hermass_platform.agents.cognitive_detective",
    "risk_guardian": "hermass_platform.agents.risk_guardian",
    "coach": "hermass_platform.agents.coach",
    "monetization_butler": "hermass_platform.agents.monetization_butler",
}

INTENT_AGENT_METHODS = {
    "market_phase": ("market_analyst", "analyze_market_environment"),
    "sector_heat": ("market_analyst", "analyze_industry_heat"),
    "macro_outlook": ("market_analyst", "analyze_market_environment"),
    "my_profile": ("cognitive_detective", "get_user_profile"),
    "my_fit": ("strategy_advisor", "analyze_strategy_fit"),
    "my_risk": ("risk_guardian", "assess_portfolio_risk"),
    "strategy_fit": ("strategy_advisor", "analyze_strategy_fit"),
    "signal_explore": ("strategy_advisor", "explore_top_signals"),
    "exit_rule": ("risk_guardian", "get_stop_loss_reference"),
    "learn_topic": ("coach", None),
    "practice": ("coach", None),
    "subscription": ("monetization_butler", "query_subscription_status"),
    "benefits": ("monetization_butler", "query_tier_comparison"),
    "sector_resonance": ("market_analyst", None),
}

SYSTEM_PROMPT = get_system_prompt()


def verify_signature(timestamp: str, nonce: str, body: str, secret: str) -> bool:
    if not secret:
        return True
    raw = f"{timestamp}{nonce}{secret}{body}"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    return True


def _resolve_foundation_db() -> str:
    from hermass_platform.slice.slice_engine import find_latest_foundation_db
    db_path = find_latest_foundation_db()
    if db_path is None:
        return ""
    return str(db_path)


def _get_help_message() -> str:
    return (
        "**Hermass Observer — AI 认知交易中台**\n\n"
        "我可以帮你做这些：\n\n"
        "**个股研究**\n"
        "  • 000021 快速研究 / 000021 怎么看\n"
        "  • 000021 深度研究 / 深度分析 000021\n"
        "  • 000021 标准版研究 / 000021 完整版研究\n"
        "  • 000021 证据卡 / 000021 数据来源\n\n"
        "**市场分析**\n"
        "  • 市场怎么样 / 大盘怎么样\n"
        "  • 电子行业怎么样 / 医药行业怎么样\n\n"
        "**策略信号**\n"
        "  • 有什么好信号 / 推荐策略\n"
        "  • VCP 策略怎么样 / 2560 策略怎么样\n\n"
        "**认知检测**\n"
        "  • 我的交易画像 / 我的风格是什么\n"
        "  • 我的持仓有什么风险\n\n"
        "**止损参考**\n"
        "  • 000001 止损 / 600519 止损\n\n"
        "**学习训练**\n"
        "  • 什么是 State / VCP 是什么\n"
        "  • 给我出题 / 做练习\n\n"
        "**会员服务**\n"
        "  • 我的会员 / 怎么升级 / 高级版有什么功能\n\n"
        "回复「帮助」可以随时查看这个列表。"
    )


def _canonical_stock_code(stock_code: str) -> str:
    digits = "".join(ch for ch in stock_code if ch.isdigit())
    if len(digits) != 6:
        return stock_code.upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _resolve_stock_code_by_name(company_name: str) -> str:
    db_path = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
    if not db_path.exists():
        return ""
    query = company_name.strip()
    if not query:
        return ""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """
            SELECT stock_code, stock_name
            FROM (
                SELECT DISTINCT stock_code, stock_name, as_of_date
                FROM ifind_industry_chain_profile
                WHERE stock_name IS NOT NULL
            )
            WHERE stock_name = ?
            ORDER BY as_of_date DESC, stock_code
            LIMIT 1
            """,
            [query],
        ).fetchone()
        if row:
            return str(row[0]).upper()

        row = con.execute(
            """
            SELECT stock_code, stock_name
            FROM (
                SELECT DISTINCT stock_code, stock_name, as_of_date
                FROM ifind_industry_chain_profile
                WHERE stock_name IS NOT NULL
            )
            WHERE stock_name LIKE ?
            ORDER BY
              CASE WHEN stock_name LIKE ? THEN 0 ELSE 1 END,
              as_of_date DESC,
              stock_code
            LIMIT 1
            """,
            [f"%{query}%", f"{query}%"],
        ).fetchone()
        if row:
            return str(row[0]).upper()

        row = con.execute(
            """
            SELECT stock_code, stock_name
            FROM ifind_tracking_pool
            WHERE stock_name = ?
            ORDER BY last_seen DESC, stock_code
            LIMIT 1
            """,
            [query],
        ).fetchone()
        if row:
            return str(row[0]).upper()
    except Exception:
        logger.exception("Stock name resolution failed for %s", company_name)
    finally:
        con.close()
    return ""


def _extract_research_target(user_message: str) -> str:
    codes = re.findall(r"(?<!\d)\d{6}(?!\d)", user_message)
    if codes:
        return _canonical_stock_code(codes[0])
    cleaned = re.sub(r"[，。！？、,.!?：:（）()【】\\[\\]]", " ", user_message)
    cleaned = re.sub(
        r"(快速研究|深度研究|深度分析|详细分析|研究一下|个股研究|研究卡|证据卡|数据来源|可信度|怎么看|研究)",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    candidates = [token for token in cleaned.split(" ") if len(token) >= 2]
    candidates.sort(key=len, reverse=True)
    for name in candidates:
        stock_code = _resolve_stock_code_by_name(name)
        if stock_code:
            return stock_code
    return ""


def _detect_research_card_request(user_message: str) -> dict[str, str] | None:
    text = user_message.strip()
    stock_code = _extract_research_target(text)
    if not stock_code:
        return None
    if any(keyword in text for keyword in ("证据卡", "数据来源", "来源卡", "可信度")):
        return {"card_type": "evidence", "stock_code": stock_code}
    if any(keyword in text for keyword in ("标准版研究", "标准版分析", "标准研究")):
        return {"card_type": "deep", "stock_code": stock_code, "render_profile": "standard"}
    if any(keyword in text for keyword in ("完整版研究", "完整版分析", "完整研究")):
        return {"card_type": "deep", "stock_code": stock_code, "render_profile": "full"}
    if any(keyword in text for keyword in ("深度研究", "深度分析", "详细分析", "研究卡")):
        return {"card_type": "deep", "stock_code": stock_code, "render_profile": "full"}
    if any(keyword in text for keyword in ("怎么看", "快速研究", "研究一下", "个股研究", "研究")):
        return {"card_type": "quick", "stock_code": stock_code}
    return None


def _render_research_card(user_message: str, foundation_db: str) -> str:
    request = _detect_research_card_request(user_message)
    if not request:
        return ""
    evidence = build_external_research_evidence(
        stock_code=request["stock_code"],
        as_of_date=str(date.today()),
        foundation_db=foundation_db,
    )
    card_type = request["card_type"]
    if card_type == "deep":
        return format_deep_research_card(evidence, render_profile=request.get("render_profile", "full"))
    if card_type == "evidence":
        return format_evidence_card(evidence)
    return format_quick_research_card(evidence)


def _record_research_event(user_id: str, user_message: str) -> None:
    request = _detect_research_card_request(user_message)
    if not request:
        return
    record_event(
        BehaviorEvent(
            user_id=user_id,
            event_type="stock_lookup",
            payload={
                "message": user_message[:200],
                "intent": "research_card",
                "agent": "research_response",
                "stock_code": request.get("stock_code", ""),
                "card_type": request.get("card_type", ""),
                "render_profile": request.get("render_profile", ""),
            },
        )
    )


def _dispatch_agent(user_id: str, intent: str, user_message: str, foundation_db: str) -> str:
    config = INTENT_AGENT_METHODS.get(intent)
    if config is None:
        return "抱歉，我暂时无法处理这个请求。你可以试试问我：市场环境、策略适配、我的画像、交易知识等。"

    agent_name, method_name = config

    if agent_name == "coach":
        return _handle_coach_intent(intent, user_message, user_id)

    if intent == "sector_resonance":
        return _handle_sector_resonance(foundation_db)

    module_path = AGENT_DISPATCH.get(agent_name)
    if module_path is None:
        return "系统内部错误：Agent 未注册。"

    try:
        import importlib
        mod = importlib.import_module(module_path)
        func = getattr(mod, method_name)

        kwargs = {"user_id": user_id}

        if method_name in ("analyze_market_environment", "analyze_industry_heat",
                           "analyze_strategy_fit", "explore_top_signals",
                           "assess_portfolio_risk", "get_stop_loss_reference"):
            kwargs["foundation_db"] = foundation_db

        if method_name == "explore_top_signals":
            kwargs["top_n"] = 10
        elif method_name == "analyze_industry_heat":
            from hermass_platform.chat.intent_router import classify_intent
            result_info = classify_intent(user_message)
            if "电子" in user_message:
                kwargs["sw_l1_name"] = "电子"
            elif "半导体" in user_message:
                kwargs["sw_l1_name"] = "电子"
            elif "新能源" in user_message:
                kwargs["sw_l1_name"] = "电力设备"
            elif "医药" in user_message:
                kwargs["sw_l1_name"] = "医药生物"

        if method_name == "get_stop_loss_reference":
            import re
            codes = re.findall(r'(?<!\d)\d{6}(?!\d)', user_message)
            if codes:
                kwargs["stock_code"] = codes[0] + ".SZ"
            else:
                kwargs["stock_code"] = "000001.SZ"

        result = func(**kwargs)

        if isinstance(result, dict) and result.get("status") == "ok":
            summary = result.get("summary", "")
            return summary
        elif isinstance(result, dict) and result.get("status") == "error":
            return f"抱歉，查询遇到问题：{'; '.join(result.get('errors', ['未知错误']))}"
        else:
            return str(result)

    except Exception as e:
        logger.exception(f"Agent dispatch failed: {agent_name}.{method_name}")
        return f"系统处理请求时出现异常，请稍后重试。"


def _handle_sector_resonance(foundation_db: str) -> str:
    try:
        from hermass_platform.slice.industry_slice import detect_sector_resonance
        results = detect_sector_resonance(foundation_db)
    except Exception as e:
        logger.exception("Sector resonance detection failed")
        return f"板块共振检测失败：{e}"

    if not results:
        return "今日未检测到明显的板块共振信号。市场可能处于个股分化阶段，建议关注具体标的而非板块。"

    lines = ["**🔥 今日板块共振信号**\n"]
    lines.append(f"检测到 {len(results)} 个行业出现共振（同日 3 只以上从 ef<2 跳至 ef≥2）：\n")

    for r in results:
        conf = r["confidence"]
        icon = "🟢" if conf == "高" else ("🟡" if conf == "中" else "🟠")
        lines.append(
            f"{icon} **{r['sw_l1']}** — {r['resonance_count']} 只共振（置信度：{conf}）"
        )

        top3 = r["signals"][:3]
        code_mentions = []
        for s in top3:
            code_mentions.append(f"{s['stock_code'].split('.')[0]}（ef={s['ef_count']}）")
        lines.append(f"  → {'、'.join(code_mentions)}")
        lines.append("")

    lines.append(
        "\n**📊 解读**\n"
        "板块共振 = 同一行业内多只股票同时进入强势状态。"
        "置信度「高」（5只以上）= 板块级别启动信号。\n"
        "建议关注共振行业中的高 ef_count 标的，"
        "结合 State 多周期验证后再决策。"
    )

    return "\n".join(lines)


def _handle_coach_intent(intent: str, user_message: str, user_id: str) -> str:
    from hermass_platform.agents.coach import (
        search_knowledge,
        get_learning_path,
        generate_quiz,
        get_topic_list,
    )

    if intent == "learn_topic":
        words = [w for w in user_message.replace("什么是", "").replace("什么叫", "").replace("解释", "").split() if len(w) > 1]
        results = search_knowledge(words[:3])
        if not results:
            results = search_knowledge([user_message])
        if not results:
            topics = get_topic_list()
            topic_names = "、".join(t["title"] for t in topics)
            return f"抱歉，没有找到相关内容。当前知识库覆盖：{topic_names}。你可以试试问'什么是 State'或'VCP 是什么'。"

        lines = []
        for r in results[:3]:
            lines.append(f"【{r['topic_title']}·{r['concept_name']}】\n{r['answer']}")
        return "\n\n".join(lines)

    elif intent == "practice":
        quiz = generate_quiz(count=2)
        lines = []
        for i, q in enumerate(quiz, 1):
            lines.append(f"**题目 {i}**\n{q['question']}\n\n💡 提示：{q['hint']}\n\n📖 答案：{q['answer']}")
        return "\n\n---\n\n".join(lines)

    return "你可以问我：学习 State 概念、VCP 策略、2560 策略、风险管理，或者做一道练习题。"


def handle_lark_message(
    user_id: str,
    user_message: str,
    chat_id: str = "",
    session_id: str = "",
) -> str:
    intent_result = classify_intent(user_message)
    intent = intent_result.intent
    agent_name = intent_result.agent

    if user_message.strip().lower() in ("帮助", "help", "功能", "能做什么", "怎么用", "使用说明"):
        return _get_help_message()

    foundation_db = _resolve_foundation_db()
    if not foundation_db:
        return "系统正在初始化数据，请稍后再试。"

    research_reply = _render_research_card(user_message, foundation_db)
    if research_reply:
        _record_research_event(user_id, user_message)
        return _wrap_lark_markdown(research_reply)

    conv_mgr = get_conversation_manager()
    session = conv_mgr.get_or_create(user_id, session_id)
    conv_mgr.add_message(session.session_id, "user", user_message, intent, agent_name)

    record_event(BehaviorEvent(
        user_id=user_id,
        event_type=intent if intent in BehaviorEvent.VALID_TYPES else "market_query",
        payload={"message": user_message[:200], "intent": intent, "agent": agent_name},
    ))

    response_text = _dispatch_agent(user_id, intent, user_message, foundation_db)

    from hermass_platform.chat.response_enricher import enrich_stock_response, enrich_market_response
    if intent in ("signal_explore", "exit_rule") and foundation_db:
        pass
    elif intent in ("market_phase", "sector_heat"):
        try:
            import duckdb
            con = duckdb.connect(foundation_db, read_only=True)
            row = con.execute(
                "SELECT SUM(CASE WHEN ef_count>=2 THEN 1 ELSE 0 END), COUNT(*) FROM d1_perspective_state "
                "WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)"
            ).fetchone()
            con.close()
            if row and row[1]:
                response_text = enrich_market_response(response_text, row[0], row[1])
        except Exception:
            pass
    elif intent in ("my_fit", "strategy_fit"):
        from hermass_platform.chat.response_enricher import _STATS as stats
        st = stats["strategy_tracking"]
        response_text += (
            "\n\n**📊 验证数据参考**\n"
            f"四策略信号综合追踪（{st['n']} 样本）："
            f"观察胜率 {st['win_rate']}，"
            f"平均超额 {st['excess_return']}。"
        )

    conv_mgr.add_message(session.session_id, "assistant", response_text, intent, agent_name)

    compliance_result = check_compliance(response_text)
    if not compliance_result.passed:
        logger.warning(f"Compliance violation for user {user_id}: {compliance_result.violations}")
        response_text = "系统检测到应答中存在不合规内容，已拦截。请重试。"
    else:
        response_text = compliance_result.filtered_text

    if compliance_result.is_trade_related:
        response_text = apply_disclaimer(response_text)

    response_text = _wrap_lark_markdown(response_text)

    return response_text


def _wrap_lark_markdown(text: str) -> str:
    lines = text.split("\n")
    result = []
    for line in lines:
        orig = line.strip()
        line = orig

        if line.startswith("### "):
            line = "**" + line[4:] + "**"
        elif line.startswith("## "):
            line = "**" + line[3:] + "**"
        elif line.startswith("# "):
            line = "**" + line[2:] + "**"

        if line.startswith("- "):
            line = "  • " + line[2:]

        result.append(line)
    return "\n".join(result)


def verify_url_challenge(challenge: str, token: str = "") -> dict:
    return {"challenge": challenge}
