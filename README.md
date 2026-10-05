# Spread: an example bot on uselayer

With uselayer, your trading bot keeps its own strategy and gains two abilities: it buys every trade on whichever venue is cheapest after fees, and it catches cross-venue price gaps that are real money after fees, rules and depth, while skipping the fake ones.

Spread runs on your machine, with your own keys, across **Kalshi** and **Polymarket US**. It has two screens:

- **Best venue.** You (by hand), your strategy, or "Every market" for a whole list decides the trade ("buy 100 YES on this outcome"). Spread prices that exact order on both venues from their live order books: each venue's average price, fees, how much it can fill, and the total cost. Then it shows which venue is cheaper for that exact order, after fees. It sends nothing.
- **Arbitrage.** Spread scans markets that are the same bet on both venues. Buying YES on one and NO on the other pays $1 a contract either way, so a price gap looks like free money. Most gaps aren't. Every match goes through the same checks, and Spread shows why each gap was dropped: a venue has no offers, there's no gap, fees are bigger than it, the books are too thin, or the return per day is too low. For a gap that survives, you see both venues side by side, then gross gap → fees → net → return per day, and you can paper-trade both sides. When the two venues word a bet differently, Spread still checks it and shows a warning with it.

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
git clone https://github.com/uselayer/layer-spread-bot
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
| `POLYMARKET_US_KEY_ID`, `POLYMARKET_US_SECRET_KEY` | Live orders, and **Save prices** for Replay (its live stream is read with your key; nothing is traded). Otherwise paper mode reads Polymarket US's public books without a key. | polymarket.us/developer |
| `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY` | The optional chat panel | console.anthropic.com, or openrouter.ai |

## Try it in paper mode

Once http://127.0.0.1:3200 is open. Everything here uses real order books and fake money.

- **Best venue → Search a game.** Type a team or league in the Game box and pick a game, then an outcome, YES or NO and an amount in dollars, and press **Compare venues**. You see what that amount wins on each venue if you're right, fees included, and which one pays more. Each venue gets its own size: the most whole contracts the amount buys there. This tab never sends an order.
- **Best venue → Every market.** Pick a group of markets and press **Check every market**. Each market is compared on both venues, biggest saving first.
- **Arbitrage → Live.** Press **Scan** (about two minutes for 50 markets). The answer comes first: how many gaps are still money after fees, or why none is. When a gap survives, press **Paper-trade both sides**.
- **Arbitrage → Replay.** Pick a game that's on now and press **Save prices**. When it's done, press **Replay** to see whether a gap would have made money after fees (see [Replay prices you saved](#replay-prices-you-saved)).
- **Paper account.** After a paper trade, a line at the top of the Arbitrage tab shows what's open. **Reset** starts the fake account over.

## Strategies

The Best venue screen opens on "Search a game". The Game box lists the soonest open games; each letter you type narrows that list at once, and after a short pause it searches every open game ("Searching all games…" shows until it answers). Pick the outcome, YES or NO and contracts (100 to start), and compare. "Every market" is next to it.

Your strategy decides the trade; the bot finds the cheaper venue for it. Strategies run from code, not from a screen: each one is a file in `engine/spread_engine/strategies/`, listed by the engine's `GET /strategies` and run with `GET /best/signal`.

It comes with examples named the way people trade. They're examples, not advice: none of them is a reason to expect a profit.

| Category | Example | What it buys |
|---|---|---|
| Sports | Back the favorite | Next game first: 100 YES on the side priced 55¢–85¢, at most 85¢ |
| Sports | Longshot under 20¢ | Next game first: 100 YES on an underdog under 20¢, at most 20¢ |
| Sports | Game day: favorite in the last 6 hours | Games starting within 6 hours: 100 YES on the side priced 55¢–90¢, at most 90¢ |
| Crypto | Crypto: nearly decided, last 3 days | Price-line markets closing within 3 days: 100 of the side priced 90¢–97¢, at most 97¢ |
| News, politics & economics | Nearly decided, last 7 days | Markets closing within 7 days: 100 of the side priced 90¢–97¢, at most 97¢ |

Each one looks only at markets that are open on both venues, worded the same on both, with a real price on each (a 1¢ or 99¢ YES is skipped). When nothing fits, it says why in one sentence, e.g. "No trade: Layer has no crypto markets matched on both Kalshi and Polymarket US right now."

"Every market" on the same screen checks the next 25 markets in one category (Sports, News, politics & economics, or Crypto), soonest first, and lists each outcome's price on Kalshi and Polymarket US and which is cheaper for 100 YES after fees, biggest saving first. Rows appear as each comparison finishes: Polymarket US allows only a few book reads every 10 seconds, so a full check takes two to three minutes. A market only one venue can price says why in one sentence, a market Polymarket US didn't answer for says "Couldn't check", and a market whose rules differ slightly on the two venues is shown with that warning. Click a row to see that market's full comparison.

### Add your own

1. Start from the starter file: `cp engine/spread_engine/strategies/my_strategy.py engine/spread_engine/strategies/momentum.py`.
2. Give it a `NAME`, a `CATEGORY` and a one-line `DESCRIPTION`, and write `decide()`: which market, YES or NO, how many contracts, the most you'll pay.
3. Run it against the engine: `curl "http://127.0.0.1:8765/best/signal?strategy=momentum"`. Edits to a strategy apply on the next run, without a restart.

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

- **Paper (the default).** Orders fill against the venues' real order books with fake money, in the bot's own store (`~/.uselayer/spread-bot/paper.db`, or `BOT_STORE_DIR`). Nothing reaches a venue. The "Paper account" line on the Arbitrage screen shows what's open and how much of your limit it uses; "Reset" starts the fake account over.
- **Live.** Set `BOT_MODE=live` in `.env` and add the key for each venue you'll trade, then restart. Orders are then real, with your money. The header shows a red LIVE badge. Only the exact word `live` turns it on. If your account already has orders or positions, the SDK starts a new live store with its kill switch on: check them, then run `uv run python -m uselayer resume --mode live` in `engine/`.
- Live or paper, every order goes through the SDK's guardrails: a budget across everything (`BOT_BUDGET`, default $100), a price collar, and a kill switch. To stop everything from any terminal: `cd engine && uv run python -m uselayer kill --mode paper --store ~/.uselayer/spread-bot/paper.db` (or `live.db` with `--mode live`).
- A comparison is a snapshot of both books when you ran it. A book can move before an order arrives. The order's limit price caps what it can pay, and it's immediate-or-cancel: it fills what's there at that price, and the rest is cancelled. The arbitrage trade reads both books again first and sends nothing if the gap is gone.

## How the arbitrage scan works

Press **Scan**. Settings (folded) holds the search, contracts (100), minimum profit a contract (0¢), minimum return a day (0%) and how many markets (50). A scan of 50 takes about two minutes: Polymarket US asks for a pause when its books are read often, and the SDK waits for it.

The answer comes first: "2 of 50 gaps are still money after fees", or one sentence saying why none is, e.g. "No trade: 46 of 50 have no gap, 3 lose the gap to fees and 1 has nobody selling on one venue."

`engine/spread_engine/funnel.py`. Each matched market stops at the first check it fails, and the fold below the answer lists the dropped ones under these names, one plain sentence each:

1. **Couldn't be priced.** A venue didn't answer, asked for fewer requests, or its key is missing.
2. **Nobody selling.** One venue has nobody selling one side.
3. **No gap.** YES on one venue plus NO on the other costs $1.00 or more before fees.
4. **Fees bigger than the gap.** There's a gap, but the two venues' fees are bigger.
5. **Under your minimum.** Something is left after fees, but less than your minimum a contract.
6. **Too little for sale.** The books can't fill even one contract that clears your minimum.
7. **Pays back too slowly.** The return per day is under your minimum. A 2% gap paid in a month is worse than 1% paid tomorrow.

A gap that survives is a card: both venues side by side (the side to buy, its price as a % and in ¢, and a link to each market), then gross gap → fees → net → return per day for the whole order. Every number comes from the SDK's `client.quote()`.

**Paper-trade both sides** calls `client.trade()`. It reads both books again, and buys only if the gap is still there after fees (at least your minimum a contract); otherwise nothing is bought, and it says so. The scan accepts a book up to 30 seconds old, the age of Polymarket US's cached public book; the trade keeps the SDK's 10-second rule. If a book is older than that, it reads both books once more, then sends nothing and says why.

**Rules differ slightly.** Layer flags a match whose two markets differ on an edge case: a different data source, deadline, rounding, exception or definition. Spread doesn't drop it. It goes through the same checks as any other match and carries an amber note, e.g. "Rules differ slightly on where the result comes from. Both pay the same in normal cases, but in a rare case one could pay and the other not." Then "both sides pay $1" may not hold, so a gap whose rules differ is listed below the ones whose rules match.

Expect most scans to end with no gap. When nothing is still money after fees, the right move is no trade.

## Replay prices you saved

Replay re-runs prices you saved from a live game, moment by moment, to show whether a gap would have made money after fees. It runs the saved order books through the same checks as the live scan, in the SDK's backtest mode.

Nothing comes pre-saved: Kalshi's and Polymarket US's terms don't let this repo ship their prices, so you save your own. On the Arbitrage screen, switch to **Replay**:

1. Under **Save prices**, pick a game (games on now are listed first, since that's when prices move) and how long to save (30 minutes unless you pick otherwise).
2. Press **Save prices**. Both venues' books for that game are saved while it trades, every change. You see the market, the time left and how many price updates are saved so far. **Stop** ends it early and keeps what's saved.
3. When it ends, the new file is selected under **Saved prices**. Press **Replay**.

One recording runs at a time, for as long as the app is running. Saving prices needs your Layer key, your Kalshi key (`KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY_PATH` or `KALSHI_PRIVATE_KEY`) and your Polymarket US key (`POLYMARKET_US_KEY_ID` and `POLYMARKET_US_SECRET_KEY`): each venue's live stream is read with your own key, and nothing is traded. Files go to `recordings/` (not committed), with the match saved next to them.

Advanced: the same recording from a terminal, for any Kalshi ticker Layer has matched (Layer finds its Polymarket US twin):

```bash
npm run record -- KXNBAGAME-26OCT05MEMATL-ATL --minutes 60
```

Any other file the SDK's `import_events` reads works too: type its folder under Settings → Folder. A file without a saved match is paired through Layer's matching. An optional `<name>.meta.json` beside it can give `settles_at` and `"sizes_unknown": true`, for a file whose order sizes are placeholders. Such a file is priced at the Contracts number under Settings (100 by default) at the top price on both venues, and the result says so: "Size unknown: assumes 100 contracts at the top price on both venues." That's an assumption, not depth the file shows. It isn't priced at 1 contract because Kalshi rounds each order's fee up to the cent: on one contract a 0.3¢ fee bills 1¢ and hides a real 1–2¢ gap.

Replays use the SDK's dated fee schedules (uselayer 0.4.1: Kalshi from Oct 1, 2025, Polymarket US from Nov 3, 2025). A payout time that has already passed at a moment of the file (a season-long market whose venue gives the season's start, say) is left out for that moment, so it's priced without a return per day.

The answer comes first: "2 of 8 moments were still money after fees" and how long the gap lasted, then the best moment as the same card as a live gap, and the other moments by reason, folded. When there's nothing to show, it's one sentence:

- No files: "No saved prices yet. Pick a game that's on now and press Save prices."
- No pair in the file: "Can't replay this file: it doesn't hold a Kalshi market and its Polymarket US match together."
- Too early: "Can't replay this file: it's from before Nov 3, 2025, and the SDK doesn't have Polymarket US's fees from before then yet."
- Never priced: "Can't replay this file: it never has prices on both venues at the same moment."
- Nothing survived: "No trade at any of 62 moments: 60 of 62 had no gap and 2 lost the gap to fees."

## Tests

```bash
npm test          # app tests (vitest) + engine tests (pytest); no network
npm run smoke     # every engine route against the real venues, in paper mode; needs your keys in .env
```

To see the screen Polymarket US's "too many requests" leads to without waiting for one, start with `SPREAD_FAKE_BUSY=polymarket_us npm run dev` (paper mode only): every Polymarket US book read then answers "busy".

## Notes

- The engine needs uselayer 0.4.1 or later (`engine/pyproject.toml`), from PyPI.
- Polymarket US answers "too many requests" after about 5 order-book reads in 10 seconds from one IP address by a Python program (measured; it isn't published), and every Python program on your network shares that. So the engine reads at most 4 Polymarket US books in any 10 seconds, reads a strategy's games one at a time, reuses a book for 3 seconds while comparing (never for an order), and after a "too many requests" waits as long as Polymarket US asks (`engine/spread_engine/reads.py`). If Polymarket US is still busy, the screen says so and offers "Try again"; it never calls Kalshi "the only venue" because Polymarket US didn't answer.
- Spread never calls anything "risk-free": a gap can close before both orders fill, and venues can settle the same event differently.
- MIT licensed: see [LICENSE](LICENSE).
