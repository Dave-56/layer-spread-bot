"""Best venue by the dollar: what an amount buys on each venue, and which pays more if you win.

You say "$50 on YES". For each venue the engine finds the most whole contracts whose cost plus fees
fits in $50, each venue at its own size, and compares what they pay if you're right ($1 a contract,
what the venues call "to win"). Every price and fee is the SDK's (``preview_best``): each venue's book
is read once, then every size is priced against those same books in the SDK's backtest mode, so the
search sends no extra requests.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from uselayer import Client, Match, VenueError

from .views import (
    DIDNT_ANSWER,
    VENUE_NAMES,
    _venue_row,
    busy_sentence,
    cents_label,
    money_label,
    pair_view,
    plain_error,
)

VENUES = ("kalshi", "polymarket_us")
MAX_SPEND = 100_000.0

Pricer = Callable[[int], Any]  # a whole number of contracts → the SDK's comparison at that size (BestVenue)


def dollars(x: float) -> str:
    """$50, $49.98: whole dollars without cents."""
    return f"${x:,.0f}" if abs(x - round(x)) < 0.005 else money_label(x)  # type: ignore[return-value]


def _row(price: Pricer, venue: str, n: int) -> Any:
    return next(v for v in price(n).venues if v.venue == venue)


def _fits(r: Any, spend: float) -> bool:
    return bool(r.ok and r.all_in is not None and r.all_in <= spend + 1e-9)


def most_for(price: Pricer, venue: str, spend: float) -> tuple[Any, Any | None, bool]:
    """The most whole contracts on ``venue`` whose cost plus fees fits in ``spend``.

    Returns (the venue at 1 contract, the venue at the most that fits or None, whether its depth ran
    out before the money did). Cost plus fees only grows with size, so a binary search finds it.
    """
    one = _row(price, venue, 1)
    if not _fits(one, spend):
        return one, None, False
    lo, best = 1, one
    hi = max(1, math.floor(spend / one.best_price)) if one.best_price else 1  # fees only lower it
    while lo < hi:
        mid = (lo + hi + 1) // 2
        r = _row(price, venue, mid)
        if _fits(r, spend):
            lo, best = mid, r
        else:
            hi = mid - 1
    after = _row(price, venue, lo + 1)
    return one, best, (not after.ok and after.skip == "not_enough_size")


def _failed_row(venue: str, e: VenueError) -> dict[str, Any]:
    """A venue whose book couldn't be read: no numbers, one sentence why."""
    said = plain_error(e)
    return {
        "venue": venue, "venue_name": VENUE_NAMES[venue], "market": None, "ok": False, "cheaper": False,
        "skip": "unavailable" if e.code in DIDNT_ANSWER else e.code, "skip_reason": said, "skip_line": said,
        "unavailable": e.code in DIDNT_ANSWER, "price": None, "price_label": None, "chance_label": None,
        "avg_price": None, "avg_price_label": None, "limit_price": None, "fees": None, "fillable": None,
        "cap_label": None, "total_cost": None, "total_cost_per_contract": None, "cost_line": None,
        "contracts": None, "payout": None, "win_line": None, "depth_limited": False,
    }


def spend_view(
    m: Match,
    side: str,
    spend: float,
    price: Pricer | None,
    *,
    failed: dict[str, VenueError] | None = None,
    collar: float | None = None,
) -> dict[str, Any]:
    """``spend`` dollars on ``side`` of ``m``, on each venue at its own size, labelled for the app.

    The same shape as :func:`views.compare_view` (so the app's card shows it), plus each venue's
    ``contracts``, ``payout`` and ``win_line``, and the answer as ``headline``.
    """
    failed = failed or {}
    found: dict[str, tuple[Any, Any | None, bool]] = {}
    for v in VENUES:
        if v not in failed and price is not None:
            found[v] = most_for(price, v, spend)
    # The one that pays more if you win: the most contracts, then the lower cost, then Kalshi.
    can = [(v, best) for v, (_, best, _) in found.items() if best is not None]
    chosen = min(can, key=lambda x: (-x[1].size, x[1].all_in, VENUES.index(x[0])))[0] if can else None
    # The pill on its card: it pays more, or the same payout costs less there. Identical: no pick.
    pick = "Pays more" if chosen else None
    if len(can) == 2 and can[0][1].size == can[1][1].size:
        same_cost = abs(can[0][1].all_in - can[1][1].all_in) < 0.005
        chosen, pick = (None, None) if same_cost else (chosen, "Cheaper")
    unknown = [v for v in VENUES if (v in failed and failed[v].code in DIDNT_ANSWER)]
    unknown += [v for v, (one, _, _) in found.items() if one.skip in ("unavailable", "stale_book")]
    if unknown:
        chosen, pick = None, None

    rows = []
    for v in VENUES:
        if v in failed:
            rows.append(_failed_row(v, failed[v]))
            continue
        one, best, depth = found[v]
        row = _venue_row(best or one, chosen)
        n = math.floor(best.size + 1e-9) if best is not None else None
        if best is None and one.ok:  # it can fill one contract, but not for this little
            row["ok"] = False
            row["skip_reason"] = row["skip_line"] = (
                f"{dollars(spend)} doesn't buy one contract on {VENUE_NAMES[v]}: one costs {money_label(one.all_in)} with its fee."
            )
        row.update(
            contracts=n,
            payout=n,
            win_line=f"Wins {dollars(n)}" if n else None,
            depth_limited=depth,
        )
        rows.append(row)

    headline = _headline(spend, side, rows, chosen, unknown)
    note = collar_note_for(rows, collar)
    if note:
        headline["detail"] = " ".join(filter(None, [headline.get("detail"), note]))
    return {
        "action": "buy",
        "side": side,
        "size": None,
        "spend": spend,
        "spend_label": dollars(spend),
        "max_price": None,
        "pair": pair_view(m),
        "venues": rows,
        "cheaper": chosen,
        "pick_label": pick,  # "Pays more" or "Cheaper": the pill on the chosen venue's card
        "cheaper_name": VENUE_NAMES.get(chosen) if chosen else None,
        "unavailable": [VENUE_NAMES[v] for v in unknown],
        "saving": None,
        "saving_label": None,
        "verdict": headline["title"],
        "headline": headline,
        "try_size": None,
        "collar_note": None,
        "as_of": None,
    }


def collar_note_for(rows: list[dict[str, Any]], collar: float | None) -> str | None:
    """Why a venue used only part of the money: its depth near the cheapest price ran out."""
    short = [r for r in rows if r.get("depth_limited") and r.get("contracts")]
    if not short:
        return None
    lines = [
        f"{r['venue_name']} has only {r['contracts']:,} for sale near its cheapest price, so it uses {money_label(r['total_cost'])}."
        for r in short
    ]
    if collar is not None:
        lines.append(f"Spread pays at most {cents_label(collar)} above a venue's cheapest offer.")
    return " ".join(lines)


def _headline(spend: float, side: str, rows: list[dict[str, Any]], chosen: str | None, unknown: list[str]) -> dict[str, Any]:
    amount, on = dollars(spend), f"{side.upper()}"
    skipped = " ".join(r["skip_line"] for r in rows if not r["ok"] and r.get("skip_line"))
    if unknown:
        return {"title": busy_sentence(unknown), "detail": None, "retry": True}
    can = [r for r in rows if r["ok"] and r.get("contracts")]
    if len(can) == 2 and chosen is None:  # the same contracts for the same cost
        costs = f"{can[0]['venue_name']} {money_label(can[0]['total_cost'])}, {can[1]['venue_name']} {money_label(can[1]['total_cost'])}, fees included."
        return {"title": f"Same on both: your {amount} wins {dollars(can[0]['payout'])} either way", "detail": costs, "retry": False}
    if not can or chosen is None:
        return {"title": f"No trade: neither venue can take {amount} on {on} right now", "detail": skipped or None, "retry": False}
    best = next(r for r in rows if r["venue"] == chosen)
    name = best["venue_name"]
    if len(can) == 1:
        return {
            "title": f"Buy on {name}: the only venue that can take {amount} on {on}",
            "detail": f"It wins {dollars(best['payout'])} if you're right, fees included. {skipped}".strip(),
            "retry": False,
        }
    other = next(r for r in can if r["venue"] != chosen)
    if best["contracts"] == other["contracts"]:
        # The same payout: the one that costs less for it.
        diff = (other["total_cost"] or 0) - (best["total_cost"] or 0)
        costs = f"{name} {money_label(best['total_cost'])}, {other['venue_name']} {money_label(other['total_cost'])}, fees included."
        return {
            "title": f"Buy on {name}: the same {dollars(best['payout'])} if you win, {money_label(diff)} cheaper",
            "detail": f"Your {amount} buys {best['contracts']:,} {on} on both venues: {costs}",
            "retry": False,
        }
    more = best["payout"] - other["payout"]
    return {
        "title": f"Buy on {name}: it pays {dollars(more)} more if you win",
        "detail": f"Your {amount} wins {dollars(best['payout'])} on {name} and {dollars(other['payout'])} on {other['venue_name']}, fees included.",
        "retry": False,
    }


def books_view(
    m: Match, side: str, spend: float, books: Iterable[Any], *, rules: Any = None, failed: dict[str, VenueError] | None = None, collar: float | None = None
) -> dict[str, Any]:
    """:func:`spend_view` priced against ``books`` (each venue's latest), in the SDK's backtest mode."""
    books = list(books)
    if not books:
        return spend_view(m, side, spend, None, failed=failed, collar=collar)
    out: dict[str, Any] = {}
    seen: set[tuple[str, str]] = set()

    def on_book(bc: Client, b: Any) -> None:
        seen.add((b.venue, b.market))
        if len(seen) == len({(x.venue, x.market) for x in books}) and "view" not in out:
            cache: dict[int, Any] = {}

            def price(n: int) -> Any:
                if n not in cache:
                    cache[n] = bc.preview_best(m, side, n).why
                return cache[n]

            out["view"] = spend_view(m, side, spend, price, failed=failed, collar=collar)

    Client(mode="backtest", books=sorted(books, key=lambda b: b.as_of), store=":memory:", rules=rules, on_alert=lambda e: None).replay(on_book)
    return out["view"]


def read_books(client: Client, m: Match) -> tuple[list[Any], dict[str, VenueError]]:
    """Each venue's book for ``m``, read once. Polymarket US first: its reads are paced, Kalshi's are quick,
    so the two are close together in time. A venue that can't be read is kept with its error."""
    books, failed = [], {}
    for venue, market in (("polymarket_us", m.polymarket_us.market_id), ("kalshi", m.kalshi.market_id)):
        try:
            books.append(client.book(market, venue=venue))
        except VenueError as e:
            failed[venue] = e
    return books, failed
