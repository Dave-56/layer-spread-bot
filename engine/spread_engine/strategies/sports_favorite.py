"""Example, not advice: back the favorite in the next game."""

from __future__ import annotations

from uselayer import Client, Match

from . import SPORTS, NoTrade, Signal, cheapest, event, game_winner, outcome, price_words, priced, soonest

NAME = "Back the favorite"
CATEGORY = SPORTS
DESCRIPTION = "Next game first: puts $50 on YES for the side the market prices between 55¢ and 85¢, paying at most 85¢."
EXAMPLE = True
ORDER = 10
LAYER_CATEGORIES = ("sports",)

LOW, HIGH = 0.55, 0.85


def decide(matches: list[Match], client: Client) -> Signal | NoTrade:
    games = soonest(m for m in matches if game_winner(m))
    if not games:
        return NoTrade("No upcoming game is matched on both venues for this search.")
    for m, p in priced(games, client):
        yes = cheapest(p, "yes")
        if yes is not None and LOW <= yes <= HIGH:
            return Signal(m, "yes", 50, max_price=HIGH, why=f"{outcome(m)} is the favorite in {event(m)}: YES costs {price_words(yes)}.")
    return NoTrade("None of the next games has a favorite priced between 55¢ and 85¢ right now.")
