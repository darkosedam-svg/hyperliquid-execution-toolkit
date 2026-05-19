"""hyperliquid-execution-toolkit: production execution primitives for HL perps.

This package handles execution correctness — order placement that respects
tick/lot precision, websocket reconnection logic, fee-aware sizing, and
mark-price-correct risk checks. Strategy logic is left to the user.

Typical usage:

    from hl_exec import ExecutionClient
    
    client = ExecutionClient(
        wallet_address="0x...",
        private_key="0x...",
        testnet=True,
    )
    await client.connect()
    fill = await client.market_buy("ETH", size_usd=Decimal("100"))
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
