"""State Timeline Observer 只读消费 SDK。

为 Strategy Agent / Router / Risk Agent 等提供统一的本地只读接口，
直接消费 `web.services.state_timeline_observer` 的查询能力，不绕 HTTP，
也不写入 AgentMemory 或 Observation Ledger。

使用方式：
    from agently_adapter.tools.state_timeline_reader import load_stock_timeline
    rows = load_stock_timeline("000001.SZ", days=10)
"""

from __future__ import annotations

from typing import Any

from web.services.state_timeline_observer import query_state_timeline, query_stock_timeline


def load_state_timeline(
    symbols: str | None = None,
    symbol_set: str | None = None,
    days: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    filters: dict[str, Any] | None = None,
    user_key: str | None = None,
) -> list[dict[str, Any]]:
    """读取 State Timeline 长表。

    参数：
      symbols: 逗号分隔的股票代码，或 'all'
      symbol_set: 命名集合，支持 'top50' / 'watchlist'
      days: 相对窗口天数
      date_from/date_to: 绝对日期
      filters: 布尔/模式/行业过滤字典
      user_key: 读取 watchlist 时使用

    返回：
      行列表，每行对应一只股票一个交易日。
    """
    result = query_state_timeline(
        symbols=symbols,
        symbol_set=symbol_set,
        date_from=date_from,
        date_to=date_to,
        days=days,
        filters=filters,
        page=1,
        page_size=10000,
        user_key=user_key,
        fetch_all=True,
    )
    if not result.get("ok"):
        raise RuntimeError(f"State Timeline 读取失败: {result.get('error')}")
    return result.get("rows", [])


def load_stock_timeline(
    stock_code: str,
    days: int = 30,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """读取单只股票最近 N 天 State 轨迹。"""
    result = query_stock_timeline(
        stock_code=stock_code,
        days=days,
        date_from=date_from,
        date_to=date_to,
    )
    if not result.get("ok"):
        raise RuntimeError(f"单股 State Timeline 读取失败: {result.get('error')}")
    return result.get("rows", [])


def load_watchlist_timeline(
    user_key: str,
    days: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """读取指定用户的 watchlist State Timeline。"""
    return load_state_timeline(
        symbol_set="watchlist",
        days=days,
        filters=filters,
        user_key=user_key,
    )


def load_top50_timeline(
    days: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """读取 Top50 State Timeline。"""
    return load_state_timeline(
        symbol_set="top50",
        days=days,
        filters=filters,
    )
