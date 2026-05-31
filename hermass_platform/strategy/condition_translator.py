"""条件块 → DuckDB WHERE 子句翻译层。

纯函数，零 LLM 依赖。
"""

from __future__ import annotations


def translate_block(block: dict[str, object]) -> str:
    """单条件块 → DuckDB WHERE 子句片段。"""
    block_type = block.get("type", "")

    if block_type == "price_cross":
        ma = block.get("ma_period", 20)
        direction = block.get("direction", "above")
        op = ">" if direction == "above" else "<"
        # DuckDB 窗口函数写法
        return (
            f"close {op} AVG(close) OVER ("
            f"PARTITION BY stock_code ORDER BY trade_date "
            f"ROWS BETWEEN {ma - 1} PRECEDING AND CURRENT ROW)"
        )

    if block_type == "volume_ratio":
        compare = block.get("compare", ">")
        ma = block.get("ma_period", 5)
        multiplier = block.get("multiplier", 1.5)
        return (
            f"volume {compare} {multiplier} * AVG(volume) OVER ("
            f"PARTITION BY stock_code ORDER BY trade_date "
            f"ROWS BETWEEN {ma - 1} PRECEDING AND CURRENT ROW)"
        )

    if block_type == "ef_count":
        compare = block.get("compare", ">=")
        value = block.get("value", 2)
        return f"ef_count {compare} {value}"

    if block_type == "state_filter":
        values = block.get("values", [])
        target = block.get("target", "d1")
        if not values:
            return "1=1"
        hex_list = ",".join(f"'{v}'" for v in values)
        col = {"mn1": "mn1_state_hex", "w1": "w1_state_hex", "d1": "d1_state_hex"}.get(target, "d1_state_hex")
        return f"{col} IN ({hex_list})"

    if block_type == "industry_filter":
        mode = block.get("mode", "include")
        codes = block.get("codes", [])
        if not codes:
            return "1=1"
        op = "IN" if mode == "include" else "NOT IN"
        code_list = ",".join(f"'{c}'" for c in codes)
        return f"sw_l1 {op} ({code_list})"

    if block_type == "price_change":
        min_pct = block.get("min", -10)
        max_pct = block.get("max", 10)
        return f"price_change_pct BETWEEN {min_pct} AND {max_pct}"

    if block_type == "stop_loss":
        pct = block.get("pct", 7)
        return f"close >= entry_price * (1 - {pct / 100.0})"

    return "1=1"


def conditions_to_sql(conditions: list[dict[str, object]]) -> str:
    """多条件 → AND 连接的完整 WHERE 子句。"""
    parts = [f"({translate_block(c)})" for c in conditions if c]
    return " AND ".join(parts) if parts else "1=1"
