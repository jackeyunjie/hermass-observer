"""盯盘任务场景 —— 诊断 → 任务注册（暂不走 LLM，直接规则化注册）"""

from __future__ import annotations

from typing import Any

from agently_adapter.agents import diagnoser


def run(user_input: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """盯盘任务场景：先诊断个股状态，再返回任务确认卡。"""
    symbol = context.get("symbol", "")
    if not symbol:
        return {
            "answer": "我可以帮你建立盯盘任务，但还需要你给出 6 位股票代码。",
            "why": "盯盘指令至少需要明确跟踪对象，才能绑定后续提醒条件。",
            "multi_cycle_view": "盯盘本质上是在多周期环境里持续观察一只股票是否进入你关心的状态。",
            "single_cycle_position": "先明确股票，再判断是盯周线关键位、D1 支撑，还是长期跟踪。",
            "avoid": "先不用重复描述条件，先把股票代码补完整。",
            "next_actions": [{"label": "打开研究页", "url": "/research?stock_code=000021.SZ"}],
            "sources": ["watch_command"],
            "freshness_note": "",
        }

    # Step 1: 诊断 —— 快速体检，为盯盘条件提供基准
    diag_ctx = {
        "symbol": symbol,
        "name": context.get("stock_name", ""),
        "states": context.get("stock_states", {}),
        "ef_count": context.get("ef_count", 0),
        "capital_flow": context.get("capital_flow", {}),
        "breakout_status": context.get("breakout_status", ""),
        "sustained_days": context.get("sustained_days", 0),
    }
    diag_result = diagnoser.run(diag_ctx)
    if diag_result is None:
        diag_result = {"conclusion": f"{symbol} 状态未知"}

    # Step 2: 返回任务确认卡（规则化，不走融合 Agent）
    conclusion = diag_result.get("conclusion", "")
    return {
        "answer": f"已识别盯盘任务：{symbol}。当前诊断：{conclusion}",
        "why": "盯盘任务需要基于当前状态设定合理的触发条件。",
        "multi_cycle_view": "盯盘条件会围绕多周期环境展开，比如周线关键位突破、行业共振、或大周期结构变化。",
        "single_cycle_position": "当前先把提醒通道补齐，后续再按你指定的单周期位置条件触发通知。",
        "avoid": "先不用重复发送股票代码或条件，直接补邮箱即可。",
        "next_actions": [{"label": "打开执行页", "url": "/watchlist"}],
        "sources": ["watch_command", "diagnoser"],
        "freshness_note": "任务尚未注册，需要补充邮箱和触发条件。",
        "remembered_stock_code": symbol,
        "remembered_email": "",
    }
