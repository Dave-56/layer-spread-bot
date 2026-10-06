"""Example, not advice: a crypto price line that's nearly decided, close to its deadline."""

from __future__ import annotations

from uselayer import Client, Match

from . import CRYPTO, NoTrade, Signal, cheapest, closes_at, hours_until, outcome, price_words, priced

NAME = "Crypto: nearly decided, last 3 days"
CATEGORY = CRYPTO
DESCRIPTION = 'Price-line markets ("BTC above $X on a date") closing within 3 days: puts $50 on the side priced 90¢ to 97¢, paying at most 97¢.'
EXAMPLE = True
ORDER = 10
LAYER_CATEGORIES = ("crypto",)

DAYS = 3
LOW, HIGH = 0.90, 0.97


def decide(matches: list[Match], client: Client) -> Signal | NoTrade:
    if not matches:
        return NoTrade("Layer has no crypto markets matched on both Kalshi and Polymarket US right now.")
    soon = [m for m in matches if 0 < (hours_until(closes_at(m)) or -1) <= DAYS * 24]
    if not soon:
        return NoTrade(f"No crypto market matched on both venues closes in the next {DAYS} days.")
    for m, p in priced(sorted(soon, key=lambda m: closes_at(m)), client):  # type: ignore[arg-type, return-value]
        for side in ("yes", "no"):
            ask = cheapest(p, side)
            if ask is not None and LOW <= ask <= HIGH:
                days = (hours_until(closes_at(m)) or 0) / 24
                return Signal(m, side, 50, max_price=HIGH, why=f"{side.upper()} on {outcome(m)} costs {price_words(ask)} with {days:.1f} days left.")
    return NoTrade(f"No crypto market closing in the next {DAYS} days has a side priced between 90¢ and 97¢ right now.")
