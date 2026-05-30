import pytest
from datetime import date

from state_calc.d1_perspective import (
    TimeframeData,
    AlignedState,
    align_timeframes,
    calculate_all_states,
)
from state_calc.p116_core import StateComponents


class TestTimeframeData:

    def test_dataclass_fields(self):
        tf = TimeframeData(
            dates=[date(2026, 5, 22)],
            opens=[100.0],
            highs=[105.0],
            lows=[95.0],
            closes=[102.0],
            volumes=[1000000.0],
        )
        assert tf.dates[0] == date(2026, 5, 22)
        assert tf.opens[0] == 100.0
        assert len(tf.closes) == 1


class TestAlignTimeframes:

    def test_simple_alignment(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 18), date(2026, 5, 19), date(2026, 5, 20),
                   date(2026, 5, 21), date(2026, 5, 22)],
            opens=[100.0] * 5, highs=[105.0] * 5,
            lows=[95.0] * 5, closes=[102.0] * 5,
            volumes=[1e6] * 5,
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[100.0], highs=[105.0],
            lows=[95.0], closes=[102.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        aligned = align_timeframes(d1, w1, mn1)
        assert len(aligned) == 5

    def test_d1_before_w1_skipped(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 15), date(2026, 5, 18)],
            opens=[100.0] * 2, highs=[105.0] * 2,
            lows=[95.0] * 2, closes=[102.0] * 2,
            volumes=[1e6] * 2,
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[100.0], highs=[105.0],
            lows=[95.0], closes=[102.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        aligned = align_timeframes(d1, w1, mn1)
        assert len(aligned) == 1
        assert aligned[0]["date"] == date(2026, 5, 18)

    def test_forward_fill_w1(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)],
            opens=[100.0] * 3, highs=[105.0] * 3,
            lows=[95.0] * 3, closes=[102.0] * 3,
            volumes=[1e6] * 3,
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[99.0], highs=[108.0],
            lows=[94.0], closes=[101.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        aligned = align_timeframes(d1, w1, mn1)
        assert len(aligned) == 3
        for item in aligned:
            assert item["w1_idx"] == 0
            assert item["mn1_idx"] == 0

    def test_bisect_choose_latest_before_or_equal(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 22)],
            opens=[100.0], highs=[105.0],
            lows=[95.0], closes=[102.0],
            volumes=[1e6],
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 4), date(2026, 5, 11),
                   date(2026, 5, 18), date(2026, 5, 25)],
            opens=[100.0] * 4, highs=[105.0] * 4,
            lows=[95.0] * 4, closes=[102.0] * 4,
            volumes=[5e6] * 4,
        )
        mn1 = TimeframeData(
            dates=[date(2026, 4, 1), date(2026, 5, 1)],
            opens=[98.0] * 2, highs=[110.0] * 2,
            lows=[90.0] * 2, closes=[100.0] * 2,
            volumes=[20e6] * 2,
        )

        aligned = align_timeframes(d1, w1, mn1)
        assert len(aligned) == 1
        assert aligned[0]["w1_idx"] == 2
        assert aligned[0]["mn1_idx"] == 1


class TestCalculateAllStates:

    def test_all_states_use_d1_close_for_position(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 21), date(2026, 5, 22)],
            opens=[100.0, 101.0],
            highs=[105.0, 120.0],
            lows=[95.0, 99.0],
            closes=[102.0, 115.0],
            volumes=[1e6, 2e6],
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[99.0], highs=[108.0],
            lows=[94.0], closes=[101.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        result = calculate_all_states(
            stock_code="000001",
            stock_name="测试股票",
            d1_data=d1, w1_data=w1, mn1_data=mn1,
            days=2,
        )

        assert len(result) == 2
        latest = result[0]
        assert latest.d1_close == 115.0
        assert isinstance(latest.d1_state, StateComponents)
        assert isinstance(latest.w1_state, StateComponents)
        assert isinstance(latest.mn1_state, StateComponents)

    def test_states_ordered_newest_first(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 21), date(2026, 5, 22)],
            opens=[100.0, 101.0],
            highs=[105.0, 106.0],
            lows=[95.0, 96.0],
            closes=[102.0, 103.0],
            volumes=[1e6, 2e6],
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[99.0], highs=[108.0],
            lows=[94.0], closes=[101.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        result = calculate_all_states(
            stock_code="000001",
            stock_name="测试股票",
            d1_data=d1, w1_data=w1, mn1_data=mn1,
            days=2,
        )

        assert result[0].date == date(2026, 5, 22)
        assert result[1].date == date(2026, 5, 21)

    def test_stock_code_preserved(self):
        d1 = TimeframeData(
            dates=[date(2026, 5, 22)],
            opens=[100.0], highs=[105.0],
            lows=[95.0], closes=[102.0],
            volumes=[1e6],
        )
        w1 = TimeframeData(
            dates=[date(2026, 5, 18)],
            opens=[99.0], highs=[108.0],
            lows=[94.0], closes=[101.0],
            volumes=[5e6],
        )
        mn1 = TimeframeData(
            dates=[date(2026, 5, 1)],
            opens=[98.0], highs=[110.0],
            lows=[90.0], closes=[100.0],
            volumes=[20e6],
        )

        result = calculate_all_states(
            stock_code="600519",
            stock_name="贵州茅台",
            d1_data=d1, w1_data=w1, mn1_data=mn1,
            days=1,
        )
        assert result[0].stock_code == "600519"
        assert result[0].stock_name == "贵州茅台"
