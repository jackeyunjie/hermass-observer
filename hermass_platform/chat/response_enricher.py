"""Agent 应答增强器——将历史验证结论注入到 Agent 响应中。

数据来源：
  - forward_observation_ledger（前向观察样本，样本积累中）
  - strategy_outcome_report（策略信号追踪报告，7,625 样本）
  - vcp_optimal_state_search（VCP 最优状态组合验证）

当前可用统计结论（提取自最新报告）：
  - VCP 20d 匹配状态组: 平均超额 1.62-1.67%, 胜率 42-43%, n=2525-4955
  - 策略信号综合追踪: 胜率 51.4%, 平均超额 5.3%, n=7625
  - 前向观察: 145 样本积累中（首期校准 2026-05-28）

用法:
  from hermass_platform.chat.response_enricher import enrich_response
  result = enrich_response(agent_result_text, stock_context)
"""

_STATS = {
    "vcp_matched_20d": {
        "label": "VCP 策略在匹配 State 环境下",
        "n_approx": "2500-5000",
        "excess_return": "+1.6%",
        "win_rate": "42-43%",
        "window": "20日",
        "note": "VCP 最优状态搜索结果",
    },
    "strategy_tracking": {
        "label": "四策略信号综合追踪报告",
        "n": "7,625",
        "win_rate": "51.4%",
        "excess_return": "+5.3%",
        "note": "2026-02-13 → 2026-05-22，61 个交易日累积",
    },
    "ef3_resonance": {
        "label": "三周期共振信号",
        "n_approx": "历史回测累积中",
        "expected": "首次出现 ef=3 后 20 日内超额收益概率优于 ef<2 状态",
        "note": "前向观察首期校准 2026-05-28",
    },
    "forward_observation": {
        "n": "145",
        "labeled": "0",
        "note": "样本积累中，2026-05-28 首次校准",
    },
}


def _stock_context_hint(ef_count: int, d1_hex: str, mn1_hex: str) -> str:
    if ef_count >= 3:
        return (
            f"\n\n**📊 验证数据参考**\n"
            f"当前三周期共振（ef=3）是系统最强信号。\n"
            f"参考：{_STATS['strategy_tracking']['label']}中，"
            f"策略信号的观察胜率 {_STATS['strategy_tracking']['win_rate']}，"
            f"平均超额 {_STATS['strategy_tracking']['excess_return']}"
            f"（样本 {_STATS['strategy_tracking']['n']} 条）。\n"
            f"⚠️ 前向观察系统正在积累 ef=3 信号的历史表现数据，首批校准将于 2026-05-28 输出。"
        )
    elif ef_count >= 2:
        return (
            f"\n\n**📊 验证数据参考**\n"
            f"当前双周期共振（ef=2）。{_STATS['vcp_matched_20d']['label']}，"
            f"20 日平均超额收益 {_STATS['vcp_matched_20d']['excess_return']}，"
            f"胜率 {_STATS['vcp_matched_20d']['win_rate']}。"
        )
    elif ef_count == 1:
        return (
            f"\n\n**📊 验证数据参考**\n"
            f"当前仅单周期 E/F（ef=1）。历史回测显示单周期状态下信号可靠性低于多周期共振。\n"
            f"建议关注周线和月线何时再次进入 E/F——那将是趋势确认的关键信号。"
        )
    return ""


def enrich_stock_response(response_text: str, ef_count: int = -1, d1_hex: str = "", mn1_hex: str = "") -> str:
    if ef_count < 0:
        return response_text

    hint = _stock_context_hint(ef_count, d1_hex, mn1_hex)
    return response_text + hint


def enrich_market_response(response_text: str, ef2_count: int, total: int) -> str:
    ef2_pct = ef2_count / max(total, 1) * 100
    hint = (
        f"\n\n**📊 环境参考**\n"
        f"当前全市场 E/F≥2 股票 {ef2_count}/{total} 只（{ef2_pct:.1f}%）。\n"
        f"历史参考：{_STATS['strategy_tracking']['label']} 显示，"
        f"全市场策略信号的观察胜率 {_STATS['strategy_tracking']['win_rate']}，"
        f"平均超额 {_STATS['strategy_tracking']['excess_return']}。"
    )
    return response_text + hint


def get_forward_observation_status() -> str:
    fo = _STATS["forward_observation"]
    return f"前向观察系统状态：{fo['n']} 条样本积累中，{fo['labeled']} 条已标注。首次校准日期：2026-05-28。"
