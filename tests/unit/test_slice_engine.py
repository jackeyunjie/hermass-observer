import json
import tempfile
from pathlib import Path

import pytest
from hermass_platform.slice.slice_engine import (
    slice,
    _read_cache,
    _write_cache,
    _build_envelope,
    CACHE_DIR,
)


class TestSliceEngineCache:

    def test_cache_write_read(self):
        with tempfile.TemporaryDirectory() as td:
            test_cache = Path(td) / "test_cache"
            result = {
                "slice_type": "user",
                "slice_id": "test",
                "generated_at": "2026-05-24T00:00:00Z",
                "contract_version": "1.0.0",
                "source": {"foundation_db": "test.duckdb", "cache_date": "20260524"},
                "params": {"user_id": "001"},
                "data": [{"stock_code": "000001"}],
                "summary": {"row_count": 1},
                "integrity": {"checksum": "sha256:0", "row_count": 1},
            }

            import hermass_platform.slice.slice_engine as engine
            original_cache = engine.CACHE_DIR
            try:
                engine.CACHE_DIR = test_cache
                _write_cache("test_key", result)
                cached = _read_cache("test_key", "20260524")
                assert cached is not None
                assert cached["slice_type"] == "user"
            finally:
                engine.CACHE_DIR = original_cache

    def test_cache_cross_day_expires(self):
        with tempfile.TemporaryDirectory() as td:
            test_cache = Path(td) / "test_cache"
            result = {
                "slice_type": "user",
                "slice_id": "test",
                "generated_at": "2026-05-24T00:00:00Z",
                "contract_version": "1.0.0",
                "source": {"foundation_db": "test.duckdb", "cache_date": "20260523"},
                "params": {"user_id": "001"},
                "data": [],
                "summary": {"row_count": 0},
                "integrity": {"checksum": "sha256:0", "row_count": 0},
            }

            import hermass_platform.slice.slice_engine as engine
            orig = engine.CACHE_DIR
            try:
                engine.CACHE_DIR = test_cache
                _write_cache("test_k2", result)
                cached = _read_cache("test_k2", "20260524")
                assert cached is None
            finally:
                engine.CACHE_DIR = orig


class TestSliceEnvelope:

    def test_build_envelope(self):
        data = [{"stock_code": "000001", "ef_count": 3}]
        env = _build_envelope(
            slice_type="user",
            params={"user_id": "001"},
            data=data,
            summary={"row_count": 1},
            foundation_db="test.duckdb",
            cache_date="20260524",
        )
        assert env["contract_version"] == "1.0.0"
        assert env["slice_type"] == "user"
        assert len(env["data"]) == 1
        assert "checksum" in env["integrity"]


class TestSliceIntegration:

    def test_user_slice_basic(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="user",
            params={"user_id": "test_user", "date": "2026-05-20", "limit": 10},
            bypass_cache=True,
            validate=False,
        )
        assert result["slice_type"] == "user"
        assert "data" in result
        assert "summary" in result
        assert result["summary"]["row_count"] >= 0

    def test_time_slice_basic(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="time",
            params={"date": "2026-05-20", "lookback_days": 5, "limit": 10},
            bypass_cache=True,
            validate=False,
        )
        assert result["slice_type"] == "time"
        assert len(result["data"]) <= 10

    def test_user_slice_with_stock_codes(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="user",
            params={
                "user_id": "test",
                "date": "2026-05-20",
                "stock_codes": ["000001"],
                "limit": 5,
            },
            bypass_cache=True,
            validate=False,
        )
        rows = result["data"]
        for r in rows:
            assert r["stock_code"] == "000001"

    def test_slice_with_validation(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="user",
            params={"user_id": "test", "date": "2026-05-20", "limit": 5},
            bypass_cache=True,
            validate=True,
        )
        assert result["contract_version"] == "1.0.0"

    def test_nonexistent_slice_type(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        with pytest.raises((ValueError, NotImplementedError)):
            slice(
                foundation_db=dbs[0],
                slice_type="nonexistent",
                params={"date": "2026-05-20"},
                bypass_cache=True,
                validate=False,
            )

    def test_invalid_state_data_fails_validation(self):
        data = [{"stock_code": "000001", "state_date": "2026-05-22",
                 "mn1_state_hex": "GG", "w1_state_hex": "E", "d1_state_hex": "F"}]
        env = _build_envelope(
            slice_type="user", params={"user_id": "001"},
            data=data, summary={"row_count": 1},
            foundation_db="test.duckdb", cache_date="20260524",
        )
        from hermass_platform.slice.data_contract import validate_slice_result
        vr = validate_slice_result(env)
        assert not vr.valid
        assert any("mn1_state_hex" in v.field for v in vr.violations)

    def test_industry_slice_basic(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="industry",
            params={"sw_l1": "电子", "date": "2026-05-20", "limit": 20},
            bypass_cache=True,
            validate=False,
        )
        assert result["slice_type"] == "industry"
        assert result["params"]["sw_l1"] == "电子"

    def test_industry_slice_nonexistent_industry(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="industry",
            params={"sw_l1": "不存在行业XYZ", "date": "2026-05-20", "limit": 20},
            bypass_cache=True,
            validate=False,
        )
        assert result["slice_type"] == "industry"
        assert result["summary"]["total_in_industry"] == 0
        assert len(result["data"]) == 0

    def test_industry_slice_list_industries(self):
        from hermass_platform.slice.industry_slice import list_industries
        inds = list_industries()
        assert len(inds) > 0
        assert "电子" in inds

    def test_cognitive_slice_stub(self):
        dbs = sorted(Path("outputs").glob("p116_foundation_*/p116_foundation.duckdb"), reverse=True)
        if not dbs:
            pytest.skip("無可用 Foundation DB")

        result = slice(
            foundation_db=dbs[0],
            slice_type="cognitive",
            params={"user_id": "test_user", "date": "2026-05-20"},
            bypass_cache=True,
            validate=False,
        )
        assert result["slice_type"] == "cognitive"
        assert result["summary"]["_notice"] is not None
        assert len(result["data"]) == 0
