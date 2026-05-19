"""Tests for the websocket module.

Uses an in-process mock WS server (websockets.serve) to test real wire
protocol behavior — connection lifecycle, reconnection, subscription
persistence, heartbeat timeouts — without any network dependency.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import pytest_asyncio
import websockets

from hl_exec.websocket import (
    ConnectionState,
    HyperliquidWebSocket,
    Subscription,
)


# -----------------------------------------------------------------------------
# Mock WS server fixture
# -----------------------------------------------------------------------------

class MockHLServer:
    """In-process mock that mimics HL's WS protocol just enough for tests."""

    def __init__(self):
        self.received_messages: list[dict[str, Any]] = []
        self.connections_count = 0
        self._active_connections: set = set()
        self._server: websockets.WebSocketServer | None = None
        self._port: int | None = None
        self._next_event: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._drop_next_connection = False
        self._silent_mode = False  # if True, server stops responding to pings

    @property
    def url(self) -> str:
        assert self._port is not None
        return f"ws://localhost:{self._port}"

    async def start(self) -> None:
        async def handler(ws):
            self.connections_count += 1
            self._active_connections.add(ws)
            if self._drop_next_connection:
                self._drop_next_connection = False
                await ws.close(code=1011, reason="forced drop")
                self._active_connections.discard(ws)
                return

            send_task = asyncio.create_task(self._sender(ws))
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    self.received_messages.append(msg)
                    if msg.get("method") == "subscribe":
                        await ws.send(json.dumps({
                            "channel": "subscriptionResponse",
                            "data": msg.get("subscription"),
                        }))
                    elif msg.get("method") == "ping" and not self._silent_mode:
                        await ws.send(json.dumps({"channel": "pong"}))
            finally:
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass
                self._active_connections.discard(ws)

        self._server = await websockets.serve(handler, "localhost", 0)
        self._port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def force_disconnect_all(self) -> None:
        """Close every active connection. Used to test client reconnection."""
        for ws in list(self._active_connections):
            try:
                await ws.close(code=1011)
            except Exception:
                pass

    async def push_event(self, event: dict[str, Any]) -> None:
        """Queue an event to be sent to the next connected client."""
        await self._next_event.put(event)

    def force_next_connection_to_drop(self) -> None:
        self._drop_next_connection = True

    def go_silent(self) -> None:
        """Stop responding to pings, simulating a stuck/zombie connection."""
        self._silent_mode = True

    async def _sender(self, ws) -> None:
        while True:
            event = await self._next_event.get()
            try:
                await ws.send(json.dumps(event))
            except websockets.ConnectionClosed:
                # Re-queue so a future connection sees it
                await self._next_event.put(event)
                return


@pytest_asyncio.fixture
async def server():
    s = MockHLServer()
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


# -----------------------------------------------------------------------------
# Subscription
# -----------------------------------------------------------------------------

class TestSubscription:
    def test_to_message_includes_type_and_params(self):
        sub = Subscription("userFills", {"user": "0xabc"})
        msg = sub.to_message()
        assert msg == {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": "0xabc"},
        }

    def test_to_message_with_empty_params(self):
        sub = Subscription("trades")
        msg = sub.to_message()
        assert msg == {"method": "subscribe", "subscription": {"type": "trades"}}

    def test_key_is_stable_for_same_params(self):
        # Different dict insertion order should yield same key
        a = Subscription("l2Book", {"coin": "BTC", "depth": 10})
        b = Subscription("l2Book", {"depth": 10, "coin": "BTC"})
        assert a.key() == b.key()

    def test_key_distinguishes_different_subscriptions(self):
        a = Subscription("userFills", {"user": "0xabc"})
        b = Subscription("userFills", {"user": "0xdef"})
        c = Subscription("trades", {"coin": "ETH"})
        assert a.key() != b.key()
        assert a.key() != c.key()


# -----------------------------------------------------------------------------
# Connection lifecycle
# -----------------------------------------------------------------------------

class TestLifecycle:
    async def test_start_connects_and_reaches_connected_state(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        assert ws.state == ConnectionState.CONNECTED
        assert ws.is_connected is True
        await ws.stop()

    async def test_stop_transitions_to_closed(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        await ws.stop()
        assert ws.state == ConnectionState.CLOSED
        assert ws.is_connected is False

    async def test_double_start_raises(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        with pytest.raises(RuntimeError, match="already started"):
            await ws.start()
        await ws.stop()

    async def test_stop_without_start_is_noop(self):
        ws = _ws_with_url("ws://localhost:1")  # bogus url; never started
        await ws.stop()  # should not raise


# -----------------------------------------------------------------------------
# Subscription handling
# -----------------------------------------------------------------------------

class TestSubscriptions:
    async def test_subscribe_after_connect_sends_message(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        await ws.subscribe("userFills", {"user": "0xabc"})
        await _wait_for(lambda: any(
            m.get("subscription", {}).get("type") == "userFills"
            for m in server.received_messages
        ))
        await ws.stop()

    async def test_duplicate_subscribe_dedup_by_key(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        await ws.subscribe("trades", {"coin": "BTC"})
        await ws.subscribe("trades", {"coin": "BTC"})
        await asyncio.sleep(0.1)
        # Both calls send messages but only one persisted subscription
        assert len(ws._subscriptions) == 1
        await ws.stop()

    async def test_unsubscribe_removes_from_state(self, server):
        ws = _ws_with_url(server.url)
        await ws.start()
        await ws.subscribe("trades", {"coin": "BTC"})
        assert len(ws._subscriptions) == 1
        await ws.unsubscribe("trades", {"coin": "BTC"})
        assert len(ws._subscriptions) == 0
        await ws.stop()


# -----------------------------------------------------------------------------
# Event delivery
# -----------------------------------------------------------------------------

class TestEventDelivery:
    async def test_event_handler_receives_messages(self, server):
        events_received: list[dict] = []

        async def handler(msg):
            events_received.append(msg)

        ws = _ws_with_url(server.url, on_event=handler)
        await ws.start()
        await ws.subscribe("trades", {"coin": "BTC"})

        await server.push_event({
            "channel": "trades",
            "data": [{"px": "63000", "sz": "0.1"}],
        })
        await _wait_for(lambda: len(events_received) >= 1)

        assert events_received[0]["channel"] == "trades"
        await ws.stop()

    async def test_pong_messages_are_filtered(self, server):
        events_received: list[dict] = []

        async def handler(msg):
            events_received.append(msg)

        ws = _ws_with_url(server.url, on_event=handler, heartbeat_interval=0.1)
        await ws.start()
        await asyncio.sleep(0.5)  # let several pings/pongs cycle

        # No pongs leaked into the user handler
        for ev in events_received:
            assert ev.get("channel") != "pong"
        await ws.stop()

    async def test_handler_exception_does_not_kill_connection(self, server):
        call_count = 0

        async def handler(msg):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("intentional test failure")

        ws = _ws_with_url(server.url, on_event=handler)
        await ws.start()
        await ws.subscribe("trades", {"coin": "BTC"})

        await server.push_event({"channel": "trades", "data": "1"})
        await server.push_event({"channel": "trades", "data": "2"})
        await _wait_for(lambda: call_count >= 2)

        # Connection still healthy after handler raised
        assert ws.is_connected
        await ws.stop()


# -----------------------------------------------------------------------------
# Reconnection
# -----------------------------------------------------------------------------

class TestReconnection:
    async def test_subscriptions_resubscribed_on_reconnect(self, server):
        ws = _ws_with_url(server.url, max_backoff=0.5)
        await ws.start()
        await ws.subscribe("userFills", {"user": "0xabc"})
        await ws.subscribe("trades", {"coin": "BTC"})
        await asyncio.sleep(0.2)

        initial_subs = sum(
            1 for m in server.received_messages if m.get("method") == "subscribe"
        )
        assert initial_subs == 2

        # Force disconnect by killing every active connection
        await server.force_disconnect_all()

        # Wait for client to reconnect
        await _wait_for(lambda: server.connections_count >= 2, timeout=5.0)
        await asyncio.sleep(0.3)  # give resubscriptions time to flush

        # Both subscriptions should have been re-sent
        total_subs = sum(
            1 for m in server.received_messages if m.get("method") == "subscribe"
        )
        assert total_subs >= 4  # 2 original + 2 after reconnect
        await ws.stop()

    async def test_reconcile_callback_fires_on_reconnect(self, server):
        reconcile_calls = 0

        async def reconciler():
            nonlocal reconcile_calls
            reconcile_calls += 1

        ws = _ws_with_url(server.url, on_reconnect=reconciler, max_backoff=0.5)
        await ws.start()
        await asyncio.sleep(0.1)
        assert reconcile_calls == 1  # fires on first connect too

        # Force disconnect
        await server.force_disconnect_all()
        await _wait_for(lambda: reconcile_calls >= 2, timeout=5.0)
        await ws.stop()

    async def test_silent_server_triggers_heartbeat_timeout(self, server):
        """If server stops responding to pings, client detects stale and reconnects."""
        ws = _ws_with_url(
            server.url,
            heartbeat_interval=0.1,
            heartbeat_timeout=0.3,
            max_backoff=0.5,
        )
        await ws.start()
        await asyncio.sleep(0.1)
        initial_connections = server.connections_count

        # Server goes silent — no pongs, no events
        server.go_silent()
        # We also need to suppress incoming traffic to trigger the timeout
        # The handler still echoes subscriptionResponses, but those only fire
        # on subscribe. With no events flowing, last_message_at goes stale.

        await _wait_for(
            lambda: server.connections_count > initial_connections,
            timeout=3.0,
        )
        await ws.stop()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _ws_with_url(url: str, **overrides) -> HyperliquidWebSocket:
    """Construct a HyperliquidWebSocket pointing at a custom URL.

    The class's __init__ chooses URL from the testnet flag; we override it
    directly here for tests.
    """
    ws = HyperliquidWebSocket(testnet=True, **overrides)
    ws._url = url
    return ws


async def _wait_for(predicate, timeout: float = 2.0, interval: float = 0.05) -> None:
    """Poll a predicate until it returns truthy or timeout elapses."""
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return
        await asyncio.sleep(interval)
        elapsed += interval
    raise AssertionError(f"Predicate not satisfied within {timeout}s")
