from pathlib import Path

import pytest
import duckdb

ROOT = Path(__file__).resolve().parents[2]


def find_latest_signal_db():
    candidates = sorted(
        ROOT.glob("outputs/strategy_signals/strategy_signals.duckdb"),
    )
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


@pytest.mark.integration
class TestSignalLedgerFlow:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_signal_db()
        if self.db_path is None:
            pytest.skip("没有可用的 strategy_signals.duckdb 进行集成测试")

    def test_signal_db_readable(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "strategy_signal_daily" in table_names, \
            f"缺少 strategy_signal_daily 表，现有: {table_names}"
        con.close()

    def test_signal_daily_has_required_columns(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        columns = con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='strategy_signal_daily'"
        ).fetchall()
        col_names = {r[0] for r in columns}

        required = {"stock_code", "signal_date", "strategy_id", "signal_name"}
        missing = required - col_names
        assert not missing, f"strategy_signal_daily 缺失列: {missing}"
        con.close()

    def test_signal_daily_strategy_coverage(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        strategies = con.execute(
            "SELECT DISTINCT strategy_id FROM strategy_signal_daily"
        ).fetchall()
        strat_names = {r[0] for r in strategies}
        assert len(strat_names) >= 1, "信号账本没有任何策略数据"
        con.close()

    def test_signal_stock_code_format(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        row = con.execute(
            "SELECT stock_code FROM strategy_signal_daily LIMIT 1"
        ).fetchone()
        if row:
            assert len(row[0]) >= 4, f"stock_code 太短: {row[0]}"
        con.close()

    def test_read_only_enforced(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        con.close()
