#!/usr/bin/env python3
"""
State Calculation Verification Script
验证 state_hex 计算是否正确
用法: python verify_state_calculation.py <stock_code> [date]
"""

import sys
import duckdb
from pathlib import Path

RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
STATE_DB = RESEARCH_ROOT / "outputs/p116_ashare_d1_native_state_20260518/p116_ashare_d1_native_state.duckdb"

# 规则映射表（从数据库中提取的固定规则）
RULES = {
    "position": {
        "insufficient_history": 0,
        "neutral": 0,
        "break_down": 2,
        "break_up": 2,
        "near_resistance": 2,
        "near_support": 2,
    },
    "volatility": {
        "atr_contracting": 0,
        "insufficient_history": 0,
        "neutral": 0,
        "atr_expanding": 1,
        "range_expanded": 1,
    },
    "trend": {
        "insufficient_history": 0,
        "neutral": 0,
        "bear_start": 4,
        "bear_trend": 4,
        "bull_start": 4,
        "bull_trend": 4,
    },
    "compression": {
        "closed": 0,
        "contracting": 0,
        "expanded": 8,
        "insufficient_history": 8,
        "neutral": 8,
    },
}


def calculate_state(compression, trend, position, volatility):
    """
    根据规则计算 state_score 和 state_hex

    计算逻辑:
    1. base_component = RULES['compression'][compression]
    2. trend_bit = RULES['trend'][trend]
    3. position_bit = RULES['position'][position]
    4. volatility_bit = RULES['volatility'][volatility]
    5. state_abs_score = base_component + trend_bit + position_bit + volatility_bit
    6. sign = 1 (bull_context) or -1 (bear_context)
    7. state_score = sign * state_abs_score
    8. state_hex = hex(state_abs_score) with sign
    """
    base = RULES["compression"].get(compression, None)
    t_bit = RULES["trend"].get(trend, None)
    p_bit = RULES["position"].get(position, None)
    v_bit = RULES["volatility"].get(volatility, None)

    if any(v is None for v in [base, t_bit, p_bit, v_bit]):
        return (
            None,
            f"未知值: compression={compression}, trend={trend}, position={position}, volatility={volatility}",
        )

    state_abs_score = base + t_bit + p_bit + v_bit

    # 十六进制映射
    hex_map = {
        0: "0",
        1: "1",
        2: "2",
        3: "3",
        4: "4",
        5: "5",
        6: "6",
        7: "7",
        8: "8",
        9: "9",
        10: "A",
        11: "B",
        12: "C",
        13: "D",
        14: "E",
        15: "F",
    }

    # 判断方向 (bull_context vs bear_context)
    # 简化：如果trend包含bull，则为正；包含bear，则为负
    if "bull" in trend:
        sign = 1
        state_score = state_abs_score
        state_hex = hex_map.get(state_abs_score, "?")
    elif "bear" in trend:
        sign = -1
        state_score = -state_abs_score
        state_hex = "-" + hex_map.get(state_abs_score, "?")
    else:
        # neutral 或 insufficient_history，根据base判断
        if base == 8:
            sign = 1  # 假设为bull context
            state_score = state_abs_score
            state_hex = hex_map.get(state_abs_score, "?")
        else:
            sign = 1
            state_score = state_abs_score
            state_hex = hex_map.get(state_abs_score, "?")

    return {
        "base": base,
        "trend_bit": t_bit,
        "position_bit": p_bit,
        "volatility_bit": v_bit,
        "state_abs_score": state_abs_score,
        "state_score": state_score,
        "state_hex": state_hex,
        "formula": f"{'+' if sign > 0 else '-'}(base={base} + trend={t_bit} + position={p_bit} + volatility={v_bit}) = {state_score}",
    }, None


def verify_stock(stock_code: str, date: str = None):
    """验证指定股票的状态计算"""

    if not STATE_DB.exists():
        print(f"错误: 状态数据库不存在: {STATE_DB}")
        return

    conn = duckdb.connect(str(STATE_DB), read_only=True)

    if date is None:
        max_date = conn.execute(
            """
            SELECT MAX(base_date) FROM ashare_d1_multitf_asof_postclose 
            WHERE stock_code = ?
        """,
            [stock_code],
        ).fetchone()[0]
        date = str(max_date)

    print(f"\n{'=' * 80}")
    print(f"验证股票: {stock_code} @ {date}")
    print(f"{'=' * 80}")

    # 查询所有周期的数据
    results = conn.execute(
        """
        SELECT timeframe, compression, trend, position, volatility,
               base_component, trend_bit, position_bit, volatility_bit,
               state_abs_score, state_score, state_hex,
               bull_context, bear_context
        FROM ashare_d1_state_timeframe
        WHERE stock_code = ? AND state_date = ?
        ORDER BY CASE timeframe 
            WHEN 'D1' THEN 1 
            WHEN 'W1' THEN 2 
            WHEN 'MN1' THEN 3 
            ELSE 4 
        END
    """,
        [stock_code, date],
    ).fetchall()

    all_pass = True

    for r in results:
        timeframe = r[0]
        db_compression = r[1]
        db_trend = r[2]
        db_position = r[3]
        db_volatility = r[4]
        db_base = r[5]
        db_trend_bit = r[6]
        db_pos_bit = r[7]
        db_vol_bit = r[8]
        db_abs_score = r[9]
        db_score = r[10]
        db_hex = r[11]
        db_bull = r[12]
        db_bear = r[13]

        # 使用我们的规则重新计算
        calc, error = calculate_state(db_compression, db_trend, db_position, db_volatility)

        print(f"\n--- {timeframe} ---")
        print(
            f"  DB: compression={db_compression}, trend={db_trend}, position={db_position}, volatility={db_volatility}"
        )
        print(f"  DB: base={db_base}, trend_bit={db_trend_bit}, pos_bit={db_pos_bit}, vol_bit={db_vol_bit}")
        print(f"  DB: abs_score={db_abs_score}, score={db_score}, hex={db_hex}")
        print(f"  DB: bull={db_bull}, bear={db_bear}")

        if error:
            print(f"  ❌ 计算错误: {error}")
            all_pass = False
            continue

        print(f"  CALC: {calc['formula']}")
        print(f"  CALC: hex={calc['state_hex']}")

        # 验证各个字段
        checks = [
            ("base", calc["base"], db_base),
            ("trend_bit", calc["trend_bit"], db_trend_bit),
            ("position_bit", calc["position_bit"], db_pos_bit),
            ("volatility_bit", calc["volatility_bit"], db_vol_bit),
            ("state_abs_score", calc["state_abs_score"], db_abs_score),
            ("state_score", calc["state_score"], db_score),
            ("state_hex", calc["state_hex"], db_hex),
        ]

        for name, calc_val, db_val in checks:
            if calc_val != db_val:
                print(f"  ❌ {name} 不匹配: 计算={calc_val}, 数据库={db_val}")
                all_pass = False
            else:
                print(f"  ✅ {name}: {calc_val}")

    conn.close()

    print(f"\n{'=' * 80}")
    if all_pass:
        print("✅ 所有验证通过！")
    else:
        print("❌ 存在验证失败！")
    print(f"{'=' * 80}\n")

    return all_pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python verify_state_calculation.py <stock_code> [date]")
        print("示例: python verify_state_calculation.py 002281.SZ 2026-05-18")
        sys.exit(1)

    stock_code = sys.argv[1]
    date = sys.argv[2] if len(sys.argv) > 2 else None

    verify_stock(stock_code, date)
