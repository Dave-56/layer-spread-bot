"""Example, not advice: a longshot under 20¢ in the next game."""

from __future__ import annotations

from uselayer import Client, Match

from . import SPORTS, NoTrade, Signal, cheapest, event, game_winner, outcome, price_words, priced, soonest

NAME = "Longshot under 20¢"
CATEGORY = SPORTS
DESCRIPTION = "Next game first: buys 100 YES on an underdog priced under 20¢, paying at most 20¢. Most longshots lose."
EXAMPLE = True
ORDER = 20
LAYER_CATEGORIES = ("sports",)

MAX = 0.20


def decide(matches: list[Match], client: Client) -> Signal | NoTrade:
    games = soonest(m for m in matches if game_winner(m))
    if not games:
        return NoTrade("No upcoming game is matched on both venues for this search.")
    for m, p in priced(games, client):
        yes = cheapest(p, "yes")
        if yes is not None and yes < MAX:
            return Signal(m, "yes", 100, max_price=MAX, why=f"{outcome(m)} is a longshot in {event(m)}: YES costs {price_words(yes)}.")
    return NoTrade("None of the next games has a side priced under 20¢ right now.")
