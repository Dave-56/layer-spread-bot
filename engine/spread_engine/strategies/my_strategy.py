"""YOUR STRATEGY. Copy this file (e.g. to strategies/momentum.py), give it a NAME, write decide().

It shows up in the app's strategy picker on the Best venue tab, under "Your own". Edits are picked up
the next time you press "Run strategy"; a new file appears after you reload the page. You can also add
a file from the app ("Add your strategy"), which saves it in this folder.
"""

from __future__ import annotations

from uselayer import Client, Match

from . import YOURS, NoTrade, Signal

NAME = "My strategy (template)"
CATEGORY = YOURS
DESCRIPTION = "Your logic goes here: engine/spread_engine/strategies/my_strategy.py. Until you write it, it makes no trade."
ORDER = 90
# LAYER_CATEGORIES = ("sports",)  # optional: only these Layer categories ("sports", "crypto", "politics", ...)


def decide(matches: list[Match], client: Client) -> Signal | NoTrade | None:
    # `matches`: markets Layer says are the same bet on Kalshi and Polymarket US (the search on screen).
    #   m.kalshi.outcome, m.kalshi.event, m.kalshi.event_time, m.caveats (rule differences) ...
    # `client`: the uselayer SDK with your own keys. Read anything you need:
    #   p = client.prices(m)  → p.a.yes_ask, p.b.yes_ask, p.leg("kalshi").no_ask ...
    #   client.book(m.kalshi)  → a full order book
    # Helpers in strategies/__init__.py:
    #   priced(matches, client)  → upcoming matches open on both venues, worded the same on both,
    #     with both venues' prices (a 1¢ or 99¢ YES ask is skipped as no real price)
    #   cheapest(p, "yes"), soonest(matches), game_winner(m), starts_at(m), closes_at(m)
    #
    # Write your logic here: which market, YES or NO, how many contracts, and the most you'll pay.
    #
    # for m, p in priced(matches, client):
    #     if <your condition on m and p>:
    #         return Signal(m, "yes", 50, max_price=0.60, why="<one line on why>")
    return NoTrade("This is the template: write your logic in strategies/my_strategy.py.")
