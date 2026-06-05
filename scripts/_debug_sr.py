import duckdb
con = duckdb.connect('outputs/p116_foundation_20260602/p116_foundation.duckdb', read_only=True)

# SR fields check
r1 = con.execute("SELECT COUNT(*) FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 AND d1_sr_support < d1_sr_resistance").fetchone()
print(f"Valid SR: {r1[0]:,}")

r2 = con.execute("SELECT d1_close,d1_sr_support,d1_sr_resistance FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 AND d1_sr_support < d1_sr_resistance LIMIT 3").fetchall()
for r in r2:
    sr_w = (r[2]-r[1])/r[0]*100
    sr_p = (r[0]-r[1])/(r[2]-r[1])*100
    print(f"  px={r[0]:.2f} sup={r[1]:.2f} res={r[2]:.2f} width={sr_w:.1f}% pos={sr_p:.0f}%")

# E/F + prev=-E/-F with SR
r3 = con.execute("""WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, d1_sr_support, d1_sr_resistance
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 AND d1_sr_support < d1_sr_resistance
),
e AS (SELECT *, LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev FROM b)
SELECT COUNT(*) FROM e WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F')
""").fetchone()
print(f"\nE/F+prev=-E/-F: {r3[0]:,}")

# + MN1 not E/F
r4 = con.execute("""WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, d1_sr_support, d1_sr_resistance
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 AND d1_sr_support < d1_sr_resistance
),
e AS (SELECT *, LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev FROM b)
SELECT COUNT(*) FROM e WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F')
""").fetchone()
print(f"+ MN1≠E/F: {r4[0]:,}")

# + sr_p in 0-1
r5 = con.execute("""WITH b AS (
    SELECT stock_code, state_date, d1_close, d1_state_hex, mn1_state_hex, d1_sr_support, d1_sr_resistance
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 AND d1_sr_support < d1_sr_resistance
),
e AS (SELECT *, LAG(d1_state_hex) OVER(PARTITION BY stock_code ORDER BY state_date) AS prev,
    (d1_close-d1_sr_support)/NULLIF(d1_sr_resistance-d1_sr_support,0) AS sr_p FROM b)
SELECT COUNT(*) FROM e WHERE d1_state_hex IN('E','F') AND prev IN('-E','-F') AND mn1_state_hex NOT IN('E','F') AND sr_p BETWEEN 0 AND 1
""").fetchone()
print(f"+ sr_p 0-1: {r5[0]:,}")

# SR position distribution for E/F states
r6 = con.execute("""
SELECT ROUND(MIN(sr_p)*100,1), ROUND(AVG(sr_p)*100,1), ROUND(MAX(sr_p)*100,1)
FROM (
    SELECT (d1_close-d1_sr_support)/NULLIF(d1_sr_resistance-d1_sr_support,0) AS sr_p
    FROM d1_perspective_state WHERE d1_close>0 AND d1_sr_support>0 AND d1_sr_resistance>0 
    AND d1_sr_support < d1_sr_resistance AND d1_state_hex IN('E','F')
) WHERE sr_p IS NOT NULL
""").fetchone()
print(f"\nE/F时的SR位置: min={r6[0]}% avg={r6[1]}% max={r6[2]}%")

con.close()
