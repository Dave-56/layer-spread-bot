"""Example, not advice: a news, politics, economics or culture market that's nearly decided, close to resolving."""

from __future__ import annotations

from uselayer import Client, Match

from . import NEWS, NoTrade, Signal, cheapest, closes_at, event, hours_until, outcome, price_words, priced

NAME = "Nearly decided, last 7 days"
CATEGORY = NEWS
DESCRIPTION = "News, politics, economics and culture markets closing within 7 days: puts $50 on the side priced 90¢ to 97¢, paying at most 97¢."
EXAMPLE = True
ORDER = 10
LAYER_CATEGORIES = ("politics", "economics", "culture")

DAYS = 7
LOW, HIGH = 0.90, 0.97


def decide(matches: list[Match], client: Client) -> Signal | NoTrade:
    if not matches:
        return NoTrade("Layer has no news, politics, economics or culture markets matched on both venues right now.")
    soon = [m for m in matches if 0 < (hours_until(closes_at(m)) or -1) <= DAYS * 24]
    if not soon:
        return NoTrade(f"None of the {len(matches)} news, politics, economics or culture markets matched on both venues closes in the next {DAYS} days.")
    for m, p in priced(sorted(soon, key=lambda m: closes_at(m)), client):  # type: ignore[arg-type, return-value]
        for side in ("yes", "no"):
            ask = cheapest(p, side)
            if ask is not None and LOW <= ask <= HIGH:
                days = (hours_until(closes_at(m)) or 0) / 24
                return Signal(m, side, 50, max_price=HIGH, why=f"{event(m)}: {side.upper()} on {outcome(m)} costs {price_words(ask)}, {days:.1f} days before it closes.")
    return NoTrade(f"No market closing in the next {DAYS} days has a side priced between 90¢ and 97¢ right now.")
