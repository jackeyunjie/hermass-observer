import duckdb

cn = duckdb.connect('outputs/p116_foundation_20260522/p116_foundation.duckdb')
us = duckdb.connect('outputs/us_stock/us_foundation.duckdb')

cn_cols = {r[0]: r[1] for r in cn.execute('DESCRIBE d1_perspective_state').fetchall()}
us_cols = {r[0]: r[1] for r in us.execute('DESCRIBE d1_perspective_state').fetchall()}

print('A-share columns:', sorted(cn_cols.keys()))
print('US columns:', sorted(us_cols.keys()))

only_cn = set(cn_cols) - set(us_cols)
only_us = set(us_cols) - set(cn_cols)
print(f'A-share only: {only_cn}')
print(f'US only: {only_us}')

print(f'\nA-share rows: {cn.execute("SELECT COUNT(*) FROM d1_perspective_state").fetchone()[0]:,}')
print(f'US rows: {us.execute("SELECT COUNT(*) FROM d1_perspective_state").fetchone()[0]:,}')

cn_dates = cn.execute('SELECT MIN(state_date), MAX(state_date) FROM d1_perspective_state').fetchone()
us_dates = us.execute('SELECT MIN(state_date), MAX(state_date) FROM d1_perspective_state').fetchone()
print(f'A-share date range: {cn_dates[0]} ~ {cn_dates[1]}')
print(f'US date range: {us_dates[0]} ~ {us_dates[1]}')

# Check key fields needed by backtest signals
key_fields = ['stock_code', 'state_date', 'd1_close', 'd1_state_score', 'w1_state_score', 'mn1_state_score',
              'd1_trend', 'd1_volatility', 'd1_adx14', 'd1_bb_width_pct']
print('\n--- Key fields check ---')
for f in key_fields:
    cn_has = f in cn_cols
    us_has = f in us_cols
    status = '✅' if cn_has and us_has else '❌'
    print(f'  {status} {f}: A={cn_has} US={us_has}')

# Check if daily_bars exists
us_tables = [r[0] for r in us.execute('SHOW TABLES').fetchall()]
print(f'\nUS tables: {us_tables}')
cn_tables = [r[0] for r in cn.execute('SHOW TABLES').fetchall()]
print(f'A-share tables: {cn_tables}')
