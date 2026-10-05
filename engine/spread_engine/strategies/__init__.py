"""Strategies: where your bot's own logic goes.

Each file in this folder is one strategy. It has a NAME, a one-line DESCRIPTION and a
``decide(matches, client)`` function that returns a :class:`Signal` (the trade you want) or None (no
trade). The app's strategy picker lists every file here, so adding a file adds a choice. Start from
``my_strategy.py``.

The bot doesn't judge your strategy. It takes the Signal and does Job 1: it prices that exact order
on both venues, after fees and depth, and sends it to the cheaper one (paper unless BOT_MODE=live).
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from uselayer import Client, Match, Prices, VenueError


@dataclass(frozen=True)
class Signal:
    """The trade your strategy wants."""

    match: Match  # the market (one of the matches you were given)
    side: str  # "yes" or "no": the outcome both venues' markets name
    size: int  # contracts
    max_price: float | None = None  # never pay more than this a contract, in dollars (None: the SDK's price collar)
    why: str = ""  # one line, shown in the app: why your strategy picked this


Decide = Callable[[list[Match], Client], "Signal | None"]


def upcoming(m: Match) -> bool:
    """The event hasn't started yet (or has no start time)."""
    t = m.kalshi.event_time or m.polymarket_us.event_time
    if not t:
        return True
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")) > datetime.now(UTC)
    except ValueError:
        return True


def priced(matches: list[Match], client: Client, *, limit: int = 10) -> Iterator[tuple[Match, Prices]]:
    """Upcoming matches whose rules don't differ, with both venues' best prices (``client.prices``).

    Reads at most ``limit`` matches' prices (each read is both venues' books) and skips any where a
    venue has no YES on offer.
    """
    looked = 0
    for m in matches:
        if m.caveats or not upcoming(m):
            continue
        if looked == limit:
            return
        looked += 1
        try:
            p = client.prices(m)
        except VenueError:
            continue
        if p.a.yes_ask is None or p.b.yes_ask is None:
            continue
        yield m, p


def cheapest_yes(p: Prices) -> float:
    """The lower of the two venues' best YES asks."""
    asks = [x for x in (p.a.yes_ask, p.b.yes_ask) if x is not None]
    return min(asks)


def _modules() -> list[ModuleType]:
    out = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        mod = importlib.reload(mod)  # pick up edits without a restart
        if callable(getattr(mod, "decide", None)):
            out.append(mod)
    return out


def available() -> list[dict[str, Any]]:
    """Every strategy file in this folder: ``{"id", "name", "description"}``. Examples first, yours last."""
    mods = _modules()
    rows = [
        {
            "id": m.__name__.rsplit(".", 1)[-1],
            "name": getattr(m, "NAME", m.__name__.rsplit(".", 1)[-1]),
            "description": getattr(m, "DESCRIPTION", ""),
            "example": bool(getattr(m, "EXAMPLE", False)),
            "order": getattr(m, "ORDER", 50),
        }
        for m in mods
    ]
    return sorted(rows, key=lambda r: (r["order"], r["name"]))


def get(strategy_id: str) -> Decide:
    for m in _modules():
        if m.__name__.rsplit(".", 1)[-1] == strategy_id:
            return m.decide  # type: ignore[no-any-return]
    raise KeyError(f"No strategy named {strategy_id!r} in engine/spread_engine/strategies/.")
