import pytest
from filter.ef_screener import (
    ScreenResult,
    count_ef_states,
    screen_stocks,
    classify_signal_strength,
)


class TestCountEfStates:

    def test_all_three_ef(self):
        assert count_ef_states("E", "E", "E") == 3

    def test_two_ef(self):
        assert count_ef_states("E", "F", "C") == 2

    def test_one_ef(self):
        assert count_ef_states("E", "C", "0") == 1

    def test_zero_ef(self):
        assert count_ef_states("0", "8", "C") == 0

    def test_mixed_e_and_f(self):
        assert count_ef_states("F", "F", "F") == 3

    def test_negative_E_not_counted(self):
        assert count_ef_states("-E", "C", "0") == 0

    def test_negative_F_not_counted(self):
        assert count_ef_states("C", "-F", "8") == 0

    def test_lowercase_not_matched(self):
        assert count_ef_states("e", "f", "0") == 0


class TestScreenStocks:

    def test_basic_screening(self):
        all_states = [
            {"stock_code": "000001", "stock_name": "平安银行",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"},
            {"stock_code": "000002", "stock_name": "万科A",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "F", "D1_hex": "C"},
            {"stock_code": "000003", "stock_name": "测试股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "C", "D1_hex": "0"},
        ]
        results = screen_stocks(all_states, min_ef=2)
        assert len(results) == 2
        assert results[0].stock_code == "000001"
        assert results[0].ef_count == 3
        assert results[1].stock_code == "000002"
        assert results[1].ef_count == 2

    def test_min_ef_3_only(self):
        all_states = [
            {"stock_code": "000001", "stock_name": "三E股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"},
            {"stock_code": "000002", "stock_name": "两E股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "F", "D1_hex": "C"},
        ]
        results = screen_stocks(all_states, min_ef=3)
        assert len(results) == 1
        assert results[0].stock_code == "000001"

    def test_max_results_limit(self):
        all_states = []
        for i in range(200):
            all_states.append({
                "stock_code": f"{i:06d}",
                "stock_name": f"股票{i}",
                "date": "2026-05-22",
                "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E",
            })

        results = screen_stocks(all_states, min_ef=2, max_results=50)
        assert len(results) == 50

    def test_sort_by_ef_count_then_code(self):
        all_states = [
            {"stock_code": "000003", "stock_name": "C股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"},
            {"stock_code": "000001", "stock_name": "A股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"},
            {"stock_code": "000002", "stock_name": "B股",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "F", "D1_hex": "C"},
        ]
        results = screen_stocks(all_states, min_ef=2)
        assert results[0].stock_code == "000001"
        assert results[1].stock_code == "000003"
        assert results[2].stock_code == "000002"

    def test_days_per_stock_truncates_history(self):
        all_states = [
            {"stock_code": "000001", "stock_name": "测试",
             "date": f"2026-05-{d:02d}", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"}
            for d in range(20, 31)
        ]
        results = screen_stocks(all_states, min_ef=2, days_per_stock=5)
        assert len(results) == 1
        assert len(results[0].states) == 5

    def test_empty_input(self):
        results = screen_stocks([], min_ef=2)
        assert results == []

    def test_no_stocks_pass_filter(self):
        all_states = [
            {"stock_code": "000001", "stock_name": "测试",
             "date": "2026-05-22", "MN1_hex": "0", "W1_hex": "8", "D1_hex": "C"},
        ]
        results = screen_stocks(all_states, min_ef=2)
        assert results == []

    def test_latest_date_taken_for_screening(self):
        all_states = [
            {"stock_code": "000001", "stock_name": "测试",
             "date": "2026-05-20", "MN1_hex": "0", "W1_hex": "0", "D1_hex": "0"},
            {"stock_code": "000001", "stock_name": "测试",
             "date": "2026-05-22", "MN1_hex": "E", "W1_hex": "E", "D1_hex": "E"},
        ]
        results = screen_stocks(all_states, min_ef=2)
        assert len(results) == 1
        assert results[0].ef_count == 3


class TestClassifySignalStrength:

    def test_3_is_super_strong(self):
        assert "超强" in classify_signal_strength(3)

    def test_2_is_strong(self):
        assert "强势" in classify_signal_strength(2)

    def test_1_is_normal(self):
        assert classify_signal_strength(1) == "一般"

    def test_0_is_normal(self):
        assert classify_signal_strength(0) == "一般"


class TestScreenResult:

    def test_dataclass_fields(self):
        sr = ScreenResult(
            stock_code="000001",
            stock_name="平安银行",
            ef_count=3,
            mn1_hex="E",
            w1_hex="E",
            d1_hex="E",
            states=[],
        )
        assert sr.ef_count == 3
        assert sr.stock_code == "000001"
