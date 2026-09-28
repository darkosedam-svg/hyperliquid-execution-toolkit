"""Tests for hl_exec.precision: tick/lot-size rounding and fee helpers.

Covers the properties documented in the module docstring:
  * sizes always round DOWN, never up
  * BUY prices round DOWN, SELL prices round UP
  * exact multiples of the precision step are left unchanged
  * sizes that round down to less than the precision step become zero
  * significant-figure limits (px_decimals / sz_decimals == 0) are honored
"""

from decimal import Decimal

import pytest

from hl_exec.precision import (
    effective_fee_rate,
    round_price,
    round_size,
    usd_to_size,
    validate_size,
)
from hl_exec.types import AssetSpec, Side


def _spec(sz_decimals: int = 4, px_decimals: int = 2, min_size: str = "0.0001") -> AssetSpec:
    return AssetSpec(
        symbol="TEST",
        sz_decimals=sz_decimals,
        px_decimals=px_decimals,
        min_size=Decimal(min_size),
        max_leverage=50,
    )


class TestRoundSize:
    def test_exact_multiple_is_unchanged(self):
        spec = _spec(sz_decimals=4)
        assert round_size(Decimal("0.5234"), spec) == Decimal("0.5234")

    def test_rounds_down_never_up(self):
        spec = _spec(sz_decimals=4)
        # 0.52349999 is one unit below the next 4-decimal step; must not
        # round up to 0.5235.
        assert round_size(Decimal("0.52349999"), spec) == Decimal("0.5234")

    def test_rounds_down_at_the_halfway_point(self):
        spec = _spec(sz_decimals=4)
        # Ordinary "round half up/even" would push this to 0.5235; the
        # rule here is unconditional truncation toward zero.
        assert round_size(Decimal("0.52345"), spec) == Decimal("0.5234")

    def test_tiny_size_below_one_step_truncates_to_zero(self):
        spec = _spec(sz_decimals=4)
        # A size smaller than the smallest representable step rounds down
        # to exactly zero, not up to the smallest step. Callers that don't
        # separately check min_size can silently end up with a zero order.
        assert round_size(Decimal("0.00004"), spec) == Decimal("0.0000")

    def test_zero_size_decimals_rounds_to_whole_units(self):
        spec = _spec(sz_decimals=0)
        assert round_size(Decimal("3.9"), spec) == Decimal("3")

    def test_many_size_decimals(self):
        spec = _spec(sz_decimals=8)
        assert round_size(Decimal("1.123456789"), spec) == Decimal("1.12345678")

    def test_result_precision_matches_sz_decimals(self):
        spec = _spec(sz_decimals=4)
        result = round_size(Decimal("1"), spec)
        # quantize() pads/truncates the exponent to match; confirm the
        # returned Decimal actually carries 4 places, not just the value.
        assert result.as_tuple().exponent == -4


class TestRoundPrice:
    def test_exact_multiple_is_unchanged_both_sides(self):
        spec = _spec(px_decimals=2)
        assert round_price(Decimal("3247.99"), Side.BUY, spec) == Decimal("3247.99")
        assert round_price(Decimal("3247.99"), Side.SELL, spec) == Decimal("3247.99")

    def test_buy_rounds_down(self):
        spec = _spec(px_decimals=2)
        assert round_price(Decimal("3247.999"), Side.BUY, spec) == Decimal("3247.99")

    def test_sell_rounds_up(self):
        spec = _spec(px_decimals=2)
        assert round_price(Decimal("3247.001"), Side.SELL, spec) == Decimal("3247.01")

    def test_buy_and_sell_diverge_on_the_same_input(self):
        spec = _spec(px_decimals=2)
        price = Decimal("100.005")
        buy = round_price(price, Side.BUY, spec)
        sell = round_price(price, Side.SELL, spec)
        assert buy == Decimal("100.00")
        assert sell == Decimal("100.01")
        assert buy < sell

    def test_zero_price_decimals_rounds_to_whole_units(self):
        spec = _spec(px_decimals=0)
        assert round_price(Decimal("100.5"), Side.BUY, spec) == Decimal("100")
        assert round_price(Decimal("100.5"), Side.SELL, spec) == Decimal("101")

    def test_result_precision_matches_px_decimals(self):
        spec = _spec(px_decimals=2)
        result = round_price(Decimal("100"), Side.BUY, spec)
        assert result.as_tuple().exponent == -2


class TestValidateSize:
    def test_accepts_a_correctly_rounded_size(self):
        spec = _spec(sz_decimals=4, min_size="0.0001")
        validate_size(Decimal("0.5234"), spec)  # must not raise

    def test_rejects_zero(self):
        spec = _spec()
        with pytest.raises(ValueError, match="positive"):
            validate_size(Decimal("0"), spec)

    def test_rejects_negative(self):
        spec = _spec()
        with pytest.raises(ValueError, match="positive"):
            validate_size(Decimal("-1"), spec)

    def test_rejects_below_min_size(self):
        spec = _spec(sz_decimals=4, min_size="0.001")
        with pytest.raises(ValueError, match="below min_size"):
            validate_size(Decimal("0.0005"), spec)

    def test_rejects_size_with_excess_precision(self):
        spec = _spec(sz_decimals=4, min_size="0.0001")
        with pytest.raises(ValueError, match="more precision"):
            validate_size(Decimal("0.12345"), spec)


class TestUsdToSize:
    def test_matches_documented_example(self):
        spec = _spec(sz_decimals=4, px_decimals=2, min_size="0.0001")
        assert usd_to_size(Decimal("100"), Decimal("3247.50"), spec) == Decimal("0.0307")

    def test_exact_division_is_unchanged(self):
        spec = _spec(sz_decimals=4, min_size="0.0001")
        # 100 / 2000 == 0.05 exactly, already at 4-decimal precision.
        assert usd_to_size(Decimal("100"), Decimal("2000"), spec) == Decimal("0.0500")

    def test_rounds_down_rather_than_exceeding_budget(self):
        spec = _spec(sz_decimals=4, min_size="0.0001")
        # 100 / 3 = 33.333...; rounding up would spend more than $100.
        size = usd_to_size(Decimal("100"), Decimal("3"), spec)
        assert size == Decimal("33.3333")
        assert size * Decimal("3") <= Decimal("100")

    def test_raises_when_result_is_exactly_at_min_size_boundary_minus_one_step(self):
        spec = _spec(sz_decimals=4, min_size="0.0010")
        # price chosen so raw_size rounds down to just under min_size.
        with pytest.raises(ValueError, match="below min_size"):
            usd_to_size(Decimal("0.0009"), Decimal("1"), spec)

    def test_accepts_result_exactly_at_min_size(self):
        spec = _spec(sz_decimals=4, min_size="0.0010")
        size = usd_to_size(Decimal("0.0010"), Decimal("1"), spec)
        assert size == Decimal("0.0010")


class TestEffectiveFeeRate:
    def test_matches_documented_example(self):
        result = effective_fee_rate(Decimal("0.4"), Decimal("1.5"), Decimal("4.5"))
        assert result == Decimal("3.3")

    def test_all_maker_uses_maker_fee(self):
        result = effective_fee_rate(Decimal("1"), Decimal("1.5"), Decimal("4.5"))
        assert result == Decimal("1.5")

    def test_all_taker_uses_taker_fee(self):
        result = effective_fee_rate(Decimal("0"), Decimal("1.5"), Decimal("4.5"))
        assert result == Decimal("4.5")

    def test_rejects_fill_rate_above_one(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            effective_fee_rate(Decimal("1.1"), Decimal("1.5"), Decimal("4.5"))

    def test_rejects_negative_fill_rate(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            effective_fee_rate(Decimal("-0.1"), Decimal("1.5"), Decimal("4.5"))
