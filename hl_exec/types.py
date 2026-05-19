"""Core data types for the execution toolkit.

All monetary values use Decimal to avoid float arithmetic drift in PnL accounting.
Timestamps are timezone-aware UTC datetimes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self == Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class AssetSpec:
    """Per-asset precision and trading rules from Hyperliquid metadata.
    
    Pulled from the /info endpoint at connect time and cached. These values
    drive all size and price rounding logic.
    """
    symbol: str
    sz_decimals: int  # max decimals for size
    px_decimals: int  # max decimals for price
    min_size: Decimal
    max_leverage: int
    is_perp: bool = True


@dataclass
class OrderRequest:
    """A pre-validated order ready for submission."""
    symbol: str
    side: Side
    type: OrderType
    size: Decimal
    price: Optional[Decimal] = None
    post_only: bool = False
    reduce_only: bool = False
    client_order_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders require a price")
        if self.type == OrderType.MARKET and self.post_only:
            raise ValueError("Market orders cannot be post_only")
        if self.size <= 0:
            raise ValueError(f"Size must be positive, got {self.size}")


@dataclass
class Fill:
    """A filled order or partial fill."""
    symbol: str
    side: Side
    size: Decimal
    avg_price: Decimal
    fee_paid: Decimal
    timestamp: datetime
    is_maker: bool
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None

    @property
    def notional(self) -> Decimal:
        return self.size * self.avg_price


@dataclass
class Position:
    """Current position state with funding accrued through latest mark.
    
    `size` is signed: positive = long, negative = short, zero = flat.
    """
    symbol: str
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    funding_paid: Decimal  # cumulative; positive = paid out, negative = received
    margin_used: Decimal
    last_updated: datetime = field(default_factory=lambda: datetime.now())

    @property
    def is_long(self) -> bool:
        return self.size > 0

    @property
    def is_short(self) -> bool:
        return self.size < 0

    @property
    def is_flat(self) -> bool:
        return self.size == 0

    @property
    def notional(self) -> Decimal:
        return abs(self.size) * self.mark_price

    @property
    def total_pnl(self) -> Decimal:
        """Realized + unrealized, net of funding paid."""
        return self.realized_pnl + self.unrealized_pnl - self.funding_paid
