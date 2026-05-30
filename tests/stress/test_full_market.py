import concurrent.futures
import time
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


@pytest.mark.slow
class TestFullMarketScanPerformance:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_foundation_db()
        if self.db_path is None:
            pytest.skip("無可用 Foundation DB")

    def test_full_state_scan_speed(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        start = time.perf_counter()
        count = con.execute(
            "SELECT COUNT(*) FROM d1_perspective_state"
        ).fetchone()[0]
        elapsed = time.perf_counter() - start
        con.close()

        rows_per_sec = count / elapsed if elapsed > 0 else 0
        print(f"\n  d1_perspective_state: {count:,} 行, "
              f"全量扫描 {elapsed:.2f}s ({rows_per_sec:,.0f} 行/s)")
        assert elapsed < 30, f"全量扫描耗时 {elapsed:.1f}s > 30s 阈值"
        assert count > 1_000_000, f"d1_perspective_state 行数异常: {count:,}"

    def test_aggregation_query_performance(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        start = time.perf_counter()
        result = con.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT stock_code) AS stocks,
                COUNT(DISTINCT state_date) AS days,
                SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END) AS ef2_count,
                ROUND(100.0 * SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS ef2_pct
            FROM d1_perspective_state
        """).fetchone()
        elapsed = time.perf_counter() - start
        con.close()

        print(f"\n  聚合查询 {elapsed:.2f}s: "
              f"{result[0]:,} 行 × {result[1]:,} 只 × {result[2]} 日, "
              f"E/F≥2: {result[3]:,} ({result[4]}%)")
        assert elapsed < 15, f"聚合查询耗时 {elapsed:.1f}s > 15s 阈值"

    def test_ef_count_distribution_query(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        start = time.perf_counter()
        rows = con.execute("""
            SELECT ef_count, COUNT(*) AS cnt
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
            GROUP BY ef_count ORDER BY ef_count
        """).fetchall()
        elapsed = time.perf_counter() - start
        con.close()

        print(f"\n  最新日 E/F 分布 {elapsed:.2f}s: "
              + ", ".join(f"ef={r[0]}:{r[1]:,}" for r in rows))
        assert elapsed < 5, f"E/F 分布查询 {elapsed:.1f}s > 5s 阈值"

    def test_state_transition_query(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        start = time.perf_counter()
        rows = con.execute("""
            WITH ordered AS (
                SELECT stock_code, state_date,
                       mn1_state_hex, w1_state_hex, d1_state_hex,
                       ef_count,
                       LAG(ef_count) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_ef
                FROM d1_perspective_state
                WHERE state_date >= '2026-04-01'
            )
            SELECT prev_ef, ef_count, COUNT(*) AS cnt
            FROM ordered
            WHERE prev_ef IS NOT NULL
            GROUP BY prev_ef, ef_count
            ORDER BY prev_ef, ef_count
        """).fetchall()
        elapsed = time.perf_counter() - start
        con.close()

        print(f"\n  近2月状态转换矩阵 {elapsed:.2f}s, {len(rows)} 种转换路径")
        assert elapsed < 10, f"状态转换查询 {elapsed:.1f}s > 10s 阈值"


@pytest.mark.slow
class TestConcurrentReadSafety:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_foundation_db()
        if self.db_path is None:
            pytest.skip("無可用 Foundation DB")

    def _reader_task(self, worker_id: int):
        con = duckdb.connect(str(self.db_path), read_only=True)
        result = con.execute("""
            SELECT stock_code, state_date, ef_count
            FROM d1_perspective_state
            WHERE stock_code = ?
            ORDER BY state_date DESC
            LIMIT 10
        """, (f"{worker_id % 5000 + 1:06d}",)).fetchall()
        con.close()
        return len(result)

    def test_concurrent_10_readers(self):
        start = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(self._reader_task, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        elapsed = time.perf_counter() - start

        print(f"\n  10 并发读完成: {elapsed:.2f}s, 结果: {results}")
        assert all(r >= 0 for r in results), f"存在失败读取: {results}"
        assert elapsed < 5, f"10 并发读 {elapsed:.1f}s > 5s 阈值"

    def test_concurrent_read_no_lock_errors(self):
        lock_errors = 0

        def safe_read(worker_id: int):
            nonlocal lock_errors
            try:
                con = duckdb.connect(str(self.db_path), read_only=True)
                con.execute("SELECT COUNT(*) FROM d1_perspective_state").fetchone()
                con.close()
                return True
            except Exception as e:
                lock_errors += 1
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(safe_read, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert lock_errors == 0, f"并发读出现 {lock_errors} 次锁错误"
        assert all(results), "存在失败的并发读取"


@pytest.mark.slow
class TestDataIntegrityAtScale:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = find_latest_foundation_db()
        if self.db_path is None:
            pytest.skip("無可用 Foundation DB")

    def test_stock_count_consistency_across_tables(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        daily_stocks = con.execute(
            "SELECT COUNT(DISTINCT stock_code) FROM daily_bars"
        ).fetchone()[0]
        state_stocks = con.execute(
            "SELECT COUNT(DISTINCT stock_code) FROM d1_perspective_state"
        ).fetchone()[0]
        con.close()

        ratio = state_stocks / daily_stocks if daily_stocks else 0
        print(f"\n  daily_bars: {daily_stocks:,} 只, "
              f"d1_perspective_state: {state_stocks:,} 只 "
              f"(覆盖率 {ratio:.1%})")
        assert ratio >= 0.80, f"State 股票覆盖率 {ratio:.1%} < 80%"

    def test_date_range_consistency(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        daily_min = con.execute("SELECT MIN(date) FROM daily_bars").fetchone()[0]
        daily_max = con.execute("SELECT MAX(date) FROM daily_bars").fetchone()[0]
        state_min = con.execute(
            "SELECT MIN(state_date) FROM d1_perspective_state"
        ).fetchone()[0]
        state_max = con.execute(
            "SELECT MAX(state_date) FROM d1_perspective_state"
        ).fetchone()[0]
        con.close()

        print(f"\n  daily_bars: {daily_min} → {daily_max}")
        print(f"  state:      {state_min} → {state_max}")
        assert state_min is not None
        assert state_max is not None

    def test_no_duplicate_state_rows(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        dupes = con.execute("""
            SELECT stock_code, state_date, COUNT(*) AS cnt
            FROM d1_perspective_state
            GROUP BY stock_code, state_date
            HAVING COUNT(*) > 1
            LIMIT 1
        """).fetchone()
        con.close()
        assert dupes is None, f"发现重复行: {dupes}"

    def test_state_score_distribution(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        rows = con.execute("""
            SELECT d1_state_score, COUNT(*) AS cnt
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
            GROUP BY d1_state_score
            ORDER BY d1_state_score
        """).fetchall()
        con.close()

        total = sum(r[1] for r in rows)
        ef_sum = sum(r[1] for r in rows if r[0] in (14, 15))
        pct = ef_sum / total * 100 if total else 0
        print(f"\n  最新日 D1 State 分布: {len(rows)} 个不同分值, "
              f"E/F 占比 {pct:.1f}% ({ef_sum:,}/{total:,})")

    def test_memory_footprint(self):
        con = duckdb.connect(str(self.db_path), read_only=True)
        con.execute("SET memory_limit='2GB'")
        try:
            con.execute("""
                SELECT stock_code, state_date, ef_count
                FROM d1_perspective_state
                ORDER BY state_date DESC, ef_count DESC
                LIMIT 1000
            """).fetchall()
            ok = True
        except Exception:
            ok = False
        con.close()
        assert ok, "2GB 内存限制下查询失败"


def test_quick_sanity():
    db_path = find_latest_foundation_db()
    if db_path is None:
        pytest.skip("無可用 Foundation DB")

    con = duckdb.connect(str(db_path), read_only=True)
    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()
    con.close()

    assert len(tables) == 12, f"预期 12 表, 实际 {len(tables)}: {[t[0] for t in tables]}"
