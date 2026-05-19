"""Main ExecutionClient interface.

The client manages connection lifecycle, order placement with correct precision,
websocket reconnection with replay, and position tracking with funding accrual.

Most methods are stubbed pending full implementation — see ROADMAP.md for the
implementation order. The precision-handling logic in `hl_exec.precision` is
already production-ready and should be used directly even before the rest of
the client is complete.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from .precision import round_price, round_size, usd_to_size, validate_size
from .types import (
    AssetSpec,
    Fill,
    OrderRequest,
    OrderType,
    Position,
    Side,
)

logger = logging.getLogger(__name__)


class ExecutionClient:
    """High-level execution client for Hyperliquid perpetuals.

    Lifecycle:
        client = ExecutionClient(wallet_address, private_key, testnet=True)
        await client.connect()           # fetches metadata, opens WS
        ...
        await client.close()             # graceful shutdown

    All sizes accept Decimal for precision. Floats are rejected at runtime
    to prevent accumulated drift in PnL accounting.
    """

    def __init__(
        self,
        wallet_address: str,
        private_key: str,
        testnet: bool = True,
        ws_heartbeat_interval: int = 30,
        ws_reconnect_max_backoff: int = 60,
    ):
        self.wallet_address = wallet_address
        self._private_key = private_key
        self.testnet = testnet
        self._ws_heartbeat_interval = ws_heartbeat_interval
        self._ws_reconnect_max_backoff = ws_reconnect_max_backoff

        self._asset_specs: dict[str, AssetSpec] = {}
        self._positions: dict[str, Position] = {}
        self._connected = False
        self._ws_task: Optional[asyncio.Task] = None

    # --------------------------------------------------------------------------
    # Lifecycle
    # --------------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish connection and prepare for trading.

        Steps:
          1. GET /info → meta → cache asset specs
          2. Open websocket
          3. Subscribe to userFills, userEvents, userFundings
          4. Start heartbeat task

        Raises:
            ConnectionError: if any step fails.
        """
        # TODO: implement
        # See: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
        raise NotImplementedError("Wire up /info → meta and ws subscriptions")

    async def close(self) -> None:
        """Cancel all open orders, close websocket, release resources."""
        # TODO: implement
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # Order placement
    # --------------------------------------------------------------------------

    async def market_buy(self, symbol: str, size_usd: Decimal) -> Fill:
        """Execute a market buy with USD-denominated sizing.

        Internally:
          1. Get current best ask
          2. Convert USD → asset size with downward rounding
          3. Validate size against asset spec
          4. Submit market order
          5. Aggregate any partial fills into a single Fill

        Args:
            symbol: Asset symbol (e.g. "ETH", "BTC").
            size_usd: Target notional in USD. Must be > 0.

        Returns:
            Fill with average fill price across any partial fills.
        """
        spec = self._get_spec(symbol)
        # TODO: get best ask, convert size, place order
        # best_ask = self._get_best_ask(symbol)
        # size = usd_to_size(size_usd, best_ask, spec)
        # validate_size(size, spec)
        # request = OrderRequest(symbol=symbol, side=Side.BUY,
        #                        type=OrderType.MARKET, size=size)
        # return await self._submit(request)
        raise NotImplementedError

    async def market_sell(self, symbol: str, size_usd: Decimal) -> Fill:
        """Execute a market sell with USD-denominated sizing."""
        # TODO: implement (mirror of market_buy)
        raise NotImplementedError

    async def limit_buy(
        self,
        symbol: str,
        size_usd: Decimal,
        price_offset_bps: int = 0,
        post_only: bool = True,
    ) -> OrderRequest:
        """Place a limit buy at price = best_bid * (1 + price_offset_bps/10000).

        Args:
            symbol: Asset symbol.
            size_usd: Target notional in USD.
            price_offset_bps: Offset from best bid in basis points. Negative
                offsets place the order below the bid (more passive). Zero
                places at the bid.
            post_only: If True, order will be canceled if it would cross the
                spread. Recommended for maker-rebate strategies.

        Returns:
            OrderRequest representing the resting order. Use the order ID to
            cancel or query status.
        """
        # TODO: implement
        raise NotImplementedError

    async def limit_sell(
        self,
        symbol: str,
        size_usd: Decimal,
        price_offset_bps: int = 0,
        post_only: bool = True,
    ) -> OrderRequest:
        """Place a limit sell at price = best_ask * (1 + price_offset_bps/10000)."""
        # TODO: implement
        raise NotImplementedError

    async def cancel_all(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders, optionally filtered by symbol.

        Returns:
            Number of orders canceled.
        """
        # TODO: implement
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # State queries
    # --------------------------------------------------------------------------

    async def get_position(self, symbol: str) -> Optional[Position]:
        """Return current position with funding accrued through latest mark.

        Returns None if no position is open in the symbol.
        """
        # TODO: implement using cached _positions, refreshed via WS userEvents
        raise NotImplementedError

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[OrderRequest]:
        """List currently-open orders, optionally filtered by symbol."""
        # TODO: implement
        raise NotImplementedError

    async def get_account_value(self) -> Decimal:
        """Return total account value (cash + unrealized PnL)."""
        # TODO: implement
        raise NotImplementedError

    # --------------------------------------------------------------------------
    # Internal
    # --------------------------------------------------------------------------

    def _get_spec(self, symbol: str) -> AssetSpec:
        if not self._connected:
            raise RuntimeError("Client not connected. Call await client.connect() first.")
        if symbol not in self._asset_specs:
            raise ValueError(
                f"Unknown symbol {symbol!r}. Available: {list(self._asset_specs)}"
            )
        return self._asset_specs[symbol]

    async def _submit(self, request: OrderRequest) -> Fill:
        """Submit an order request, handle response, return aggregated Fill."""
        # TODO: sign, POST to /exchange, parse response, handle errors
        raise NotImplementedError
