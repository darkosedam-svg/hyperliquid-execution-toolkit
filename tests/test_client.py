"""Tests for ExecutionClient.get_position (cached-state read path)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from hl_exec.client import ExecutionClient
from hl_exec.types import Position


def _make_client() -> ExecutionClient:
    return ExecutionClient(
        wallet_address="0xTEST",
        private_key="0xTEST_KEY",
        testnet=True,
    )


def _make_position(symbol: str = "ETH") -> Position:
    return Position(
        symbol=symbol,
        size=Decimal("1.5"),
        entry_price=Decimal("3000"),
        mark_price=Decimal("3100"),
        unrealized_pnl=Decimal("150"),
        realized_pnl=Decimal("0"),
        funding_paid=Decimal("2.5"),
        margin_used=Decimal("450"),
        last_updated=datetime.now(timezone.utc),
    )


class TestGetPosition:
    async def test_raises_if_not_connected(self):
        client = _make_client()

        with pytest.raises(RuntimeError, match="not connected"):
            await client.get_position("ETH")

    async def test_returns_none_when_no_position_cached(self):
        client = _make_client()
        client._connected = True

        result = await client.get_position("ETH")

        assert result is None

    async def test_returns_cached_position_for_symbol(self):
        client = _make_client()
        client._connected = True
        position = _make_position("ETH")
        client._positions["ETH"] = position

        result = await client.get_position("ETH")

        assert result is position
        assert result.size == Decimal("1.5")
        assert result.is_long

    async def test_ignores_other_symbols(self):
        client = _make_client()
        client._connected = True
        client._positions["BTC"] = _make_position("BTC")

        result = await client.get_position("ETH")

        assert result is None


class TestOrderPlacementStubs:
    """Pins the exact exceptions the README documents for the unimplemented
    order-placement methods (see "Roadmap / not yet implemented" and the
    quick-start note about ExecutionClient in README.md).

    market_buy is a special case: it calls the same connection-state check
    that get_position uses (via `_get_spec`), so before `connect()` it
    raises RuntimeError, not NotImplementedError — it would only reach its
    own NotImplementedError once that check passed, which it can't yet
    since connect() itself is unimplemented. The other three methods have
    no such check and raise NotImplementedError immediately.
    """

    async def test_market_buy_raises_runtime_error_when_not_connected(self):
        client = _make_client()
        with pytest.raises(RuntimeError, match="not connected"):
            await client.market_buy("ETH", Decimal("100"))

    async def test_market_sell_raises_not_implemented_immediately(self):
        client = _make_client()
        with pytest.raises(NotImplementedError):
            await client.market_sell("ETH", Decimal("100"))

    async def test_limit_buy_raises_not_implemented_immediately(self):
        client = _make_client()
        with pytest.raises(NotImplementedError):
            await client.limit_buy("ETH", Decimal("100"))

    async def test_limit_sell_raises_not_implemented_immediately(self):
        client = _make_client()
        with pytest.raises(NotImplementedError):
            await client.limit_sell("ETH", Decimal("100"))
