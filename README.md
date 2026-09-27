# hyperliquid-execution-toolkit

[![CI](https://github.com/darkosedam-svg/hyperliquid-execution-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/darkosedam-svg/hyperliquid-execution-toolkit/actions/workflows/ci.yml)

Production-grade execution primitives for Hyperliquid perps. Order placement that respects tick/lot sizes, websocket reconnect logic that doesn't drop fills, and fee-aware sizing that won't blow your maker rebate assumptions.

Built and battle-tested across multiple live trading systems. Released under MIT — use it, fork it, ship with it.

## Why this exists

Most "Hyperliquid Python" code on GitHub is a 30-line wrapper around the official SDK that breaks on the first reconnect, rejects orders due to tick rounding, or silently turns your maker limits into takers. This toolkit fixes the boring stuff so you can focus on strategy.

It is **not**:
- A trading bot
- A strategy framework
- An indicator library

It **is**:
- A correct, tested execution layer you can drop under any strategy.

## Features

| | |
|---|---|
| ✅ Tick-size & lot-size aware order placement | Rounds correctly on every asset, never gets rejected for precision errors |
| ✅ Self-healing websocket | Detects stale connections via heartbeat timeout, reconnects with exponential backoff, replays missed events |
| ✅ Fee-aware position sizing | Computes effective fees from your actual maker/taker fill ratio, not the optimistic version |
| ✅ Mark-price-aware risk checks | Stops, liquidation distance, and funding accrual all use the correct price series |
| ✅ Order state reconciliation | Survives restarts — rebuilds open-order and position state from the exchange on startup |
| ✅ Idempotent order submission | Client-order-IDs prevent double-fills on retry |
| ✅ Async-first | Built on asyncio, plays well with FastAPI, Discord/Telegram bots, etc. |

## Install

```bash
pip install hyperliquid-execution-toolkit
```

Or from source:

```bash
git clone https://github.com/GitBot/hyperliquid-execution-toolkit
cd hyperliquid-execution-toolkit
pip install -e .
```

Requires Python 3.10+.

## Quick start

```python
from hl_exec import ExecutionClient
import asyncio

async def main():
    client = ExecutionClient(
        wallet_address="0xYOUR_ADDRESS",
        private_key="0xYOUR_PRIVATE_KEY",
        testnet=True,  # always start here
    )

    await client.connect()

    # Place a market buy that respects tick & lot sizes
    fill = await client.market_buy(
        symbol="ETH",
        size_usd=100,
    )
    print(f"Filled {fill.size} ETH at avg price ${fill.avg_price}")

    # Place a post-only limit (will not cross the spread)
    order = await client.limit_buy(
        symbol="ETH",
        size_usd=100,
        price_offset_bps=-5,  # 5 bps below best bid
        post_only=True,
    )

    # Get current position with funding accrued
    pos = await client.get_position("ETH")
    print(f"Position: {pos.size} | Unrealized: ${pos.unrealized_pnl} | Funding paid: ${pos.funding_paid}")

asyncio.run(main())
```

## Usage notes (read these)

### 1. Always test on testnet first
The toolkit defaults to `testnet=True` for a reason. Hyperliquid's testnet is fully featured — orders, fills, funding, the full thing. Burn through your strategy bugs there.

### 2. Respect rate limits
Hyperliquid has per-IP and per-wallet rate limits. The toolkit batches and throttles automatically, but if you're running multiple instances from the same IP, you'll hit the wall. Use proxies or run from separate VPS instances.

### 3. Funding is hourly
The position object tracks funding accrual in real-time. If you're surprised by funding costs, you weren't reading them. Set alerts on `pos.funding_paid` if it matters.

### 4. The websocket WILL disconnect
Even with the self-healing logic, expect 2-5 reconnects per day. The toolkit handles them, but your strategy logic should be idempotent against missed-and-replayed events.

### 5. Position size rounding is downward
Always. If you ask for 0.00187 BTC and `szDecimals=4`, you get 0.0018. This is intentional — it's the safe side. Your backtest should round the same way.

## What's NOT included (deliberately)

- **No strategy logic.** Bring your own.
- **No PnL accounting layer.** Use the position object's `realized_pnl` and `funding_paid`, but if you want a full ledger across multiple bots, build one.
- **No backtest harness.** Use vectorbt, backtrader, or roll your own. The toolkit's order semantics are documented so you can match them in your backtest.
- **No GUI/dashboard.** Pipe positions to your own.

## Project status

Active development. Versioned semantically. Breaking changes only on major version bumps with migration notes.

Roadmap:
- [ ] Builder code support
- [ ] Vault deposit/withdraw helpers
- [ ] Spot trading endpoints (currently perps-only)
- [ ] Optional Prometheus metrics emitter

## Contributing

PRs welcome. Please open an issue first for non-trivial changes. Tests are required for all new features — we don't ship execution code without tests.

```bash
# Run the test suite
pytest tests/
```

Integration tests hit testnet; you'll need a testnet wallet with some test USDC.

## Who built this

Built by Darko Kovačić. I build production algo-trading systems for Hyperliquid, Solana, and CEX perps. Available for paid work — bug fixes, custom strategies, full systems.

- 🌐 jessuskrist84@gmail.com
- 🐦 [@GitBot]
- ✉️ jessuskrist84@gmail.com

## Hire me

I build and harden trading infrastructure: execution engines, exchange connectors, backtesting pipelines, and the unglamorous reconciliation/reconnect logic that keeps live systems from silently losing money. Available for custom work and ongoing retainers around trading-infrastructure, execution, and backtesting engineering.

Contact: darko.sedam@gmail.com

## License

MIT. Use it for anything, just don't blame me when your strategy doesn't work.

---

⚠️ **Risk note:** Algorithmic trading can lose money. This toolkit handles execution correctness, not strategy correctness. Test on testnet, size small on mainnet, scale only after live PnL matches expectations.
