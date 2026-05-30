import pytest
from state_calc.sr_calculator import (
    SRLevels,
    find_fractal_highs,
    find_fractal_lows,
    calculate_sr,
    calculate_ma,
    calculate_atr,
)


class TestFindFractalHighs:

    def test_simple_fractal_high(self):
        highs = [4.0, 4.5, 5.0, 4.6, 4.1]
        indices = find_fractal_highs(highs, period=5)
        assert indices == [2]

    def test_no_fractal_high_in_flat_data(self):
        highs = [10.0, 10.0, 10.0, 10.0, 10.0]
        indices = find_fractal_highs(highs, period=5)
        assert indices == []

    def test_multiple_fractal_highs(self):
        highs = [
            10, 11, 12, 11, 10,    # peak at index 2
            9, 10, 11, 12, 11,     # peak at index 8
            10, 9, 8, 7, 6,
        ]
        indices = find_fractal_highs(highs, period=5)
        assert 2 in indices
        assert 8 in indices

    def test_too_few_bars_returns_empty(self):
        highs = [10.0, 12.0]
        indices = find_fractal_highs(highs, period=5)
        assert indices == []

    def test_fractal_high_edge_bar_not_counted(self):
        highs = [8.0, 10.0, 12.0, 10.0, 8.0]
        indices = find_fractal_highs(highs, period=5)
        assert indices == [2]


class TestFindFractalLows:

    def test_simple_fractal_low(self):
        lows = [5.0, 4.8, 4.5, 4.7, 5.0]
        indices = find_fractal_lows(lows, period=5)
        assert indices == [2]

    def test_no_fractal_low_in_flat_data(self):
        lows = [10.0, 10.0, 10.0, 10.0, 10.0]
        indices = find_fractal_lows(lows, period=5)
        assert indices == []

    def test_multiple_fractal_lows(self):
        lows = [
            10, 9, 8, 9, 10,      # trough at index 2
            9, 8, 7, 8, 9,        # trough at index 7
            8, 7, 6, 5, 4,
        ]
        indices = find_fractal_lows(lows, period=5)
        assert 2 in indices
        assert 7 in indices

    def test_too_few_bars_returns_empty(self):
        lows = [10.0, 12.0]
        indices = find_fractal_lows(lows, period=5)
        assert indices == []


class TestCalculateSR:

    def test_insufficient_bars_returns_not_ready(self):
        sr = calculate_sr(
            highs=[10, 20],
            lows=[5, 10],
            closes=[8, 15],
            lookback=120,
        )
        assert sr.ready is False
        assert sr.support is None
        assert sr.resistance is None

    def test_valid_sr_with_enough_data(self):
        highs = [float(i % 10 + 90) for i in range(150)]
        lows = [float(i % 10 + 80) for i in range(150)]
        closes = [float(i % 10 + 85) for i in range(150)]

        sr = calculate_sr(highs, lows, closes, lookback=120)
        assert sr.ready is True
        assert sr.support < sr.resistance

    def test_fallback_when_fractals_insufficient(self):
        highs = list(range(100, 220))
        lows = list(range(95, 215))
        closes = list(range(97, 217))

        sr = calculate_sr(highs, lows, closes, lookback=120, min_fractals=50)
        assert sr.ready is True
        assert sr.support < sr.resistance

    def test_support_below_resistance_always(self):
        for _ in range(20):
            highs = [100.0 + i * 0.1 for i in range(200)]
            lows = [90.0 + i * 0.1 for i in range(200)]
            closes = [95.0 + i * 0.1 for i in range(200)]
            sr = calculate_sr(highs, lows, closes, lookback=120)
            assert sr.support < sr.resistance

    def test_sr_levels_are_positive(self):
        highs = [50.0 + i * 0.5 for i in range(200)]
        lows = [45.0 + i * 0.5 for i in range(200)]
        closes = [47.0 + i * 0.5 for i in range(200)]
        sr = calculate_sr(highs, lows, closes, lookback=120)
        assert sr.support > 0
        assert sr.resistance > 0


class TestCalculateMA:

    def test_simple_ma(self):
        prices = [10.0, 20.0, 30.0]
        result = calculate_ma(prices, period=3)
        assert result == pytest.approx(20.0)

    def test_insufficient_data_returns_none(self):
        prices = [10.0, 20.0]
        result = calculate_ma(prices, period=5)
        assert result is None

    def test_ma_uses_tail(self):
        prices = [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 10.0, 10.0]
        result = calculate_ma(prices, period=3)
        assert result == pytest.approx(10.0)


class TestCalculateATR:

    def test_atr_calculation(self):
        highs = [105.0, 106.0, 107.0, 106.0, 108.0, 109.0, 110.0, 111.0,
                 112.0, 113.0, 114.0, 115.0, 116.0, 117.0, 118.0]
        lows = [100.0, 101.0, 102.0, 101.0, 103.0, 104.0, 105.0, 106.0,
                107.0, 108.0, 109.0, 110.0, 111.0, 112.0, 113.0]
        closes = [102.0, 103.0, 104.0, 103.0, 105.0, 106.0, 107.0, 108.0,
                  109.0, 110.0, 111.0, 112.0, 113.0, 114.0, 115.0]

        curr, prev = calculate_atr(highs, lows, closes, period=14)
        assert curr > 0
        assert prev > 0

    def test_atr_insufficient_data(self):
        highs = [100.0, 101.0]
        lows = [98.0, 99.0]
        closes = [99.0, 100.0]

        curr, prev = calculate_atr(highs, lows, closes, period=14)
        assert curr == 0.0
        assert prev == 0.0

    def test_atr_expanding_sequence(self):
        n = 30
        highs = [100.0]
        lows = [95.0]
        closes = [97.0]
        for i in range(1, n):
            mult = 1.0 + i * 0.02
            highs.append(100.0 * mult)
            lows.append(95.0 * mult)
            closes.append(97.0 * mult)

        curr, prev = calculate_atr(highs, lows, closes, period=14)
        assert curr > prev

    def test_atr_contracting_sequence(self):
        n = 30
        highs = [200.0]
        lows = [190.0]
        closes = [195.0]
        for i in range(1, n):
            mult = 30.0 / i
            highs.append(100.0 * mult)
            lows.append(95.0 * mult)
            closes.append(97.0 * mult)

        curr, prev = calculate_atr(highs, lows, closes, period=14)
        assert curr < prev
