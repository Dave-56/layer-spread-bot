# Spread: an example bot on uselayer

With uselayer, your trading bot keeps its own strategy and gains two abilities: it buys every trade on whichever venue is cheapest after fees, and it catches cross-venue price gaps that are real money after fees, rules and depth, while skipping the fake ones.

Spread runs on your machine, with your own keys, across **Kalshi** and **Polymarket US**. It has two screens:

- **Best venue.** Your strategy decides the trade ("buy 100 YES on this outcome"). Spread prices that exact order on both venues from their live order books: each venue's average price, fees, how much it can fill, and the total cost. Then it sends the order to the cheaper one.
- **Arbitrage.** Spread scans markets that are the same bet on both venues. Buying YES on one and NO on the other pays $1 a contract either way, so a price gap looks like free money. Most gaps aren't. Every match goes through the same checks, and Spread shows why each gap was dropped: the rules differ, a venue has no offers, there's no gap, fees are bigger than it, the books are too thin, or the return per day is too low. For a gap that survives, you see gross spread → fees → net → return per day, and you can paper-trade both legs.

An optional chat panel answers the same questions in plain English, with your own LLM key.

It's paper mode by default: real order books, fake money.

## What runs where

| Piece | Where it runs |
|---|---|
| Which markets are the same bet, and where their rules differ | Layer's hosted matching (`GET /v0/matches`), called by the SDK with your `LAYER_API_KEY` |
| Venue prices and order books, fees, quotes, orders, positions, paper fills | The [uselayer](https://github.com/Dave-56/uselayer-sdk) Python SDK, on your machine, talking to each venue with your own keys |
| The engine (`engine/`): a small local service that runs the SDK for the app | Your machine, `127.0.0.1:8765`. It answers only this machine. |
| The app (`app/`, `components/`): the two screens and the chat | Your machine, `127.0.0.1:3200` |
| The chat's answers | The LLM you choose (Anthropic or OpenRouter), with your key |

Nothing is hosted and nothing is deployed. Layer gets your Layer API key, the market ids it gave you, and search words. It never sees prices, orders, positions or venue keys. The SDK checks every Layer request against that list before it leaves your machine.

## Set up in 5 minutes

You need [Node 20+](https://nodejs.org) and [uv](https://docs.astral.sh/uv/) (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). uv fetches Python 3.11+ if you don't have it.

```bash
git clone https://github.com/Dave-56/layer-spread-bot
cd layer-spread-bot
npm run setup              # npm install + the engine's Python packages
cp .env.example .env       # then fill in your keys (below)
npm run dev                # starts the engine and the app together
```

Open http://127.0.0.1:3200.

Keys in `.env`:

| Key | What for | Where to get it |
|---|---|---|
| `LAYER_API_KEY` | Which markets are the same bet | [uselayer.sh](https://uselayer.sh) |
| `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` | Reading Kalshi's order books (a read-only key is enough for paper mode) | Kalshi account settings → API keys |
| `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY` | Live orders only. Paper mode reads Polymarket US's public books without a key. | polymarket.us/developer |
| `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` | The optional chat panel | console.anthropic.com, or openrouter.ai |

## Your keys stay on your machine

- `.env` is git-ignored. Each key is read by the SDK and sent only to its own service: the Kalshi key to Kalshi, the Polymarket US key to Polymarket US, the Layer key to Layer, the LLM key to your LLM provider.
- No key is logged, shown in the app, or returned by the engine. `/status` reports only which keys are set (yes/no).
- The engine listens on `127.0.0.1` and refuses requests from any other machine.

## Paper and live

- **Paper (the default).** Orders fill against the venues' real order books with fake money, in the SDK's local store (`~/.uselayer/paper.db`). Nothing reaches a venue.
- **Live.** Set `BOT_MODE=live` in `.env` and add the key for each venue you'll trade, then restart. Orders are then real, with your money. The header shows a red LIVE badge. Only the exact word `live` turns it on. If your account already has orders or positions, the SDK starts a new live store with its kill switch on: check them, then run `uv run python -m uselayer resume --mode live` in `engine/`.
- Live or paper, every order goes through the SDK's guardrails: a budget across everything (`BOT_BUDGET`, default $100), a price collar, and a kill switch. To stop everything from any terminal: `cd engine && uv run python -m uselayer kill`.
- A comparison is a snapshot of both books when you ran it. A book can move before an order arrives. The limit price caps what an order can pay, and orders are immediate-or-cancel. The arbitrage trade reads both books again first and sends nothing if the gap is gone.

## Your strategy here

`engine/spread_engine/strategy.py` is where your strategy goes. It gets the matched markets and returns a `Signal`: which market, YES or NO, how many contracts, and an optional maximum price. The example reads prices with the SDK, picks the first upcoming match whose rules don't differ and where both venues have YES on offer, and asks for 100 YES. It's a placeholder, not advice. The Best venue screen runs it, then compares and sends that order.

## How the arbitrage scan works

`engine/spread_engine/funnel.py`. Each matched market stops at the first check it fails:

1. **Rules differ.** Layer flagged a rule difference: a different data source, deadline, rounding, exception or definition. These are dropped before any book is read. The two markets could settle differently, so "both sides pay $1" may not hold.
2. **Couldn't price.** A book couldn't be read (no key, a stale book, the venue didn't answer).
3. **No offers.** One venue has nobody selling one side.
4. **No gap.** YES on one venue plus NO on the other costs $1.00 or more before fees.
5. **Fees ate the gap.** There's a gap, but the two venues' fees are bigger.
6. **Below your minimum.** Something is left after fees, but less than your minimum per contract.
7. **Too thin.** The books can't fill even one contract that clears your minimum.
8. **Return per day too low.** Below your minimum. A 2% gap paid in a month is worse than 1% paid tomorrow.

Every number comes from the SDK's `client.quote()`: the gross spread, both venues' fees, the net, and the return per day until the later of the two markets pays out. Expect most scans to end with no survivor. When nothing is still money after fees, the right move is no trade.

## Replay a gap you recorded

Record both venues' books for a matched pair with the SDK, then replay them through the same quote in backtest mode:

```bash
cd engine
uv run python -m uselayer record <kalshi-ticker> <polymarket-us-slug> --out pair.jsonl --minutes 60
```

Recording needs your Kalshi key and your Polymarket US key (its live stream is read with your key). The Replay switch on the Arbitrage screen is coming next.

## Tests

```bash
npm test          # app tests (vitest) + engine tests (pytest); no network
npm run smoke     # every engine route against the real venues, in paper mode; needs your keys in .env
```

## Notes

- The engine pins the uselayer SDK to a commit (see `engine/pyproject.toml`) until the release with best-venue orders and return per day is on PyPI.
- Spread never calls anything "risk-free": a gap can close before both orders fill, and venues can settle the same event differently.
- MIT licensed.
