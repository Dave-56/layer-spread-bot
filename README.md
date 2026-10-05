# Spread: an example bot on uselayer

With uselayer, your trading bot keeps its own strategy and gains two abilities: it buys every trade on whichever venue is cheapest after fees, and it catches cross-venue price gaps that are real money after fees, rules and depth, while skipping the fake ones.

Spread runs on your machine, with your own keys, across **Kalshi** and **Polymarket US**. It has two screens:

- **Best venue.** Your strategy (or you, by hand) decides the trade ("buy 100 YES on this outcome"). Spread prices that exact order on both venues from their live order books: each venue's average price, fees, how much it can fill, and the total cost. Then it sends the order to the cheaper one.
- **Arbitrage.** Spread scans markets that are the same bet on both venues. Buying YES on one and NO on the other pays $1 a contract either way, so a price gap looks like free money. Most gaps aren't. Every match goes through the same checks, and Spread shows why each gap was dropped: a venue has no offers, there's no gap, fees are bigger than it, the books are too thin, or the return per day is too low. For a gap that survives, you see gross spread → fees → net → return per day, and you can paper-trade both legs. When the two venues word a bet differently, Spread still checks it and shows a warning with it.

An optional chat panel answers the same questions in plain English, with your own LLM key.

It's paper mode by default: real order books, fake money.

## What runs where

| Piece | Where it runs |
|---|---|
| Which markets are the same bet, and where their rules differ | Layer's hosted matching (`GET /v0/matches`), called by the SDK with your `LAYER_API_KEY` |
| Venue prices and order books, fees, quotes, orders, positions, paper fills | The [uselayer](https://pypi.org/project/uselayer/) Python SDK, on your machine, talking to each venue with your own keys |
| The engine (`engine/`): a small local service that runs the SDK for the app | Your machine, `127.0.0.1:8765`. It answers only this machine. |
| The app (`app/`, `components/`): the two screens and the chat | Your machine, `127.0.0.1:3200` |
| The chat's answers | The LLM you choose (Anthropic or OpenRouter), with your key |

Nothing is hosted and nothing is deployed. Layer gets your Layer API key, the market ids it gave you, and search words. It never sees prices, orders, positions or venue keys. The SDK checks every Layer request against that list before it leaves your machine.

## Set up in 5 minutes

You need [Node 20+](https://nodejs.org) and [uv](https://docs.astral.sh/uv/) (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). uv fetches Python 3.11+ if you don't have it.

```bash
git clone https://github.com/Dave-56/layer-spread-bot
cd layer-spread-bot
npm run setup              # installs the app (npm ci) and the engine's Python packages (uv sync)
cp .env.example .env       # then fill in your keys (below)
npm run dev                # starts the engine and the app together
```

Open http://127.0.0.1:3200. Ports in use? `ENGINE_PORT=8775 WEB_PORT=3210 npm run dev`.

Keys in `.env`:

| Key | What for | Where to get it |
|---|---|---|
| `LAYER_API_KEY` | Which markets are the same bet | [uselayer.sh](https://uselayer.sh) |
| `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH` | Reading Kalshi's order books (a read-only key is enough for paper mode) | Kalshi account settings → API keys |
| `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY` | Live orders only. Paper mode reads Polymarket US's public books without a key. | polymarket.us/developer |
| `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` | The optional chat panel | console.anthropic.com, or openrouter.ai |

## Strategies

Your strategy decides the trade; the bot finds the cheaper venue for it. Each strategy is one file in `engine/spread_engine/strategies/`, and the Best venue screen lists every file there, grouped by category.

It comes with examples named the way people trade. They're examples, not advice: none of them is a reason to expect a profit.

| Category | Example | What it buys |
|---|---|---|
| Sports | Back the favorite | Next game first: 100 YES on the side priced 55¢–85¢, at most 85¢ |
| Sports | Longshot under 20¢ | Next game first: 100 YES on an underdog under 20¢, at most 20¢ |
| Sports | Game day: favorite in the last 6 hours | Games starting within 6 hours: 100 YES on the side priced 55¢–90¢, at most 90¢ |
| Crypto | Crypto: nearly decided, last 3 days | Price-line markets closing within 3 days: 100 of the side priced 90¢–97¢, at most 97¢ |
| News, politics & economics | Nearly decided, last 7 days | Markets closing within 7 days: 100 of the side priced 90¢–97¢, at most 97¢ |

Each one looks only at markets that are open on both venues, worded the same on both, with a real price on each (a 1¢ or 99¢ YES is skipped). When nothing fits, it says why in one sentence, e.g. "No trade: Layer has no crypto markets matched on both Kalshi and Polymarket US right now."

"Pick a game yourself" on the same screen skips the strategy: search for any game or market, pick the outcome, YES or NO and contracts (a max price is under Settings).

### Add your own

1. Start from the starter file: `cp engine/spread_engine/strategies/my_strategy.py engine/spread_engine/strategies/momentum.py`, or press "Download the starter file" on the "Add your own" card of the Best venue screen and save it under a new name.
2. Give it a `NAME`, a `CATEGORY` and a one-line `DESCRIPTION`, and write `decide()`: which market, YES or NO, how many contracts, the most you'll pay.
3. Press "Upload a .py file" on the same card: it saves your file in that folder and selects it. (A file you copied into the folder shows up when you reload the page.) Edits to a strategy apply on the next run, without a restart.

The starter file itself isn't in the list, since it never trades.

```python
from . import SPORTS, NoTrade, Signal, priced

NAME = "Momentum: buy YES under 40¢"
CATEGORY = SPORTS
DESCRIPTION = "Buys 50 YES when it's under 40¢ on both venues."

def decide(matches, client):
    for m, p in priced(matches, client):          # upcoming, open and worded the same on both venues, with both prices
        if p.a.yes_ask < 0.40 and p.b.yes_ask < 0.40:
            return Signal(m, "yes", 50, max_price=0.40, why="YES is under 40¢ on both venues.")
    return NoTrade("Nothing is under 40¢ on both venues right now.")
```

`client` is the uselayer SDK with your keys, so a strategy can read anything: `client.prices(m)`, `client.book(m.kalshi)`. `LAYER_CATEGORIES = ("crypto",)` in the file asks Layer for those categories only. The helpers (`priced`, `cheapest`, `soonest`, `game_winner`, `starts_at`, `closes_at`) are in `strategies/__init__.py`.

A strategy file is your own Python, run by the engine on your machine with your keys, like any script you run yourself. Adding one from the app saves it into `strategies/` and imports it once to check that it loads and has `decide()`; if not, the file is removed and you see why. The engine answers only this machine (`127.0.0.1`), so nobody else can add a file. Only add code you wrote or have read.

## Your keys stay on your machine

- `.env` is git-ignored. Each key is read by the SDK and sent only to its own service: the Kalshi key to Kalshi, the Polymarket US key to Polymarket US, the Layer key to Layer, the LLM key to your LLM provider.
- No key is logged, shown in the app, or returned by the engine. `/status` reports only which keys are set (yes/no).
- The engine listens on `127.0.0.1` and refuses requests from any other machine.

## Paper and live

- **Paper (the default).** Orders fill against the venues' real order books with fake money, in the bot's own store (`~/.uselayer/spread-bot/paper.db`, or `BOT_STORE_DIR`). Nothing reaches a venue. The "Paper account" line shows what's open and how much of your limit it uses; "Reset" starts the fake account over.
- **Live.** Set `BOT_MODE=live` in `.env` and add the key for each venue you'll trade, then restart. Orders are then real, with your money. The header shows a red LIVE badge. Only the exact word `live` turns it on. If your account already has orders or positions, the SDK starts a new live store with its kill switch on: check them, then run `uv run python -m uselayer resume --mode live` in `engine/`.
- Live or paper, every order goes through the SDK's guardrails: a budget across everything (`BOT_BUDGET`, default $100), a price collar, and a kill switch. To stop everything from any terminal: `cd engine && uv run python -m uselayer kill --mode paper --store ~/.uselayer/spread-bot/paper.db` (or `live.db` with `--mode live`).
- A comparison is a snapshot of both books when you ran it. A book can move before an order arrives. The order's limit price (shown as "pays at most") caps what it can pay, and it's immediate-or-cancel: it fills what's there at that price, and the rest is cancelled. The arbitrage trade reads both books again first and sends nothing if the gap is gone.

## How the arbitrage scan works

`engine/spread_engine/funnel.py`. Each matched market stops at the first check it fails:

1. **Couldn't price.** A book couldn't be read (no key, a stale book, the venue didn't answer).
2. **No offers.** One venue has nobody selling one side.
3. **No gap.** YES on one venue plus NO on the other costs $1.00 or more before fees.
4. **Fees ate the gap.** There's a gap, but the two venues' fees are bigger.
5. **Below your minimum.** Something is left after fees, but less than your minimum per contract.
6. **Too thin.** The books can't fill even one contract that clears your minimum.
7. **Return per day too low.** Below your minimum. A 2% gap paid in a month is worse than 1% paid tomorrow.

**Worded differently.** Layer flags a match whose two markets differ on an edge case: a different data source, deadline, rounding, exception or definition. Spread doesn't drop it. It goes through the same checks as any other match, and wherever it shows up (the scan table, a survivor, a replay, the paper-trade result) it carries a warning, e.g. "Worded differently: different data source. The two could settle differently." Then "both sides pay $1" may not hold, so a survivor worded differently is listed below the ones worded the same.

Every number comes from the SDK's `client.quote()`: the gross spread, both venues' fees, the net, and the return per day until the later of the two markets pays out. Expect most scans to end with no survivor. When nothing is still money after fees, the right move is no trade.

## Replay prices you saved

The Replay switch on the Arbitrage screen runs saved order books through the same checks as the live scan, in the SDK's backtest mode, moment by moment.

Save a matched pair's books while it trades (both venues, every change):

```bash
npm run record -- KXNBAGAME-26OCT05MEMATL-ATL --minutes 60
```

Use any Kalshi ticker from a scan; Layer finds its Polymarket US twin. Files go to `recordings/` (not committed), with the match saved next to them. Recording needs your Kalshi key and your Polymarket US key (its live stream is read with your key; nothing is traded).

Any other file the SDK's `import_events` reads works too: type its folder into "Folder" and pick it. A file without a saved match is paired through Layer's matching. An optional `<name>.meta.json` beside it can give `settles_at` and `"sizes_unknown": true`, for a file whose order sizes are placeholders. Such a file is priced at the Contracts number you pick (100 by default) at the top price on both venues, and every result says so: "Size unknown: assumes 100 contracts at the top price on both venues." That's an assumption, not depth the file shows. It isn't priced at 1 contract because Kalshi rounds each order's fee up to the cent: on one contract a 0.3¢ fee bills 1¢ and hides a real 1–2¢ gap. "Per contract after fees" is the SDK's figure before that rounding.

Replays use the SDK's dated fee schedules. A file from before a venue's first schedule in the SDK (Polymarket US: Sep 25, 2026) can't be priced, and the replay says so in one sentence.

The result: "Replay of <date>", how many moments were checked and why each was dropped, and the best moment's gross spread → fees → net → return per day, with how long the gap lasted.

## Tests

```bash
npm test          # app tests (vitest) + engine tests (pytest); no network
npm run smoke     # every engine route against the real venues, in paper mode; needs your keys in .env
```

## Notes

- The engine needs uselayer 0.4.0 or later (`engine/pyproject.toml`), from PyPI.
- Spread never calls anything "risk-free": a gap can close before both orders fill, and venues can settle the same event differently.
- MIT licensed.
