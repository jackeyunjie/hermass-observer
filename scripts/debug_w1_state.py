#!/usr/bin/env python3
import duckdb

DB_PATH = "outputs/p116_ashare_d1_native_state_v2_20260518/p116_ashare_d1_native_state_v2.duckdb"
conn = duckdb.connect(DB_PATH)

# Check W1 data for the weeks containing 2026-03-12 to 2026-03-10
result = conn.execute("""
    SELECT 
        state_date,
        state_hex,
        state_score,
        base_component,
        trend_bit,
        position_bit,
        volatility_bit,
        position,
        close,
        sr_resistance,
        sr_support,
        trend,
        compression,
        volatility
    FROM ashare_d1_native_state_v2_final 
    WHERE stock_code = '002281.SZ' 
    AND timeframe = 'W1'
    AND state_date BETWEEN '2026-03-06' AND '2026-03-13'
    ORDER BY state_date
""").fetchall()

print("W1 data around 2026-03-12:")
for row in result:
    (d, hex_val, score, base, trend_b, pos_b, vol_b, pos, close, sr_r, sr_s, trend, comp, vol) = row
    print(f"\n  W1 Date: {d}")
    print(f"    close={close}, sr_resistance={sr_r}, sr_support={sr_s}")
    print(f"    position={pos}")
    print(f"    trend={trend}, compression={comp}, volatility={vol}")
    print(f"    base={base}, trend_bit={trend_b}, position_bit={pos_b}, vol_bit={vol_b}")
    print(f"    state_score={score}, state_hex={hex_val}")

# Check D1 data
print("\n" + "=" * 60)
print("D1 dates 2026-03-09 to 2026-03-12:")
print("=" * 60)

result2 = conn.execute("""
    SELECT 
        state_date,
        close,
        sr_resistance,
        sr_support,
        position
    FROM ashare_d1_native_state_v2_final 
    WHERE stock_code = '002281.SZ' 
    AND timeframe = 'D1'
    AND state_date BETWEEN '2026-03-09' AND '2026-03-12'
    ORDER BY state_date
""").fetchall()

for row in result2:
    d, close, sr_r, sr_s, pos = row
    print(f"  {d}: close={close}, D1_sr_r={sr_r}, D1_sr_s={sr_s}, position={pos}")

conn.close()
