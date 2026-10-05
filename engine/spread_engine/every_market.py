"""Best venue for every market: the next matched markets, each priced on both venues, streamed.

One click checks up to ``limit`` markets in one category (the next games first) and sends one row per
outcome as each comparison finishes: Kalshi's price, Polymarket US's price, which is cheaper for the
order after fees and by how much. Every number is the SDK's ``client.preview_best()``, labelled by
:func:`views.compare_view`, the same as the strategy path. A market Layer says is worded differently is
priced and shown with its warning, never dropped.

Polymarket US books can take up to ~30 s each (its public book is cached), so the scan is bounded and
reads :data:`strategies.READERS` at once: more makes Polymarket US answer "too many requests".
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from uselayer import Match

from .strategies import CRYPTO, NEWS, READERS, SPORTS, closes_at, starts_at
from .views import error_line, error_view, match_id, match_view


@dataclass(frozen=True)
class Category:
    name: str  # as the app shows it (the strategy picker's own names)
    layer: tuple[str, ...]  # Layer's categories
    noun: str  # in a sentence: "Layer has no <noun> markets matched …"


CATEGORIES = {
    "sports": Category(SPORTS, ("sports",), "sports"),
    "news": Category(NEWS, ("politics", "economics", "culture"), "news, politics, economics or culture"),
    "crypto": Category(CRYPTO, ("crypto",), "crypto"),
}

LISTED = 200  # matches listed per Layer category before the soonest are picked (listing reads no book)
FAR = datetime.max.replace(tzinfo=UTC)


def soonest_first(matches: list[Match]) -> list[Match]:
    """The next games first: by start time, else by when the market closes (no time: last)."""
    return sorted(matches, key=lambda m: starts_at(m) or closes_at(m) or FAR)


def empty_line(cat: Category, started: int) -> str:
    """Why there's nothing to check, in one sentence."""
    if started:
        return f"All {started:,} {cat.noun} markets matched on both venues have already started or finished."
    return f"Layer has no {cat.noun} markets matched on both Kalshi and Polymarket US right now."


def outcome(best: dict[str, Any]) -> str:
    """How one comparison came out: ``kalshi`` / ``polymarket_us`` (cheaper), ``same``, ``one_venue``,
    ``neither`` or ``error``. Read from the SDK's own ``reason_code``."""
    if not best.get("ok"):
        return "error"
    code = (best.get("why") or {}).get("reason_code")
    if code == "cheaper":
        return best["why"]["venue"]
    if code in ("tie_more_size", "tie_first_listed"):
        return "same"
    if code == "only_venue":
        return "one_venue"
    return "neither"


OUTCOMES = ("kalshi", "polymarket_us", "same", "one_venue", "neither", "error")

Price = Callable[[Match, str, int], dict[str, Any]]


def scan(
    matches: list[Match], price: Price, *, category: str, size: int, started: int = 0, side: str = "yes"
) -> Iterator[dict[str, Any]]:
    """Stream ``start`` (with ``empty``: one sentence when there's nothing to check), one ``row`` per
    market as its comparison finishes, then ``done`` with how many came out each way.

    ``price(match, side, size)`` is the engine's preview: ``{"ok": True, ...BestOrder, "compare"}`` or
    ``{"ok": False, "error", "error_line"}``. A failure is that row's plain reason, never the scan's.
    """
    cat = CATEGORIES[category]
    counts = dict.fromkeys(OUTCOMES, 0)
    yield {
        "type": "start",
        "total": len(matches),
        "category": cat.name,
        "size": size,
        "side": side,
        "empty": None if matches else empty_line(cat, started),
    }
    pool = ThreadPoolExecutor(max_workers=READERS)
    try:
        reads = {pool.submit(price, m, side, size): m for m in matches}
        for read in as_completed(reads):
            m = reads[read]
            try:
                best = read.result()
            except Exception as e:  # noqa: BLE001  (one market's failure is its row, never the scan's)
                best = {"ok": False, "error": error_view(e), "error_line": error_line(e)}
            how = outcome(best)
            counts[how] += 1
            yield {
                "type": "row",
                "match": match_view(m),
                "order": {"match_id": match_id(m), "side": side, "size": size, "max_price": None},
                "best": best,
                "outcome": how,
            }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # the page closed: stop reading books
    yield {"type": "done", "total": len(matches), "counts": counts}
