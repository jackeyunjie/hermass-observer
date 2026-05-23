#!/usr/bin/env python3
"""
State Detail Query Tool
查询指定股票的多周期状态计算详情
用法: python query_state_detail.py <stock_code> [date]
示例: python query_state_detail.py 002281.SZ 2026-05-18
"""

import sys
import duckdb
from pathlib import Path
from datetime import datetime

# 配置路径
RESEARCH_ROOT = Path("/Users/lv111101/Documents/hongrun-chaos-trading-system")
STATE_DB = RESEARCH_ROOT / "outputs/p116_ashare_d1_native_state_20260518/p116_ashare_d1_native_state.duckdb"
SR_DB = RESEARCH_ROOT / "outputs/p116b_ashare_d1_official_sr_key_positions_20260518/p116b_ashare_d1_official_sr_key_positions.duckdb"


def decode_state(score):
    """解码 state_score 为各维度"""
    if score is None:
        return None
    score_i = int(score)
    sign = -1 if score_i < 0 else 1
    magnitude = abs(score_i)
    base = 0 if magnitude < 8 else 8
    remainder = magnitude - base
    volatility_bit = 1 if remainder & 1 else 0
    position_bit = 2 if remainder & 2 else 0
    trend_bit = 4 if remainder & 4 else 0
    
    hex_map = {0:'0', 1:'1', 2:'2', 3:'3', 8:'8', 9:'9', 10:'A', 11:'B', 12:'C', 13:'D', 14:'E', 15:'F'}
    hex_char = hex_map.get(magnitude, '?')
    if sign < 0:
        hex_char = '-' + hex_char
    
    return {
        'score': score_i,
        'hex': hex_char,
        'base': base,
        'volatility_bit': volatility_bit,
        'position_bit': position_bit,
        'trend_bit': trend_bit,
        'formula': f"{'+' if sign > 0 else '-'}（底座={base} + 波动={volatility_bit} + 位置={position_bit} + 趋势={trend_bit}）= {score_i}"
    }


def query_state(stock_code: str, date: str = None):
    """查询指定股票的状态详情"""
    
    if not STATE_DB.exists():
        print(f"错误: 状态数据库不存在: {STATE_DB}")
        return
    
    conn = duckdb.connect(str(STATE_DB), read_only=True)
    
    # 如果没有指定日期，使用最新日期
    if date is None:
        max_date = conn.execute("""
            SELECT MAX(base_date) FROM ashare_d1_multitf_asof_postclose 
            WHERE stock_code = ?
        """, [stock_code]).fetchone()[0]
        date = str(max_date)
    
    print(f"\n{'='*80}")
    print(f"股票: {stock_code}")
    print(f"日期: {date}")
    print(f"{'='*80}")
    
    # 查询多周期汇总数据
    result = conn.execute("""
        SELECT stock_code, base_date, base_close,
               D_state_hex, D_state_score, D_trend, D_position, D_compression, D_volatility,
               W_state_hex, W_state_score, W_trend, W_position, W_compression, W_volatility,
               MN1_state_hex, MN1_state_score, MN1_trend, MN1_position, MN1_compression, MN1_volatility
        FROM ashare_d1_multitf_asof_postclose
        WHERE stock_code = ? AND base_date = ?
    """, [stock_code, date]).fetchone()
    
    if not result:
        print(f"未找到数据: {stock_code} @ {date}")
        conn.close()
        return
    
    close_price = result[2]
    print(f"\n收盘价: {close_price}")
    print(f"\n{'-'*80}")
    print("多周期状态汇总:")
    print(f"{'-'*80}")
    
    timeframes = [
        ('D1 (日线)', result[3], result[4], result[5], result[6], result[7], result[8]),
        ('W1 (周线)', result[9], result[10], result[11], result[12], result[13], result[14]),
        ('MN1 (月线)', result[15], result[16], result[17], result[18], result[19], result[20]),
    ]
    
    for tf_name, hex_val, score, trend, position, compression, volatility in timeframes:
        decoded = decode_state(score)
        print(f"\n{tf_name}:")
        print(f"  state_hex: {hex_val}")
        print(f"  state_score: {score}")
        print(f"  计算: {decoded['formula']}")
        print(f"  trend: {trend}")
        print(f"  position: {position}")
        print(f"  volatility: {volatility}")
        print(f"  compression: {compression}")
    
    # 查询各周期的详细计算指标
    print(f"\n{'-'*80}")
    print("各周期详细指标:")
    print(f"{'-'*80}")
    
    for tf in ['MN1', 'W1', 'D1']:
        tf_result = conn.execute(f"""
            SELECT close, ma20, ma60, sd20, atr14, atr_pct,
                   high_20, low_20, high_60, low_60, high_120, low_120,
                   position_120, range_compression_20_120, boll_width_20,
                   compression, trend, position, volatility,
                   base_component, volatility_bit, position_bit, trend_bit,
                   bull_context, bear_context, state_abs_score, state_score, state_hex
            FROM ashare_d1_state_timeframe
            WHERE stock_code = ? AND timeframe = ? AND state_date = ?
        """, [stock_code, tf, date]).fetchone()
        
        if tf_result:
            print(f"\n{tf} 详细指标:")
            print(f"  收盘价: {tf_result[0]:.2f}")
            print(f"  MA20: {tf_result[1]:.2f}, MA60: {tf_result[2]:.2f}")
            print(f"  20日区间: {tf_result[6]:.2f} - {tf_result[7]:.2f}")
            print(f"  60日区间: {tf_result[8]:.2f} - {tf_result[9]:.2f}")
            print(f"  120日区间: {tf_result[10]:.2f} - {tf_result[11]:.2f}")
            print(f"  120日位置: {tf_result[12]:.4f}")
            print(f"  区间压缩比: {tf_result[13]:.4f}")
            print(f"  布林带宽度: {tf_result[14]:.4f}")
            print(f"  趋势上下文: 多头={tf_result[23]}, 空头={tf_result[24]}")
    
    conn.close()
    
    # 查询 SR 关键位
    if SR_DB.exists():
        print(f"\n{'-'*80}")
        print("SR 关键位状态:")
        print(f"{'-'*80}")
        
        sr_conn = duckdb.connect(str(SR_DB), read_only=True)
        sr_result = sr_conn.execute("""
            SELECT MN1_sr_support, MN1_sr_resistance, MN1_sr_relation, MN1_sr_breakout_flag, MN1_sr_breakdown_flag,
                   W_sr_support, W_sr_resistance, W_sr_relation, W_sr_breakout_flag, W_sr_breakdown_flag,
                   D_sr_support, D_sr_resistance, D_sr_relation, D_sr_breakout_flag, D_sr_breakdown_flag
            FROM ashare_d1_official_sr_key_positions_postclose
            WHERE stock_code = ? AND base_date = ?
        """, [stock_code, date]).fetchone()
        
        if sr_result:
            print(f"\nMN1 (月线) SR:")
            print(f"  支撑: {sr_result[0]}, 阻力: {sr_result[1]}")
            print(f"  位置关系: {sr_result[2]}")
            print(f"  突破: {sr_result[3]}, 跌破: {sr_result[4]}")
            
            print(f"\nW1 (周线) SR:")
            print(f"  支撑: {sr_result[5]}, 阻力: {sr_result[6]}")
            print(f"  位置关系: {sr_result[7]}")
            print(f"  突破: {sr_result[8]}, 跌破: {sr_result[9]}")
            
            print(f"\nD1 (日线) SR:")
            print(f"  支撑: {sr_result[10]}, 阻力: {sr_result[11]}")
            print(f"  位置关系: {sr_result[12]}")
            print(f"  突破: {sr_result[13]}, 跌破: {sr_result[14]}")
        
        sr_conn.close()
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python query_state_detail.py <stock_code> [date]")
        print("示例: python query_state_detail.py 002281.SZ 2026-05-18")
        sys.exit(1)
    
    stock_code = sys.argv[1]
    date = sys.argv[2] if len(sys.argv) > 2 else None
    
    query_state(stock_code, date)
