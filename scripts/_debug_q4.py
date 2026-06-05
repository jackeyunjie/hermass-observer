import duckdb,json
con=duckdb.connect('outputs/p116_foundation_20260602/p116_foundation.duckdb',read_only=True)
# Show Q2/Q3 results
cmd = "cat /tmp/qoder_out.txt"
import subprocess,json
out = subprocess.check_output(['cat','/tmp/qoder_out.txt']).decode()
d = json.loads(out)
print("Q2:", json.dumps(d["q2_contraction_depth_vs_return"], indent=2))
print("Q3:", json.dumps(d["q3_reversal_timing"], indent=2))

# Debug Q4
r = con.execute("""
WITH e AS (
    SELECT *, LAG(d1_state_hex) OVER w AS p, LEAD(d1_state_hex) OVER w AS n,
        LEAD(d1_close,20) OVER w / d1_close - 1 AS r20
    FROM d1_perspective_state WHERE d1_close>0 AND d1_atr_ratio_pct IS NOT NULL AND d1_bb_width_q20_20 IS NOT NULL
    WINDOW w AS (PARTITION BY stock_code ORDER BY state_date)
),
m AS (SELECT MEDIAN(d1_atr_ratio_pct) am, MEDIAN(d1_bb_width_q20_20) bm FROM e)
SELECT COUNT(*)
FROM e,m
WHERE d1_state_hex IN('-E','-F') AND n IN('E','F') AND mn1_state_hex NOT IN('E','F')
  AND d1_atr_ratio_pct < m.am AND d1_bb_width_q20_20 < m.bm
  AND r20 IS NOT NULL
""").fetchone()
print("Q4 base events:", r[0])
con.close()
