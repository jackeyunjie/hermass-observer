import time
from pathlib import Path

import pytest
import duckdb

ROOT = Path(__file__).resolve().parents[2]


def find_foundation_dbs():
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"))
    result = []
    for c in candidates:
        if c.exists() and c.stat().st_size > 0 and "_mt4like" not in str(c.parent):
            result.append(c)
    return result


@pytest.mark.slow
class TestCrossDBBitExact:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.dbs = find_foundation_dbs()
        if len(self.dbs) < 2:
            pytest.skip(f"至少需要 2 個 Foundation DB，當前只有 {len(self.dbs)} 個")

    def test_cross_db_state_counts_monotonic(self):
        prev_count = None
        for db_path in self.dbs:
            con = duckdb.connect(str(db_path), read_only=True)
            state_count = con.execute(
                "SELECT COUNT(*) FROM d1_perspective_state"
            ).fetchone()[0]
            latest_date = con.execute(
                "SELECT MAX(state_date) FROM d1_perspective_state"
            ).fetchone()[0]
            con.close()

            if prev_count is not None:
                assert state_count >= prev_count, \
                    f"{db_path.parent.name}: {state_count:,} < 前版 {prev_count:,}"

            print(f"  {db_path.parent.name}: {state_count:,} 行, 最新 {latest_date}")
            prev_count = state_count

    def test_overlapping_dates_bit_exact(self):
        dbs = self.dbs[-2:]

        con_a = duckdb.connect(str(dbs[0]), read_only=True)
        latest_a = con_a.execute(
            "SELECT MAX(state_date) FROM d1_perspective_state"
        ).fetchone()[0]
        con_a.close()

        con_b = duckdb.connect(str(dbs[1]), read_only=True)
        con_b.execute(f"ATTACH '{str(dbs[0])}' AS db_a (READ_ONLY)")

        diff_count = con_b.execute(f"""
            SELECT COUNT(*)
            FROM d1_perspective_state cur
            INNER JOIN db_a.d1_perspective_state prev
              ON cur.stock_code = prev.stock_code
             AND cur.state_date = prev.state_date
             AND cur.state_date <= DATE '{latest_a}'
            WHERE cur.d1_state_score != prev.d1_state_score
               OR cur.d1_state_hex   != prev.d1_state_hex
               OR cur.w1_state_score != prev.w1_state_score
               OR cur.w1_state_hex   != prev.w1_state_hex
               OR cur.mn1_state_score != prev.mn1_state_score
               OR cur.mn1_state_hex  != prev.mn1_state_hex
        """).fetchone()[0]

        overlap_count = con_b.execute(f"""
            SELECT COUNT(*)
            FROM d1_perspective_state cur
            INNER JOIN db_a.d1_perspective_state prev
              ON cur.stock_code = prev.stock_code
             AND cur.state_date = prev.state_date
             AND cur.state_date <= DATE '{latest_a}'
        """).fetchone()[0]

        con_b.close()

        ratio = diff_count / overlap_count * 100 if overlap_count else 0
        print(f"\n  重疊 {overlap_count:,} 行, 差異 {diff_count} 行 ({ratio:.4f}%)")
        assert diff_count == 0, \
            f"跨 DB bit-exact 失敗: {diff_count} 行差異 / {overlap_count:,} 重疊"

    def test_ef_count_field_consistency_across_dbs(self):
        dbs = self.dbs[-2:]

        con_b = duckdb.connect(str(dbs[1]), read_only=True)
        latest_a_date = con_b.execute(
            f"SELECT MAX(state_date) FROM d1_perspective_state"
        ).fetchone()[0]
        con_b.execute(f"ATTACH '{str(dbs[0])}' AS db_a (READ_ONLY)")

        diff_ef = con_b.execute(f"""
            SELECT COUNT(*)
            FROM d1_perspective_state cur
            INNER JOIN db_a.d1_perspective_state prev
              ON cur.stock_code = prev.stock_code
             AND cur.state_date = prev.state_date
             AND cur.state_date <= DATE '{latest_a_date}'
            WHERE cur.ef_count != prev.ef_count
        """).fetchone()[0]

        con_b.close()

        assert diff_ef == 0, f"ef_count 跨 DB 不一致: {diff_ef} 行"

    def test_db_schema_version(self):
        for db_path in self.dbs:
            con = duckdb.connect(str(db_path), read_only=True)
            version = con.execute(
                "SELECT schema_version FROM foundation_run_log LIMIT 1"
            ).fetchone()[0]
            con.close()
            print(f"  {db_path.parent.name}: schema_version={version}")
            assert version is not None
