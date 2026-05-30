import hashlib
import json

import pytest
from hermass_platform.slice.data_contract import (
    ContractViolation,
    ValidationResult,
    validate_state_hex,
    validate_ef_count,
    validate_state_score,
    validate_state_row,
    validate_slice_envelope,
    validate_slice_data,
    validate_slice_result,
    compute_slice_checksum,
    compute_cache_key,
)


class TestValidateStateHex:

    @pytest.mark.parametrize("value,expected_valid", [
        ("0", True), ("1", True), ("8", True), ("9", True),
        ("A", True), ("B", True), ("C", True), ("D", True), ("E", True), ("F", True),
        ("-1", True), ("-C", True), ("-F", True),
        ("GG", False), ("10", False), ("-AA", False), ("", False),
        (None, False), (14, False),
    ])
    def test_hex_validation(self, value, expected_valid):
        v = validate_state_hex(value, "test_hex")
        if expected_valid:
            assert v is None
        else:
            assert v is not None
            assert v.rule == "STATE_BASE_CONTRACT §3.5"

    def test_lowercase_rejected(self):
        v = validate_state_hex("e", "test")
        assert v is not None

    def test_lowercase_f_rejected(self):
        v = validate_state_hex("f", "test")
        assert v is not None


class TestValidateEfCount:

    def test_valid_range(self):
        for n in range(4):
            assert validate_ef_count(n, "ef_count") is None

    def test_out_of_range(self):
        for n in (-1, 4, 10):
            v = validate_ef_count(n, "ef_count")
            assert v is not None

    def test_none_fails(self):
        v = validate_ef_count(None, "ef_count")
        assert v is not None

    def test_string_fails(self):
        v = validate_ef_count("2", "ef_count")
        assert v is not None


class TestValidateStateScore:

    def test_valid_range(self):
        for n in (-15, -8, 0, 8, 14, 15):
            assert validate_state_score(n, "score") is None

    def test_out_of_range(self):
        for n in (-16, 16, 99):
            v = validate_state_score(n, "score")
            assert v is not None

    def test_float_fails(self):
        v = validate_state_score(14.0, "score")
        assert v is not None


class TestValidateStateRow:

    def test_valid_row(self):
        row = {
            "stock_code": "000001",
            "state_date": "2026-05-22",
            "d1_close": 102.5,
            "mn1_state_hex": "E",
            "w1_state_hex": "E",
            "d1_state_hex": "F",
            "mn1_state_score": 14,
            "w1_state_score": 14,
            "d1_state_score": 15,
            "ef_count": 3,
        }
        violations = validate_state_row(row, "user")
        assert len(violations) == 0

    def test_invalid_hex(self):
        row = {"stock_code": "000001", "state_date": "2026-05-22",
               "mn1_state_hex": "GG", "w1_state_hex": "E", "d1_state_hex": "F"}
        violations = validate_state_row(row, "user")
        assert any(v.field == "mn1_state_hex" for v in violations)

    def test_ef_mismatch_with_scores(self):
        row = {
            "stock_code": "000001", "state_date": "2026-05-22",
            "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "E",
            "mn1_state_score": 14, "w1_state_score": 14, "d1_state_score": 14,
            "ef_count": 2,
        }
        violations = validate_state_row(row, "user")
        assert any(v.field == "ef_count" for v in violations)

    def test_negative_d1_close(self):
        row = {
            "stock_code": "000001", "state_date": "2026-05-22",
            "d1_close": -1.0,
            "mn1_state_hex": "0", "w1_state_hex": "0", "d1_state_hex": "0",
            "ef_count": 0,
        }
        violations = validate_state_row(row, "user")
        assert any(v.field == "d1_close" for v in violations)

    def test_missing_stock_code(self):
        row = {"state_date": "2026-05-22",
               "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "F"}
        violations = validate_state_row(row, "user")
        assert any(v.field == "stock_code" for v in violations)

    def test_short_stock_code(self):
        row = {"stock_code": "01", "state_date": "2026-05-22",
               "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "F"}
        violations = validate_state_row(row, "user")
        assert any(v.field == "stock_code" for v in violations)

    def test_out_of_range_state_score(self):
        row = {
            "stock_code": "000001", "state_date": "2026-05-22",
            "mn1_state_score": 99, "d1_state_score": 14, "w1_state_score": 14,
            "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "F",
            "ef_count": 2,
        }
        violations = validate_state_row(row, "user")
        assert any(v.field == "mn1_state_score" for v in violations)


class TestValidateSliceEnvelope:

    def test_valid_envelope(self):
        envelope = {
            "slice_type": "user",
            "slice_id": "test_001",
            "generated_at": "2026-05-24T00:00:00+00:00",
            "contract_version": "1.0.0",
            "source": {"foundation_db": "./test.duckdb", "cache_date": "20260524"},
            "params": {},
            "data": [{"stock_code": "000001"}],
            "summary": {"row_count": 1},
            "integrity": {"checksum": compute_slice_checksum([{"stock_code": "000001"}]), "row_count": 1},
        }
        vr = validate_slice_envelope(envelope)
        assert vr.valid

    def test_missing_contract_version(self):
        envelope = {
            "slice_type": "user", "slice_id": "x", "generated_at": "x",
            "source": {}, "params": {}, "data": [], "summary": {"row_count": 0},
            "integrity": {"checksum": "sha256:0", "row_count": 0},
        }
        vr = validate_slice_envelope(envelope)
        assert not vr.valid

    def test_wrong_contract_version(self):
        envelope = {
            "slice_type": "user", "slice_id": "x", "generated_at": "x",
            "contract_version": "0.9.0",
            "source": {}, "params": {}, "data": [], "summary": {"row_count": 0},
            "integrity": {"checksum": "sha256:0", "row_count": 0},
        }
        vr = validate_slice_envelope(envelope)
        assert not vr.valid

    def test_invalid_slice_type(self):
        envelope = {
            "slice_type": "invalid", "slice_id": "x", "generated_at": "x",
            "contract_version": "1.0.0",
            "source": {}, "params": {}, "data": [], "summary": {"row_count": 0},
            "integrity": {"checksum": "sha256:0", "row_count": 0},
        }
        vr = validate_slice_envelope(envelope)
        assert not vr.valid

    def test_data_not_list(self):
        envelope = {
            "slice_type": "user", "slice_id": "x", "generated_at": "x",
            "contract_version": "1.0.0",
            "source": {}, "params": {}, "data": "not-a-list",
            "summary": {"row_count": 0},
            "integrity": {"checksum": "sha256:0", "row_count": 0},
        }
        vr = validate_slice_envelope(envelope)
        assert not vr.valid


class TestValidateSliceData:

    def test_empty_data(self):
        vr = validate_slice_data([], "user")
        assert vr.valid

    def test_mixed_valid_invalid(self):
        data = [
            {
                "stock_code": "000001", "state_date": "2026-05-22",
                "mn1_state_hex": "E", "w1_state_hex": "E", "d1_state_hex": "F",
                "mn1_state_score": 14, "w1_state_score": 14, "d1_state_score": 15,
                "ef_count": 3,
            },
            {
                "stock_code": "000002", "state_date": "2026-05-22",
                "mn1_state_hex": "GG", "w1_state_hex": "E", "d1_state_hex": "F",
            },
        ]
        vr = validate_slice_data(data, "user")
        assert not vr.valid
        assert len(vr.violations) == 1

    def test_non_dict_row(self):
        data = ["not-a-dict"]
        vr = validate_slice_data(data, "user")
        assert not vr.valid


class TestValidateSliceResult:

    def test_full_valid_result(self):
        data = [{"stock_code": "000001", "state_date": "2026-05-22",
                 "mn1_state_hex": "E", "w1_state_hex": "F", "d1_state_hex": "E",
                 "mn1_state_score": 14, "w1_state_score": 15, "d1_state_score": 14,
                 "ef_count": 3, "d1_close": 100.0}]
        result = {
            "slice_type": "user",
            "slice_id": "test_001",
            "generated_at": "2026-05-24T00:00:00+00:00",
            "contract_version": "1.0.0",
            "source": {"foundation_db": "./test.duckdb", "cache_date": "20260524"},
            "params": {"user_id": "001"},
            "data": data,
            "summary": {"row_count": 1},
            "integrity": {
                "checksum": compute_slice_checksum(data),
                "row_count": 1,
            },
        }
        vr = validate_slice_result(result)
        assert vr.valid

    def test_checksum_mismatch(self):
        data = [{"stock_code": "000001"}]
        result = {
            "slice_type": "user",
            "slice_id": "test_001",
            "generated_at": "2026-05-24T00:00:00+00:00",
            "contract_version": "1.0.0",
            "source": {"foundation_db": "./test.duckdb", "cache_date": "20260524"},
            "params": {"user_id": "001"},
            "data": data,
            "summary": {"row_count": 1},
            "integrity": {"checksum": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                          "row_count": 1},
        }
        vr = validate_slice_result(result)
        assert not vr.valid
        assert any("checksum" in v.field for v in vr.violations)


class TestChecksum:

    def test_deterministic(self):
        data = [{"a": 1, "b": 2}]
        assert compute_slice_checksum(data) == compute_slice_checksum(data)

    def test_different_data_different_hash(self):
        a = compute_slice_checksum([{"x": 1}])
        b = compute_slice_checksum([{"x": 2}])
        assert a != b

    def test_format(self):
        c = compute_slice_checksum([{"a": 1}])
        assert c.startswith("sha256:")
        assert len(c) == 7 + 64

    def test_order_independent(self):
        data_a = [{"stock_code": "000001", "mn1_state_hex": "E", "ef_count": 3}]
        data_b = [{"ef_count": 3, "mn1_state_hex": "E", "stock_code": "000001"}]
        assert compute_slice_checksum(data_a) == compute_slice_checksum(data_b)


class TestCacheKey:

    def test_deterministic(self):
        a = compute_cache_key("user", {"user_id": "001", "date": "2026-05-22"}, "20260522")
        b = compute_cache_key("user", {"date": "2026-05-22", "user_id": "001"}, "20260522")
        assert a == b

    def test_different_params_different_key(self):
        a = compute_cache_key("user", {"user_id": "001"}, "20260522")
        b = compute_cache_key("user", {"user_id": "002"}, "20260522")
        assert a != b

    def test_length(self):
        k = compute_cache_key("user", {"user_id": "test"}, "20260522")
        assert len(k) == 16


class TestContractViolation:

    def test_dataclass(self):
        v = ContractViolation("field", "val", "rule_ref", "something wrong")
        assert v.field == "field"
        assert v.rule == "rule_ref"


class TestValidationResult:

    def test_default_valid(self):
        vr = ValidationResult(valid=True)
        assert vr.valid
        assert len(vr.violations) == 0

    def test_add_violation_flips_valid(self):
        vr = ValidationResult(valid=True)
        vr.add_violation("x", None, "r", "m")
        assert not vr.valid
