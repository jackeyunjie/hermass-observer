import pytest
from state_calc.p116_core import (
    StateComponents,
    calculate_state,
    decode_state_hex,
    is_ef_state,
)


# ============================================================
# 4-bit 编码公式: score = base + trend_bit*4 + position_bit + volatility_bit
# ============================================================

class TestCalculateState4BitEncoding:

    def test_all_bits_zero_yields_score_0(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.score == 0
        assert result.hex == "0"
        assert result.base == 0
        assert result.trend_bit == 0
        assert result.position_bit == 0
        assert result.volatility_bit == 0

    def test_base_8_with_trend_bit_1_gives_score_12(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=110.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.score == 12
        assert result.hex == "C"
        assert result.base == 8
        assert result.trend_bit == 1
        assert result.position_bit == 0
        assert result.volatility_bit == 0

    def test_score_E_format(self):
        result = calculate_state(
            d1_close=110.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=110.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.score == 14
        assert result.hex == "E"

    def test_score_F_format(self):
        result = calculate_state(
            d1_close=110.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=110.0,
            trend_ma_slow=100.0,
            atr_current=4.0,
            atr_previous=3.0,
        )
        assert result.score == 15
        assert result.hex == "F"

    def test_score_C_format(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=110.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.score == 12
        assert result.hex == "C"

    def test_score_3_format(self):
        result = calculate_state(
            d1_close=110.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=4.0,
            atr_previous=3.0,
        )
        assert result.score == 3
        assert result.hex == "3"

    def test_full_combinatorial_coverage(self):
        expected = []
        for base in (0, 8):
            for trend in (0, 1):
                for pos in (0, 2):
                    for vol in (0, 1):
                        score = base + trend * 4 + pos + vol
                        expected.append(score)
        assert len(expected) == 16
        assert sorted(expected) == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


class TestCalculateStatePositionPriority:

    def test_close_above_resistance_gives_breakout(self):
        result = calculate_state(
            d1_close=110.0,
            sr_support=90.0,
            sr_resistance=100.0,
            trend_ma_fast=95.0,
            trend_ma_slow=95.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.position_bit == 2
        assert result.position_label == "上突"

    def test_close_below_support_gives_breakdown(self):
        result = calculate_state(
            d1_close=85.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=95.0,
            trend_ma_slow=95.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.position_bit == 2
        assert result.position_label == "下突"

    def test_close_inside_range_gives_neutral(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=95.0,
            trend_ma_slow=95.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.position_bit == 0
        assert result.position_label == "中"

    def test_close_exactly_at_resistance_is_not_breakout(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=90.0,
            sr_resistance=100.0,
            trend_ma_fast=95.0,
            trend_ma_slow=95.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.position_bit == 0

    def test_close_exactly_at_support_is_not_breakdown(self):
        result = calculate_state(
            d1_close=90.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=95.0,
            trend_ma_slow=95.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.position_bit == 0


class TestTrendDetection:

    def test_bull_trend_fast_above_slow(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=110.0,
            trend_ma_slow=100.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.trend_bit == 1
        assert result.trend_label == "牛"
        assert result.base == 8

    def test_bear_trend_fast_below_slow(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=90.0,
            trend_ma_slow=100.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.trend_bit == 1
        assert result.trend_label == "熊"
        assert result.base == 8

    def test_neutral_trend_fast_equals_slow(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=1.0,
            atr_previous=1.0,
        )
        assert result.trend_bit == 0
        assert result.trend_label == "平"
        assert result.base == 0


class TestVolatilityDetection:

    def test_atr_expanding(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=3.0,
            atr_previous=2.0,
        )
        assert result.volatility_bit == 1
        assert result.volatility_label == "波扩"

    def test_atr_contracting(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.volatility_bit == 0
        assert result.volatility_label == "稳"

    def test_atr_equal_is_stable(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=95.0,
            sr_resistance=105.0,
            trend_ma_fast=100.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=2.0,
        )
        assert result.volatility_bit == 0


# ============================================================
# decode_state_hex: 十六进制 → StateComponents 往返
# ============================================================

class TestDecodeStateHex:

    @pytest.mark.parametrize("hex_val,expected_score", [
        ("0", 0), ("1", 1), ("2", 2), ("3", 3),
        ("4", 4), ("5", 5), ("6", 6), ("7", 7),
        ("8", 8), ("9", 9), ("A", 10), ("B", 11),
        ("C", 12), ("D", 13), ("E", 14), ("F", 15),
        ("-1", -1), ("-C", -12), ("-F", -15),
    ])
    def test_decode_preserves_score(self, hex_val, expected_score):
        result = decode_state_hex(hex_val)
        assert result.score == expected_score
        assert result.hex == hex_val

    def test_roundtrip_positive_scores(self):
        for base in (0, 8):
            for trend in (0, 1):
                for pos in (0, 2):
                    for vol in (0, 1):
                        score = base + trend * 4 + pos + vol
                        original = decode_state_hex(f"{score:X}")
                        assert original.score == score

    def test_roundtrip_E_state(self):
        result = decode_state_hex("E")
        assert result.score == 14
        assert result.base == 8
        assert result.trend_bit == 1
        assert result.position_bit == 1
        assert result.volatility_bit == 0

    def test_roundtrip_F_state(self):
        result = decode_state_hex("F")
        assert result.score == 15
        assert result.base == 8
        assert result.trend_bit == 1
        assert result.position_bit == 1
        assert result.volatility_bit == 1

    def test_decode_negative_C_has_bear_context(self):
        result = decode_state_hex("-C")
        assert result.score == -12
        assert result.trend_label == "熊"

    def test_decode_negative_F_bear_context(self):
        result = decode_state_hex("-F")
        assert result.score == -15


# ============================================================
# is_ef_state: score ∈ {14, 15} 且为正
# ============================================================

class TestIsEfState:

    def test_E_is_ef(self):
        assert is_ef_state("E") is True

    def test_F_is_ef(self):
        assert is_ef_state("F") is True

    def test_C_is_not_ef(self):
        assert is_ef_state("C") is False

    def test_0_is_not_ef(self):
        assert is_ef_state("0") is False

    def test_negative_E_is_not_ef(self):
        assert is_ef_state("-E") is False

    def test_negative_F_is_not_ef(self):
        assert is_ef_state("-F") is False

    def test_none_is_not_ef(self):
        assert is_ef_state(None) is False

    def test_invalid_hex_is_not_ef(self):
        assert is_ef_state("GG") is False

    def test_empty_string_is_not_ef(self):
        assert is_ef_state("") is False

    @pytest.mark.parametrize("hex_val", ["0", "1", "2", "3", "4", "5", "6", "7",
                                          "8", "9", "A", "B", "C", "D",
                                          "-1", "-2", "-3", "-8", "-A", "-C", "-E", "-F"])
    def test_non_EF_states_are_all_false(self, hex_val):
        assert is_ef_state(hex_val) is False


# ============================================================
# StateComponents dataclass
# ============================================================

class TestStateComponents:

    def test_dataclass_fields(self):
        s = StateComponents(
            base=8, trend_bit=1, position_bit=2, volatility_bit=0,
            comp_label="扩", trend_label="牛", position_label="上突",
            volatility_label="稳", score=14, hex="E",
        )
        assert s.base == 8
        assert s.hex == "E"
        assert s.score == 14


# ============================================================
# 符号裁决：位置优先
# ============================================================

class TestSignArbitration:

    def test_bear_breakdown_negative_state(self):
        result = calculate_state(
            d1_close=85.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=80.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.position_bit == 2
        assert result.position_label == "下突"
        assert result.trend_label == "熊"

    def test_bull_breakout_positive_state(self):
        result = calculate_state(
            d1_close=115.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=120.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.position_bit == 2
        assert result.position_label == "上突"
        assert result.trend_label == "牛"

    def test_score_C_bull_without_breakout(self):
        result = calculate_state(
            d1_close=100.0,
            sr_support=90.0,
            sr_resistance=110.0,
            trend_ma_fast=120.0,
            trend_ma_slow=100.0,
            atr_current=2.0,
            atr_previous=3.0,
        )
        assert result.score == 12
        assert result.hex == "C"
