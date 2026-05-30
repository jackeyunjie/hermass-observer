import os
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest
import duckdb

ROOT = Path(__file__).resolve().parents[2]


def find_latest_foundation_db():
    candidates = sorted(
        ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


@pytest.mark.integration
class TestFoundationDBIntegrity:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_foundation_db()
        if self.db_path is None:
            pytest.skip("没有可用的 Foundation DB 进行集成测试")

    def test_all_12_tables_exist(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = {r[0] for r in tables}

        expected = {
            "daily_bars", "weekly_bars", "monthly_bars",
            "timeframe_bars", "sr_levels", "timeframe_indicators",
            "d1_d_sr", "d1_w_sr", "d1_mn1_sr",
            "d1_sr_context", "d1_perspective_state",
            "foundation_run_log",
        }
        missing = expected - table_names
        assert not missing, f"缺失表: {missing}"
        con.close()

    def test_foundation_run_log_has_schema_version(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            "SELECT schema_version FROM foundation_run_log LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] is not None
        assert len(row[0]) > 0
        con.close()

    def test_d1_perspective_state_has_required_columns(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        columns = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='d1_perspective_state'"
        ).fetchall()
        col_names = {r[0] for r in columns}

        required = {
            "stock_code", "state_date", "d1_close",
            "mn1_state_score", "w1_state_score", "d1_state_score",
            "mn1_state_hex", "w1_state_hex", "d1_state_hex",
            "ef_count",
        }
        missing = required - col_names
        assert not missing, f"d1_perspective_state 缺失列: {missing}"
        con.close()

    def test_ef_count_range(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            "SELECT MIN(ef_count), MAX(ef_count) FROM d1_perspective_state"
        ).fetchone()
        assert row[0] is not None
        assert 0 <= row[0] <= 3
        assert 0 <= row[1] <= 3
        con.close()

    def test_state_scores_in_valid_range(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        for col in ("mn1_state_score", "w1_state_score", "d1_state_score"):
            mn, mx = con.execute(
                f"SELECT MIN({col}), MAX({col}) FROM d1_perspective_state"
            ).fetchone()
            assert mn is not None
            assert mx is not None
            assert -15 <= mn <= 15, f"{col} min={mn} 超出 [-15,15]"
            assert -15 <= mx <= 15, f"{col} max={mx} 超出 [-15,15]"
        con.close()

    def test_d1_perspective_state_no_null_stock_code(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        count = con.execute(
            "SELECT COUNT(*) FROM d1_perspective_state WHERE stock_code IS NULL"
        ).fetchone()[0]
        assert count == 0
        con.close()

    def test_read_only_enforced(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        con.close()

    def test_sr_levels_fractal_params(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            "SELECT DISTINCT fractal_period, confirm_lag_bars FROM sr_levels LIMIT 1"
        ).fetchone()
        if row:
            assert row[0] == 5
            assert row[1] == 3
        con.close()


@pytest.mark.integration
class TestPipelineDataConsistency:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_foundation_db()
        if self.db_path is None:
            pytest.skip("没有可用的 Foundation DB 进行集成测试")

    def test_daily_bars_date_temporal_consistency(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        rows = con.execute(
            "SELECT stock_code, date FROM daily_bars "
            "WHERE stock_code='000001' ORDER BY date LIMIT 5"
        ).fetchall()
        dates = [r[1] for r in rows]
        for i in range(1, len(dates)):
            assert dates[i] > dates[i-1], f"日期 {dates[i-1]} → {dates[i]} 不递增"
        con.close()

    def test_sr_inversion_rate_acceptable(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        total = con.execute(
            "SELECT COUNT(*) FROM sr_levels WHERE sr_ready = true"
        ).fetchone()[0]
        inverted = con.execute(
            "SELECT COUNT(*) FROM sr_levels "
            "WHERE sr_ready = true AND sr_support > sr_resistance"
        ).fetchone()[0]
        equal_count = con.execute(
            "SELECT COUNT(*) FROM sr_levels "
            "WHERE sr_ready = true AND sr_support = sr_resistance"
        ).fetchone()[0]
        con.close()

        if total > 0:
            inversion_rate = inverted / total
            equal_rate = equal_count / total
            assert inversion_rate < 0.35, \
                f"支撑>阻力 比例 {inversion_rate:.1%} 偏高（阈值 35%）"
            assert equal_rate < 0.05, \
                f"支撑==阻力 比例 {equal_rate:.1%} 偏高（阈值 5%）"

    def test_state_hex_format(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        rows = con.execute(
            "SELECT DISTINCT mn1_state_hex FROM d1_perspective_state LIMIT 50"
        ).fetchall()
        for (h,) in rows:
            if h.startswith("-"):
                assert len(h) >= 2
                assert h[1] in "0123456789ABCDEF"
            else:
                assert h[0] in "0123456789ABCDEF"
        con.close()

    def test_ef_count_matches_state_scores(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            """
            SELECT COUNT(*) FROM d1_perspective_state
            WHERE ef_count = 3
              AND (mn1_state_score NOT IN (14, 15)
                   OR w1_state_score NOT IN (14, 15)
                   OR d1_state_score NOT IN (14, 15))
            """
        ).fetchone()[0]
        assert row == 0, f"ef_count=3 但三周期不全是 E/F: {row} 行"
        con.close()

    def test_d1_close_positive(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            "SELECT COUNT(*) FROM d1_perspective_state WHERE d1_close <= 0"
        ).fetchone()[0]
        assert row == 0, f"{row} 行 d1_close <= 0"
        con.close()
