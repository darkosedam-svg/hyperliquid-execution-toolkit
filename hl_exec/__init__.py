"""hyperliquid-execution-toolkit: execution-correctness primitives for HL perps.

This package currently provides tick/lot-size-correct order math, a
self-healing websocket with reconnect/backoff and subscription replay, and a
blended fee-rate helper. Order placement and account-state tracking on
`ExecutionClient` are still stubs — see the "Roadmap / not yet implemented"
section of README.md. Strategy logic is left to the user.

Typical usage (what actually runs today):

    from decimal import Decimal
    from hl_exec.precision import round_size, round_price, usd_to_size
    from hl_exec.types import AssetSpec, Side

    spec = AssetSpec("ETH", sz_decimals=4, px_decimals=2,
                      min_size=Decimal("0.0001"), max_leverage=50)
    size = usd_to_size(Decimal("100"), Decimal("3247.50"), spec)
"""

from .client import ExecutionClient
from .precision import round_price, round_size, usd_to_size, validate_size
from .types import (
    AssetSpec,
    Fill,
    OrderRequest,
    OrderType,
    Position,
    Side,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "ExecutionClient",
    # Types
    "AssetSpec",
    "Fill",
    "OrderRequest",
    "OrderType",
    "Position",
    "Side",
    # Precision utilities
    "round_price",
    "round_size",
    "usd_to_size",
    "validate_size",
]
