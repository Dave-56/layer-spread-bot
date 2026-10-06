"""Example, not advice: back the favorite in the last hours before the game."""

from __future__ import annotations

from uselayer import Client, Match

from . import SPORTS, NoTrade, Signal, cheapest, event, game_winner, hours_until, outcome, price_words, priced, soonest, starts_at

NAME = "Game day: favorite in the last 6 hours"
CATEGORY = SPORTS
DESCRIPTION = "Only games starting in the next 6 hours: puts $50 on YES for the side priced between 55¢ and 90¢, paying at most 90¢."
EXAMPLE = True
ORDER = 30
LAYER_CATEGORIES = ("sports",)

HOURS = 6
LOW, HIGH = 0.55, 0.90


def decide(matches: list[Match], client: Client) -> Signal | NoTrade:
    soon = [m for m in soonest(matches) if game_winner(m) and 0 < (hours_until(starts_at(m)) or -1) <= HOURS]
    if not soon:
        return NoTrade(f"No game matched on both venues starts in the next {HOURS} hours.")
    for m, p in priced(soon, client):
        yes = cheapest(p, "yes")
        if yes is not None and LOW <= yes <= HIGH:
            h = hours_until(starts_at(m)) or 0
            starts = f"{h:.0f} hours" if h >= 1.5 else f"{h * 60:.0f} minutes"
            return Signal(m, "yes", 50, max_price=HIGH, why=f"{event(m)} starts in {starts} and {outcome(m)} is the favorite: YES costs {price_words(yes)}.")
    return NoTrade(f"No game in the next {HOURS} hours has a favorite priced between 55¢ and 90¢ right now.")
