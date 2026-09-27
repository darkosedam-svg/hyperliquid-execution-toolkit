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
