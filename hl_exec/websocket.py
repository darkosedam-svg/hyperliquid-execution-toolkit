"""Self-healing websocket connection for Hyperliquid.

Design principles:

  * The exchange is allowed to disconnect us at any time.
  * We are never allowed to drop a fill.
  * On reconnect, we call a caller-supplied hook so the caller can reconcile
    its own state (e.g. refetch from REST); this module does not refetch or
    reconcile anything itself.
  * Subscription state is preserved across reconnects.
  * Stale connections are detected via heartbeat timeout, not just socket
    close (sockets often appear "open" long after the peer is gone).

This module owns the WS lifecycle. The main client uses it through a small
interface: subscribe(channel), and an event callback. Reconnection is
transparent to callers above the connection layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
ReconcileCallback = Callable[[], Awaitable[None]]


WS_URL_MAINNET = "wss://api.hyperliquid.xyz/ws"
WS_URL_TESTNET = "wss://api.hyperliquid-testnet.xyz/ws"


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class Subscription:
    """A WS subscription that should be re-established on reconnect."""
    channel: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> dict[str, Any]:
        return {
            "method": "subscribe",
            "subscription": {"type": self.channel, **self.params},
        }

    def key(self) -> str:
        """Stable key for deduplication in the subscription set."""
        return f"{self.channel}:{json.dumps(self.params, sort_keys=True)}"


class HyperliquidWebSocket:
    """Self-healing websocket client for Hyperliquid.

    Usage:
        ws = HyperliquidWebSocket(
            testnet=True,
            on_event=my_handler,
            on_reconnect=my_state_reconciler,
        )
        await ws.start()
        await ws.subscribe("userFills", {"user": "0x..."})
        ...
        await ws.stop()

    The handler is called once per event. The reconciler is called once per
    successful reconnect, after subscriptions are re-established but before
    new events flow — use it to refetch state from REST and reconcile any
    drift in your local cache.
    """

    def __init__(
        self,
        testnet: bool = True,
        on_event: Optional[EventHandler] = None,
        on_reconnect: Optional[ReconcileCallback] = None,
        heartbeat_interval: float = 30.0,
        heartbeat_timeout: float = 60.0,
        max_backoff: float = 60.0,
    ):
        self._url = WS_URL_TESTNET if testnet else WS_URL_MAINNET
        self._on_event = on_event
        self._on_reconnect = on_reconnect
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._max_backoff = max_backoff

        self._ws: Optional[Any] = None
        self._state = ConnectionState.DISCONNECTED
        self._subscriptions: dict[str, Subscription] = {}
        self._last_message_at: Optional[datetime] = None

        self._main_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    @staticmethod
    def _ws_is_closed(ws: Any) -> bool:
        """Compatibility shim across websockets library versions.

        websockets 13.x exposes a `closed` boolean property; 14.x+ removed it
        in favor of checking close_code or using `state`. This helper works
        across both.
        """
        if ws is None:
            return True
        # Modern (14.x+): state attribute
        state = getattr(ws, "state", None)
        if state is not None:
            # State.OPEN == 1; anything else (CLOSING, CLOSED) is "closed enough"
            return getattr(state, "name", "") not in ("OPEN", "CONNECTING")
        # Legacy fallback
        return bool(getattr(ws, "closed", False))

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    async def start(self) -> None:
        """Open the connection and begin processing events.

        This method returns once the initial connection is established.
        The connection lifecycle continues in a background task.
        """
        if self._main_task is not None:
            raise RuntimeError("WebSocket already started")

        self._stop_event.clear()
        self._main_task = asyncio.create_task(self._run())

        # Wait for first successful connection (with timeout)
        try:
            await asyncio.wait_for(self._wait_until_connected(), timeout=10.0)
        except asyncio.TimeoutError:
            await self.stop()
            raise ConnectionError("Failed to establish initial WS connection")

    async def stop(self) -> None:
        """Cleanly close the connection and stop background tasks."""
        if self._main_task is None:
            return

        self._state = ConnectionState.CLOSING
        self._stop_event.set()

        if self._ws is not None and not self._ws_is_closed(self._ws):
            await self._ws.close()

        # Cancel and await background tasks
        for task in [self._main_task, self._heartbeat_task]:
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._main_task = None
        self._heartbeat_task = None
        self._state = ConnectionState.CLOSED

    async def subscribe(self, channel: str, params: Optional[dict[str, Any]] = None) -> None:
        """Subscribe to a WS channel. Subscription persists across reconnects.

        Args:
            channel: Channel type (e.g. "userFills", "l2Book", "trades").
            params: Channel-specific parameters (e.g. {"user": "0x..."} or
                {"coin": "BTC"}).
        """
        sub = Subscription(channel=channel, params=params or {})
        self._subscriptions[sub.key()] = sub

        if self.is_connected:
            await self._send(sub.to_message())

    async def unsubscribe(self, channel: str, params: Optional[dict[str, Any]] = None) -> None:
        """Unsubscribe from a channel."""
        sub = Subscription(channel=channel, params=params or {})
        key = sub.key()
        self._subscriptions.pop(key, None)

        if self.is_connected:
            await self._send({
                "method": "unsubscribe",
                "subscription": {"type": channel, **(params or {})},
            })

    # --------------------------------------------------------------------------
    # Connection lifecycle
    # --------------------------------------------------------------------------

    async def _run(self) -> None:
        """Main connection loop. Reconnects with exponential backoff on failures."""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_process()
                # Connection ended cleanly. If not stopping, reconnect.
                if self._stop_event.is_set():
                    break
                logger.warning("WS connection ended; reconnecting in %.1fs", backoff)
            except (ConnectionClosed, ConnectionError, OSError) as e:
                logger.warning(
                    "WS error: %s. Reconnecting in %.1fs", type(e).__name__, backoff
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected WS error")

            self._state = ConnectionState.RECONNECTING

            # Backoff with jitter to avoid thundering herd
            jittered = backoff * (0.5 + random.random())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=jittered)
                break  # stop_event was set during sleep
            except asyncio.TimeoutError:
                pass

            backoff = min(backoff * 2, self._max_backoff)

    async def _connect_and_process(self) -> None:
        """Single connection attempt: connect, resubscribe, process events.

        Returns normally on graceful close. Raises on any error so the outer
        loop can reconnect.
        """
        self._state = ConnectionState.CONNECTING
        logger.info("Connecting to %s", self._url)

        async with websockets.connect(
            self._url,
            ping_interval=None,  # we manage heartbeat manually
            close_timeout=5.0,
            max_size=2**22,  # 4MB — order books can be large
        ) as ws:
            self._ws = ws
            self._state = ConnectionState.CONNECTED
            self._last_message_at = datetime.now(timezone.utc)
            logger.info("WS connected")

            # Re-establish all subscriptions
            for sub in self._subscriptions.values():
                await self._send(sub.to_message())

            # Trigger reconciliation callback (state may have drifted while disconnected)
            if self._on_reconnect is not None:
                try:
                    await self._on_reconnect()
                except Exception:
                    logger.exception("Reconcile callback failed")

            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            try:
                await self._receive_loop()
            finally:
                if self._heartbeat_task is not None:
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    self._heartbeat_task = None
                self._ws = None

    async def _receive_loop(self) -> None:
        """Read and dispatch messages until the connection ends."""
        assert self._ws is not None

        async for raw in self._ws:
            self._last_message_at = datetime.now(timezone.utc)

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message: %r", raw[:200])
                continue

            # Hyperliquid wraps events: {"channel": "...", "data": {...}}
            channel = msg.get("channel")
            if channel == "pong":
                continue  # heartbeat ack
            if channel == "subscriptionResponse":
                logger.debug("Subscription confirmed: %s", msg.get("data"))
                continue

            if self._on_event is not None:
                try:
                    await self._on_event(msg)
                except Exception:
                    logger.exception("Event handler raised on %s", channel)

    async def _heartbeat_loop(self) -> None:
        """Send pings and detect stale connections."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)

                # Stale detection: if no message in heartbeat_timeout, force reconnect
                if self._last_message_at is not None:
                    age = (datetime.now(timezone.utc) - self._last_message_at).total_seconds()
                    if age > self._heartbeat_timeout:
                        logger.warning(
                            "WS stale: last message %.1fs ago, forcing reconnect", age
                        )
                        if self._ws is not None and not self._ws_is_closed(self._ws):
                            await self._ws.close(code=4000, reason="heartbeat_timeout")
                        return

                await self._send({"method": "ping"})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat loop error")

    async def _send(self, message: dict[str, Any]) -> None:
        """Send a JSON message. No-op if the connection is closed."""
        if self._ws is None or self._ws_is_closed(self._ws):
            logger.debug("Drop send (not connected): %s", message.get("method"))
            return
        await self._ws.send(json.dumps(message))

    async def _wait_until_connected(self) -> None:
        """Block until state == CONNECTED. Used by start() to confirm readiness."""
        while self._state != ConnectionState.CONNECTED:
            if self._state == ConnectionState.CLOSED:
                raise ConnectionError("WS closed during connect")
            await asyncio.sleep(0.05)
