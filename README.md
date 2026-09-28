# hyperliquid-execution-toolkit

[![CI](https://github.com/darkosedam-svg/hyperliquid-execution-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/darkosedam-svg/hyperliquid-execution-toolkit/actions/workflows/ci.yml)

A work-in-progress execution layer for Hyperliquid perps: tick/lot-size-correct
order math, a self-healing websocket that resubscribes on reconnect and calls
a caller-supplied hook so you can reconcile your own state, and a blended
fee-rate helper. The order-placement and account methods on `ExecutionClient`
are still stubs — see "What works today" below before you build on this.

## Why this exists

Most "Hyperliquid Python" code on GitHub is a 30-line wrapper around the
official SDK that breaks on the first reconnect or rejects orders due to tick
rounding. This toolkit is being built to fix that boring stuff so you can
focus on strategy — the precision and websocket layers are done; the
order-submission layer (including post-only/maker handling) is not yet.

It is **not**:
- A trading bot
- A strategy framework
- An indicator library
- A finished execution client (yet)

## What works today

| | |
|---|---|
| ✅ Tick-size & lot-size aware rounding (`hl_exec.precision`) | `round_size`, `round_price`, `usd_to_size`, `validate_size` — sizes always round down, buy prices round down, sell prices round up. Unit-tested. |
| ✅ Self-healing websocket (`hl_exec.websocket.HyperliquidWebSocket`) | Detects stale connections via heartbeat timeout, reconnects with exponential backoff + jitter, and replays subscriptions on reconnect. Unit-tested. |
| ✅ Blended fee helper (`hl_exec.precision.effective_fee_rate`) | Computes an effective fee rate from an empirical maker-fill ratio instead of assuming 100% maker fills. |
| ✅ `ExecutionClient.get_position()` | Reads from an in-memory cache that the websocket layer is meant to keep updated. Raises if the client hasn't connected. Note: nothing populates this cache yet, since the websocket event handlers and `connect()` are not wired up (see Roadmap) — so in the current release this always returns `None` for any symbol. |

## Roadmap / not yet implemented

Everything else on `ExecutionClient` is a stub that raises `NotImplementedError`:

- `connect()` / `close()` — no REST metadata fetch or websocket wiring yet
- `market_buy()` / `market_sell()` / `limit_buy()` / `limit_sell()` — no order submission
- `cancel_all()`, `get_open_orders()`, `get_account_value()`
- Signing and posting to `/exchange` (`_submit`)
- Builder code support, vault deposit/withdraw helpers, spot trading endpoints (perps-only is the target), optional Prometheus metrics emitter

In short: the pieces you'd actually trust with money — order placement,
account state, connection bootstrap — aren't there yet. What's shipped is the
math and the reconnect logic underneath them.

## Install

Not on PyPI yet. Install from GitHub:

```bash
pip install git+https://github.com/darkosedam-svg/hyperliquid-execution-toolkit.git
```

Or from source:

```bash
git clone https://github.com/darkosedam-svg/hyperliquid-execution-toolkit
cd hyperliquid-execution-toolkit
pip install -e .
```

Requires Python 3.10+.

## Quick start (what actually runs today)

```python
from decimal import Decimal
from hl_exec.precision import round_size, round_price, usd_to_size, effective_fee_rate
from hl_exec.types import AssetSpec, Side

spec = AssetSpec("ETH", sz_decimals=4, px_decimals=2,
                  min_size=Decimal("0.0001"), max_leverage=50)

size = usd_to_size(Decimal("100"), Decimal("3247.50"), spec)
price = round_price(Decimal("3247.997"), Side.BUY, spec)
fee_bps = effective_fee_rate(Decimal("0.4"), Decimal("1.5"), Decimal("4.5"))
```

```python
from hl_exec.websocket import HyperliquidWebSocket

async def on_event(msg):
    print(msg)

ws = HyperliquidWebSocket(testnet=True, on_event=on_event)
await ws.start()
await ws.subscribe("userFills", {"user": "0x..."})
```

The higher-level `ExecutionClient` example that used to be here (`market_buy`,
`limit_buy`, etc.) does not work yet — those methods raise
`NotImplementedError`. Use the modules above directly until the client is
wired up.

## Usage notes (read these)

### 1. Always test on testnet first
Once order submission lands, the toolkit will default to `testnet=True`.
Today there's no live trading path at all, so this is forward-looking advice
for when `connect()`/`_submit()` are implemented.

### 2. Funding is hourly
The intent is for the position object to track funding accrual in real time
once the websocket event handlers are wired into `_positions`. Not yet true.

### 3. The websocket WILL disconnect
This part is real today: expect reconnects under normal operation. The
`HyperliquidWebSocket` class handles them (heartbeat timeout detection,
exponential backoff with jitter, subscription replay on reconnect) — see
`hl_exec/websocket.py` and `tests/test_websocket.py`.

### 4. Position size rounding is downward
Always, in `hl_exec.precision`. If you ask for 0.00187 BTC and
`szDecimals=4`, `round_size` gives you 0.0018. This is intentional — it's the
safe side. Your backtest should round the same way.

## What's NOT included (deliberately)

- **No strategy logic.** Bring your own.
- **No PnL accounting layer.** Once implemented, use the position object's
  `realized_pnl` and `funding_paid`, but if you want a full ledger across
  multiple bots, build one.
- **No backtest harness.** Use vectorbt, backtrader, or roll your own.
- **No GUI/dashboard.**

## Project status

Early / alpha. The precision math and websocket reconnect logic are done and
tested. The order-submission and account-state layer is not implemented —
see Roadmap above. Expect breaking API changes until a 1.0 release.

## Contributing

PRs welcome. Please open an issue first for non-trivial changes. Tests are
required for all new features.

```bash
# Run the test suite
pytest tests/
```

## Who built this

Built by Darko Vlahovic. I build algo-trading infrastructure for Hyperliquid
perps. Available for paid work — bug fixes, custom strategies, full systems.

- ✉️ jessuskrist84@gmail.com
- 🌐 [github.com/darkosedam-svg](https://github.com/darkosedam-svg)

## Hire me

I build and harden trading infrastructure: execution engines, exchange
connectors, backtesting pipelines, and the unglamorous reconciliation/reconnect
logic that keeps live systems from silently losing money. Available for
custom work and ongoing retainers around trading-infrastructure, execution,
and backtesting engineering.

Contact: jessuskrist84@gmail.com

## License

MIT. Use it for anything, just don't blame me when your strategy doesn't work
— especially since half the client is still stubs.

---

⚠️ **Risk note:** Algorithmic trading can lose money. This toolkit is
pre-alpha for anything involving order execution; only the rounding math and
websocket layer have been tested. Do not point this at mainnet funds via
`ExecutionClient` yet — the trading methods are not implemented.
