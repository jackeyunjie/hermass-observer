"""统一问答入口 —— 场景化多 Agent 编排的顶层门面。

用法（web/main.py 只改 1 行）：
    from agently_adapter.qa_entry import handle
    result = handle(user_input, context)

约束：
- 本层只做「路由 → 工具预取 → 场景执行 → 返回」四件事。
- 调用方仍优先准备业务上下文；缺失的市场/个股/产业链证据由受控 ToolRegistry 补齐。
- 任何 Agent 调用失败都返回 None，调用方（web/main.py）应回退到规则回答。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from agently_adapter.agents import router
from agently_adapter.scenarios import get_scenario_module, get_scenario_tools
from agently_adapter.tools import run_tool

# ── 复合场景配置 ──────────────────────────────────────────────────────────

COMPOUND_PAIRS: list[tuple[str, str, list[str], list[str]]] = [
    (
        "watch_command",
        "industry_scan",
        ["盯着", "提醒", "突破", "止损", "帮我盯", "盯着它"],
        ["行业", "板块", "产业链", "什么行业", "它的行业"],
    ),
]


def _has_keywords(msg: str, keywords: list[str]) -> bool:
    return any(k in msg for k in keywords)


def _should_compound(primary: str, secondary: str, user_input: str) -> bool:
    if not primary or not secondary or primary == secondary:
        return False
    msg = user_input.strip().lower()
    pair = {primary, secondary}
    for p, s, p_kws, s_kws in COMPOUND_PAIRS:
        if pair == {p, s} and _has_keywords(msg, p_kws) and _has_keywords(msg, s_kws):
            return True
    return False


def _compound_fallback_secondary(primary: str, user_input: str) -> str:
    msg = user_input.strip().lower()
    for p, s, p_kws, s_kws in COMPOUND_PAIRS:
        if primary == p and _has_keywords(msg, s_kws):
            return s
        if primary == s and _has_keywords(msg, p_kws):
            return p
    return ""


def _execute_compound(
    primary: str,
    secondary: str,
    user_input: str,
    context: dict[str, Any],
    route: dict[str, Any] | None,
) -> dict[str, Any]:
    # 规范化：task_card 提供方（watch_command）先跑，行业/回答提供方后跑
    task_scenario = "watch_command"
    answer_scenario = "industry_scan"
    task_mod = get_scenario_module(task_scenario)
    answer_mod = get_scenario_module(answer_scenario)
    _prepare_scenario_tools(task_scenario, user_input, context)
    _prepare_scenario_tools(answer_scenario, user_input, context)

    task_result = None
    answer_result = None
    try:
        task_result = task_mod.run(user_input, context) if task_mod else None
    except Exception:
        task_result = None

    try:
        answer_result = answer_mod.run(user_input, context) if answer_mod else None
    except Exception:
        answer_result = None

    if task_result is None and answer_result is None:
        return _fallback_response(user_input, context)

    if task_result is None:
        result = dict(answer_result)
        result["freshness_note"] = (
            result.get("freshness_note", "")
            + " 盯盘任务链路暂不可用，仅返回行业分析。"
        ).strip()
    elif answer_result is None:
        result = dict(task_result)
        result["freshness_note"] = (
            result.get("freshness_note", "")
            + " 行业扫描链路暂不可用，仅返回盯盘确认。"
        ).strip()
        result.setdefault("task_card", task_result.get("task_card"))
    else:
        result = dict(answer_result)
        result["task_card"] = task_result.get("task_card")
        result["remembered_stock_code"] = task_result.get("remembered_stock_code", "")
        next_actions = list(task_result.get("next_actions", []))
        for a in answer_result.get("next_actions", []):
            if a not in next_actions:
                next_actions.append(a)
        result["next_actions"] = next_actions

    result.setdefault("mode_used", context.get("mode", "chat"))
    if result.get("provider") is None:
        result["provider"] = "agently_deepseek"
    if result.get("enhancement_used") is None:
        result["enhancement_used"] = True
    result.setdefault("intent", {
        "scenario": [primary, secondary],
        "confidence": route.get("confidence", 0.0) if route else 0.0,
        "secondary_scenario": "",
    })
    _attach_trace(result, context, [primary, secondary])
    return result


def _fallback_response(user_input: str, context: dict[str, Any]) -> dict[str, Any]:
    """当多 Agent 链任何一环失败时，返回一个带说明的兜底结构，让 web 层决定如何展示。"""
    return {
        "answer": "当前 Agently 多 Agent 链路调用失败，已触发规则回退。",
        "why": "Agently 场景化 Agent 编排链路调用失败：某个 Agent 返回异常、超时或结构化输出失败。",
        "multi_cycle_view": "失败不代表数据本身有问题，只是 LLM 链路暂时不可用。",
        "single_cycle_position": "请稍后重试；如果持续失败，应检查 Agently 运行时和模型配置。",
        "avoid": "不要把「链路失败」误解成市场或个股结论。",
        "next_actions": [],
        "sources": ["agently_multi_agent", "rule_fallback"],
        "freshness_note": "Agently 场景化 Agent 编排调用失败。",
        "mode_used": context.get("mode", "chat"),
        "provider": "agently_deepseek",
        "enhancement_used": False,
        "intent": {"scenario": "fallback", "confidence": 0.0, "secondary_scenario": ""},
    }


def handle(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """统一问答入口。

    Args:
        user_input: 用户原始输入
        context: 调用方准备好的上下文，至少应包含：
            - user_type: 方向型/研究型/执行型
            - current_page: 当前页面标识
            - symbol: 当前股票代码（如有）
            - market_data: 市场数据（市场/行业/策略场景需要）
            - stock_states: 个股状态（个股场景需要）
            - value_prompt_pack + value_payload: 价值分析增强（web 层准备）
            - recent_topics / recent_stock_codes / user_focus / user_preferred_scenarios: 记忆上下文
            - 以及其他场景所需的结构化数据

    Returns:
        标准 JSON（answer/why/multi_cycle_view/single_cycle_position/avoid/next_actions/sources/freshness_note）
        或 None（失败时 web 层回退规则回答）
    """
    if not user_input or not user_input.strip():
        return None
    started = time.monotonic()
    context.setdefault("trace_id", str(uuid.uuid4())[:8])

    # 价值分析路径：直接走 prompt-pack 增强的 DeepSeek 调用，不经过场景链
    if context.get("value_prompt_pack"):
        result = _handle_value_analysis(context)
        if result is not None:
            _attach_trace(result, context, ["value_analysis"], started)
        return result

    # 1. 场景路由 —— LLM 判断场景类型
    route = router.run(user_input, context)
    if route is None:
        scenario_name = _keyword_fallback_route(user_input, context)
        secondary = ""
    else:
        scenario_name = route.get("scenario", "chitchat")
        secondary = route.get("secondary_scenario", "")

    if scenario_name == "chitchat":
        return None

    # 1.5 复合关键词兜底：secondary 为空时从关键词推断
    if not secondary:
        secondary = _compound_fallback_secondary(scenario_name, user_input)

    # 复合场景检测：主/次场景配对命中
    if _should_compound(scenario_name, secondary, user_input):
        result = _execute_compound(scenario_name, secondary, user_input, context, route)
        _attach_trace(result, context, [scenario_name, secondary], started)
        return result

    # 场景二次纠偏：当用户问题关键词与次场景更匹配时，切换场景
    scenario_mod = None
    if secondary:
        msg_lower = user_input.strip().lower()
        if secondary == "industry_scan" and any(k in msg_lower for k in ("行业", "板块", "产业链", "什么行业")):
            secondary_mod = get_scenario_module(secondary)
            if secondary_mod is not None:
                scenario_name = secondary
                scenario_mod = secondary_mod

    # 2. 加载场景编排模块（如未在上一步设置）
    if scenario_mod is None:
        scenario_mod = get_scenario_module(scenario_name)
        if scenario_mod is None:
            if secondary:
                scenario_mod = get_scenario_module(secondary)
            if scenario_mod is None:
                return None

    # 3. 准备场景工具结果，再执行场景链
    _prepare_scenario_tools(scenario_name, user_input, context)
    try:
        result = scenario_mod.run(user_input, context)
    except Exception:
        result = None

    if result is None:
        result = _fallback_response(user_input, context)
        _attach_trace(result, context, [scenario_name], started)
        return result

    # 补充元信息
    result.setdefault("mode_used", context.get("mode", "chat"))
    if result.get("provider") is None:
        result["provider"] = "agently_deepseek"
    result.setdefault("enhancement_used", True)
    result.setdefault("intent", {
        "scenario": scenario_name,
        "confidence": route.get("confidence", 0.0) if route else 0.0,
        "secondary_scenario": route.get("secondary_scenario", "") if route else "",
    })
    _attach_trace(result, context, [scenario_name], started)
    return result


def _prepare_scenario_tools(
    scenario_name: str,
    user_input: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run the small deterministic tool prefetch for a scenario."""
    allowed_tools = get_scenario_tools(scenario_name)
    if not allowed_tools:
        return context.setdefault("tool_results", {})

    tool_results = context.setdefault("tool_results", {})
    user = str(context.get("username") or context.get("user_id") or "anonymous")
    trace_id = str(context.get("trace_id") or "")
    symbol = _resolve_symbol(user_input, context)

    def run_once(tool_name: str, params: dict[str, Any] | None = None) -> None:
        if tool_name in tool_results:
            return
        tool_results[tool_name] = run_tool(
            tool_name,
            params or {},
            user=user,
            trace_id=trace_id,
            allowed_tools=allowed_tools,
        )

    if "get_market_phase" in allowed_tools:
        run_once("get_market_phase")
    if symbol and "get_stock_state" in allowed_tools:
        run_once("get_stock_state", {"stock_code": symbol})
    if symbol and "get_chain_position" in allowed_tools:
        run_once("get_chain_position", {"stock_code": symbol})

    _hydrate_context_from_tools(context)
    return tool_results


def _resolve_symbol(user_input: str, context: dict[str, Any]) -> str:
    symbol = str(context.get("symbol") or context.get("stock_code") or "").strip().upper()
    if symbol:
        return symbol
    import re

    m = re.search(r"\b([0-9]{6})(?:\.(?:SZ|SH))?\b", user_input.strip().upper())
    if not m:
        return ""
    code = m.group(1)
    suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
    return f"{code}.{suffix}"


def _hydrate_context_from_tools(context: dict[str, Any]) -> None:
    tool_results = context.get("tool_results") or {}
    stock_result = tool_results.get("get_stock_state") or {}
    stock_data = stock_result.get("data") if stock_result.get("ok") else None
    if isinstance(stock_data, dict) and stock_data.get("available"):
        context.setdefault("symbol", stock_data.get("stock_code") or "")
        context.setdefault("stock_name", stock_data.get("stock_name") or stock_data.get("stock_code") or "")
        context.setdefault("industry_name", stock_data.get("industry_name") or "")
        context.setdefault("stock_states", stock_data.get("stock_states") or {})
        context.setdefault("ef_count", stock_data.get("ef_count") or 0)
        context.setdefault("capital_flow", stock_data.get("capital_flow") or {})
        context.setdefault("breakout_status", stock_data.get("breakout_status") or "")
        context.setdefault("sustained_days", stock_data.get("sustained_days") or 0)

    market_result = tool_results.get("get_market_phase") or {}
    market_data = market_result.get("data") if market_result.get("ok") else None
    if isinstance(market_data, dict) and market_data.get("available"):
        existing = context.setdefault("market_data", {})
        if isinstance(existing, dict):
            existing.setdefault("phase", market_data)


def _attach_trace(
    result: dict[str, Any],
    context: dict[str, Any],
    scenarios: list[str],
    started: float | None = None,
) -> None:
    tool_results = context.get("tool_results") or {}
    sources = list(result.get("sources") or [])
    for name, payload in tool_results.items():
        source_name = f"tool:{name}"
        if payload.get("ok") and source_name not in sources:
            sources.append(source_name)
    result["sources"] = sources
    trace = dict(result.get("trace") or {})
    trace.setdefault("id", context.get("trace_id", ""))
    trace.setdefault("scenarios", scenarios)
    trace.setdefault("tools", [name for name, payload in tool_results.items() if payload.get("ok")])
    trace.setdefault("tool_errors", {
        name: payload.get("error")
        for name, payload in tool_results.items()
        if not payload.get("ok")
    })
    if started is not None:
        trace["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    result["trace"] = trace


def _keyword_fallback_route(user_input: str, context: dict[str, Any]) -> str:
    """关键词兜底路由（当 LLM 路由失败时使用）。"""
    msg = user_input.strip().lower()

    if any(kw in msg for kw in ("怎么样", "分析", "能买", "能跟踪", "这只股")):
        if context.get("symbol"):
            return "stock_checkup"

    if any(kw in msg for kw in ("行业", "板块", "产业链", "景气")):
        return "industry_scan"

    if any(kw in msg for kw in ("vcp", "2560", "策略", "胜率", "回测")):
        return "strategy_fit"

    if any(kw in msg for kw in ("盯着", "提醒", "突破", "止损")):
        return "watch_command"

    if any(kw in msg for kw in ("什么是", "怎么学", "解释一下", "什么意思")):
        return "learn_topic"

    if any(kw in msg for kw in ("大盘", "市场", "环境", "能不能做", "现在适合")):
        return "market_overview"

    return "chitchat"


def _handle_value_analysis(context: dict[str, Any]) -> dict[str, Any] | None:
    """价值分析增强 —— 统一走 Agently value prompt pack / DeepSeek。"""
    try:
        payload = context.get("value_payload", {})
        if not payload:
            return None

        stock_code = payload.get("stock_code", "")

        from agently_adapter.deepseek import call as deepseek_call
        from agently_adapter.tools import list_tools

        allowed_tools = ["get_market_phase", "get_stock_state", "get_chain_position"]
        result = deepseek_call(
            payload,
            tools=list_tools(allowed_tools),
            allowed_tools=allowed_tools,
            user=str(context.get("username") or context.get("user_id") or "anonymous"),
            trace_id=str(context.get("trace_id") or ""),
        )
        if not result:
            return None

        result.setdefault("remembered_stock_code", stock_code)
        result.setdefault("mode_used", context.get("mode", "chat"))
        if result.get("provider") is None:
            result["provider"] = "agently_deepseek"
        if result.get("enhancement_used") is None:
            result["enhancement_used"] = True
        result.setdefault("intent", {
            "scenario": "value_analysis",
            "confidence": 1.0,
            "secondary_scenario": "",
        })
        return result
    except Exception:
        return None
