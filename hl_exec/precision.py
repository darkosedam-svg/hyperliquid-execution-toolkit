"""Tick-size and lot-size aware rounding for Hyperliquid orders.

Hyperliquid enforces per-asset szDecimals and pxDecimals. Orders that violate
these rules are rejected by the exchange.

Key rounding rules (DO NOT change without understanding why):

  * Sizes always round DOWN. If we round up, we may exceed available margin
    or trade more than the strategy intended. Down is the safe direction.

  * Prices round toward the SAFER side per direction:
      - BUY orders round price DOWN (we don't want to overpay)
      - SELL orders round price UP (we don't want to undersell)

These rules apply equally in backtests and live execution. Backtests that
round differently will diverge from live results.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_UP, Decimal

from .types import AssetSpec, Side


def round_size(size: Decimal, spec: AssetSpec) -> Decimal:
    """Round size DOWN to the asset's szDecimals.

    Rounding direction is unconditionally DOWN. Never round size up under any
    circumstance — it can cause order rejection (insufficient margin) or
    silent over-allocation.

    Args:
        size: Desired size in asset units (e.g. BTC, ETH).
        spec: AssetSpec for the asset.

    Returns:
        Size rounded down to szDecimals precision.

    Examples:
        >>> from decimal import Decimal
        >>> spec = AssetSpec("BTC", sz_decimals=4, px_decimals=1,
        ...                  min_size=Decimal("0.0001"), max_leverage=50)
        >>> round_size(Decimal("0.000187"), spec)
        Decimal('0.0001')
        >>> round_size(Decimal("0.5234567"), spec)
        Decimal('0.5234')
    """
    quant = Decimal(10) ** -spec.sz_decimals
    return size.quantize(quant, rounding=ROUND_DOWN)


def round_price(price: Decimal, side: Side, spec: AssetSpec) -> Decimal:
    """Round price toward the safer side for the given order direction.

    For BUY orders: round DOWN (don't pay more than intended).
    For SELL orders: round UP (don't receive less than intended).

    This means: a BUY limit at the best ask rounds to a price slightly below
    the ask if rounding is needed, which is post-only-friendly. A SELL limit
    at the best bid rounds slightly above the bid for the same reason.

    Args:
        price: Desired price.
        side: Order side, determines rounding direction.
        spec: AssetSpec for the asset.

    Returns:
        Price rounded to pxDecimals precision on the safer side.

    Examples:
        >>> from decimal import Decimal
        >>> spec = AssetSpec("ETH", sz_decimals=4, px_decimals=2,
        ...                  min_size=Decimal("0.0001"), max_leverage=50)
        >>> round_price(Decimal("3247.997"), Side.BUY, spec)
        Decimal('3247.99')
        >>> round_price(Decimal("3247.991"), Side.SELL, spec)
        Decimal('3248.00')
    """
    quant = Decimal(10) ** -spec.px_decimals
    rounding = ROUND_DOWN if side == Side.BUY else ROUND_UP
    return price.quantize(quant, rounding=rounding)


def validate_size(size: Decimal, spec: AssetSpec) -> None:
    """Validate that a size is acceptable for the asset.

    Raises:
        ValueError: if size is non-positive, below min_size, or has more
            precision than szDecimals allows.
    """
    if size <= 0:
        raise ValueError(f"Size must be positive, got {size}")
    if size < spec.min_size:
        raise ValueError(
            f"Size {size} below min_size {spec.min_size} for {spec.symbol}"
        )
    rounded = round_size(size, spec)
    if rounded != size:
        raise ValueError(
            f"Size {size} has more precision than "
            f"szDecimals={spec.sz_decimals} for {spec.symbol}. "
            f"Use round_size() before validating."
        )


def usd_to_size(usd_amount: Decimal, price: Decimal, spec: AssetSpec) -> Decimal:
    """Convert a USD-denominated order size to asset units with correct rounding.

    Always rounds DOWN to ensure we don't exceed the USD budget. The actual
    notional after rounding will be slightly less than `usd_amount`.

    Args:
        usd_amount: Target notional in USD.
        price: Reference price (use best-ask for buys, best-bid for sells).
        spec: AssetSpec for the asset.

    Returns:
        Size in asset units, rounded down to szDecimals.

    Raises:
        ValueError: if the resulting size is below min_size for the asset.

    Examples:
        >>> from decimal import Decimal
        >>> spec = AssetSpec("ETH", sz_decimals=4, px_decimals=2,
        ...                  min_size=Decimal("0.0001"), max_leverage=50)
        >>> usd_to_size(Decimal("100"), Decimal("3247.50"), spec)
        Decimal('0.0307')
    """
    raw_size = usd_amount / price
    rounded = round_size(raw_size, spec)
    if rounded < spec.min_size:
        raise ValueError(
            f"USD amount ${usd_amount} at price ${price} produces size "
            f"{rounded}, below min_size {spec.min_size} for {spec.symbol}"
        )
    return rounded


def effective_fee_rate(
    maker_fill_rate: Decimal,
    maker_fee_bps: Decimal,
    taker_fee_bps: Decimal,
) -> Decimal:
    """Compute realistic effective fee rate given an empirical maker fill rate.

    Most strategies overestimate maker fill rate. Real-world rates for
    momentum/breakout strategies are typically 30-50%, not 100%. Apply this
    to size your strategy's fee load realistically.

    Args:
        maker_fill_rate: Fraction of orders that fill as makers (0.0 to 1.0).
        maker_fee_bps: Maker fee in basis points (e.g. Decimal("1.5") = 0.015%).
        taker_fee_bps: Taker fee in basis points.

    Returns:
        Blended effective fee in basis points.

    Examples:
        >>> from decimal import Decimal
        >>> effective_fee_rate(Decimal("0.4"), Decimal("1.5"), Decimal("4.5"))
        Decimal('3.3')
    """
    if not 0 <= maker_fill_rate <= 1:
        raise ValueError(f"maker_fill_rate must be in [0, 1], got {maker_fill_rate}")
    return maker_fill_rate * maker_fee_bps + (1 - maker_fill_rate) * taker_fee_bps
