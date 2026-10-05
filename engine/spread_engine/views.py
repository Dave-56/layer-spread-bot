"""SDK objects as the plain JSON the web app shows. No math here: every number comes from the SDK."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from uselayer import Match, VenueError

VENUE_NAMES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US"}


def venue_name(venue: str | None) -> str:
    if venue is None:
        return "The venue"
    return {**VENUE_NAMES, "layer": "Layer"}.get(venue, venue)


def market_view(m: Any) -> dict[str, Any]:
    return {
        "venue": m.venue,
        "market_id": m.market_id,
        "url": m.url,
        "event": m.event,
        "question": m.question,
        "outcome": m.outcome,
        "event_time": m.event_time,
        "close_time": m.close_time,
    }


# Layer's codes: same event and outcome normally, but the rules differ on an edge case.
CAVEATS = {
    "source_differs": "different data source",
    "timing_differs": "different deadline, measurement time or timezone",
    "rounding_differs": "different rounding or threshold",
    "carveout_differs": "different special exceptions (e.g. ambiguity rules)",
    "definition_differs": "a term is defined differently",
}


def rule_warning(m: Match) -> str | None:
    """Layer's rule difference for a match, as one plain warning, or None when it flagged none.

    The match still goes through every check: the warning travels with it wherever it's shown.
    """
    if not m.caveats:
        return None
    words = [CAVEATS.get(c, c.replace("_", " ")) for c in m.caveats]
    said = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    return f"Worded differently: {said}. The two could settle differently."


def match_id(m: Match) -> str:
    """A match is keyed by its Kalshi market id (one Kalshi market has one Polymarket US twin)."""
    return m.kalshi.market_id


def match_view(m: Match) -> dict[str, Any]:
    k, u = m.kalshi, m.polymarket_us
    title = k.event or u.event or k.market_id
    outcome = k.outcome or u.outcome or k.question or u.question
    return {
        "id": match_id(m),
        "title": title,
        "outcome": outcome,
        "category": m.category,
        "event_date": m.event_date,
        "event_time": k.event_time or u.event_time,
        "confidence": m.confidence,
        "caveats": list(m.caveats),
        "rule_warning": rule_warning(m),
        "event_key": k.group_id or u.group_id,  # the same for every outcome of one game or event
        "kalshi": market_view(k),
        "polymarket_us": market_view(u),
    }


def _time(t: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
    except ValueError:
        return None


def over(m: Match, now: datetime | None = None) -> bool:
    """The event is over: a venue's market has closed, or it started more than 12 hours ago."""
    now = now or datetime.now(UTC)
    closes = [t for t in (_time(m.kalshi.close_time), _time(m.polymarket_us.close_time)) if t]
    starts = [t for t in (_time(m.kalshi.event_time), _time(m.polymarket_us.event_time)) if t]
    return any(t < now for t in closes) or any(t < now - timedelta(hours=12) for t in starts)


def error_view(e: Exception) -> dict[str, Any]:
    """An error for the app: ``message`` is one plain sentence (:func:`plain_error`); ``detail`` keeps the SDK's own words."""
    if isinstance(e, VenueError):
        plain = plain_error(e)
        return {
            "code": e.code,
            "message": plain,
            # The SDK's hint is for a developer; a sentence we wrote already says what to do.
            "hint": None if plain != e.message else getattr(e, "hint", None),
            "venue": e.venue,
            "unavailable": e.code in DIDNT_ANSWER,
            "detail": e.message,
        }
    return {"code": "error", "message": str(e) or type(e).__name__, "hint": None, "venue": None, "unavailable": False, "detail": None}


# A venue that didn't answer (busy, down, or a book too old to use): its price isn't known, which is
# not the same as "it can't fill this".
DIDNT_ANSWER = frozenset({"rate_limited", "venue_unavailable", "venue_maintenance", "stale_quote"})


def plain_error(e: VenueError) -> str:
    """The SDK's error as one plain sentence with the venue's name. Codes not listed keep the SDK's sentence."""
    v = venue_name(e.venue)
    code = e.code
    if code == "rate_limited":
        return f"{v} is busy right now. Try again in a few seconds."
    if code == "venue_maintenance":
        return f"{v} is down for maintenance. Try again later."
    if code == "venue_unavailable":
        return f"{v} didn't answer just now. Try again in a few seconds."
    if code == "stale_quote":
        return f"{v}'s prices are too old to use right now. Try again in a few seconds."
    if code == "market_closed":
        return f"This market is closed on {v}."
    if code == "not_found":
        return f"{v} doesn't know this market."
    if code == "auth_failed":
        if e.status is None:  # no key was given
            return f"Add your {v} key to .env, then restart."
        return f"{v} didn't accept your key. Check it in .env, then restart."
    if code == "not_allowed":
        return f"{v} doesn't let this account trade this market."
    if code == "insufficient_balance":
        return f"There isn't enough money in your {v} account for this order."
    if code == "outcome_unknown":
        return f"We don't know if {v} took the order. Check your {v} account before trying again."
    if code == "venue_switched_off":
        return f"This release doesn't trade on {v}."
    if code == "killed":
        return "The kill switch is on, so nothing was sent."
    if code == "format_changed":
        return f"{v} answered in a way this version of uselayer can't read. Update uselayer."
    if code == "bad_data":
        return f"{v} sent data we couldn't read. Try again in a few seconds."
    if code == "not_available" and isinstance(e.raw, dict) and "venues" in e.raw:
        return "Neither venue can take this order right now."
    if code == "invalid_order" and e.venue:
        return f"{v} turned this order down."
    return e.message


def busy_sentence(venues: Any, *, prices: bool = False) -> str:
    """The venues that didn't answer, as the one sentence the app leads with.

    ``prices=False`` (one comparison): "Couldn't get Polymarket US's price just now, so we can't compare yet."
    ``prices=True`` (a strategy's reads): "Couldn't get Polymarket US's prices just now, so there's no answer yet."
    """
    venues = set(venues)
    names = [VENUE_NAMES[v] for v in ("kalshi", "polymarket_us") if v in venues or VENUE_NAMES[v] in venues]
    names += [venue_name(v) for v in sorted(venues) if v not in VENUE_NAMES and v not in VENUE_NAMES.values()]
    who = " or ".join(f"{n}'s" for n in names) or "a venue's"
    if prices:
        return f"Couldn't get {who} prices just now, so there's no answer yet."
    word = "price" if len(names) <= 1 else "prices"
    return f"Couldn't get {who} {word} just now, so we can't compare yet."


# ---- Best venue: the comparison as the app shows it -------------------------------------------

# The SDK's skip codes (uselayer.best) as one sentence each, for the codes skip_sentence() doesn't word
# with the book's own numbers. {n} is the venue's name, {side} YES or NO, {size} the contracts.
SKIP = {
    "switched_off": "This release doesn't trade on {n}.",
    "no_key": "Add your {n} key to .env to price it here.",
    "not_allowed": "Your rules don't allow this order on {n}.",
    "not_found": "{n} doesn't know this market.",
    "market_closed": "This market is closed on {n}.",
    "no_book": "There's no book for this market on {n}.",
    "stale_book": "{n}'s prices are too old to use right now. Try again in a few seconds.",
    "no_offers": "Nobody is selling {side} on {n} right now.",
    "above_max_price": "{n}'s cheapest {side} costs more than your max price.",
    "below_min_price": "{n}'s best bid is below your min price.",
    "not_enough_size": "{n} doesn't have {size} {side} for sale near its best price.",
    "invalid_order": "This order breaks {n}'s price step or minimum size.",
    "not_held": "You don't hold enough of this on {n} to sell it.",
    "unavailable": "{n} didn't answer just now. Try again in a few seconds.",
}
UNKNOWN_SKIPS = frozenset({"unavailable", "stale_book"})  # the venue's price isn't known


def skip_line(v: Any, limit: float | None = None) -> str | None:
    """Why a venue can't take the order, as one plain sentence (:func:`skip_sentence`)."""
    return skip_sentence(v, limit)


def error_line(e: Exception) -> str:
    """A comparison that couldn't run, as one plain sentence."""
    if isinstance(e, VenueError):
        return plain_error(e)
    return "Couldn't read the prices for this one. Try again in a few seconds."


def _num(x: float) -> str:
    return f"{round(x, 1):g}"


def cents_label(p: float | None) -> str | None:
    """A price as cents: ``54¢``, ``54.5¢``."""
    return None if p is None else f"{_num(p * 100)}¢"


def chance_label(p: float | None) -> str | None:
    """A price as the chance the market gives the side: ``54%``."""
    return None if p is None else f"{_num(p * 100)}%"


def money_label(x: float | None) -> str | None:
    return None if x is None else f"{'−' if x < 0 else ''}${abs(x):,.2f}"


def match_note(m: Match) -> str:
    """Layer's word on the pair, in one or two plain sentences."""
    conf = f" ({m.confidence * 100:.0f}% confidence)" if m.confidence is not None else ""
    note = f"Layer matched these as the same bet{conf}."
    w = rule_warning(m)
    return f"{note} {w}" if w else note


def pair_view(m: Match) -> dict[str, Any]:
    """The matched pair: each venue's title, id and link, and Layer's note."""
    k, u = m.kalshi, m.polymarket_us
    return {
        "kalshi": {"title": k.event, "outcome": k.outcome, "question": k.question, "ticker": k.market_id, "url": k.url},
        "polymarket_us": {"title": u.event, "outcome": u.outcome, "question": u.question, "slug": u.market_id, "url": u.url},
        "note": match_note(m),
        "confidence": m.confidence,
        "rule_warning": rule_warning(m),
    }


def _size(n: float) -> str:
    return f"{n:,g}"


def skip_sentence(v: Any, limit: float | None = None) -> str | None:
    """Why a venue can't take the order (``uselayer.best.VenueCost.skip``), as one plain sentence."""
    if not v.skip:
        return None
    n = VENUE_NAMES.get(v.venue, v.venue)
    side = str(v.side).upper()
    buy = getattr(v, "action", "buy") != "sell"
    best, cap = cents_label(v.best_price), cents_label(getattr(v, "cap", None))
    code = v.skip
    if code == "unavailable":
        said = (v.detail or "").lower()
        if "too many requests" in said:
            return f"{n} is busy right now. Try again in a few seconds."
        if "maintenance" in said or "(503)" in said:
            return f"{n} is down for maintenance. Try again later."
        return f"{n} didn't answer just now. Try again in a few seconds."
    if code == "no_offers":
        return f"Nobody is {'selling' if buy else 'buying'} {side} on {n} right now."
    if code == "above_max_price" and best and limit is not None:
        return f"{n}'s cheapest offer is {best}, above your {cents_label(limit)} limit."
    if code == "below_min_price" and best and limit is not None:
        return f"{n}'s best bid is {best}, below your {cents_label(limit)} minimum."
    if code == "not_enough_size" and cap:
        if buy:
            return f"{n} doesn't have {_size(v.size)} {side} for sale at {cap} or less."
        return f"{n} isn't buying {_size(v.size)} {side} at {cap} or more."
    return SKIP.get(code, "").format(n=n, side=side, size=_size(v.size)) or f"{n} can't take this order."


def _venue_row(v: Any, chosen: str | None, limit: float | None = None) -> dict[str, Any]:
    return {
        "venue": v.venue,
        "venue_name": VENUE_NAMES.get(v.venue, v.venue),
        "market": v.market,
        "ok": v.ok,
        "cheaper": v.venue == chosen,
        "skip": v.skip,
        "skip_reason": skip_sentence(v, limit),
        "skip_line": skip_sentence(v, limit),  # the same sentence (Every market's name for it)
        # The venue didn't answer (busy, down, a book too old): its price isn't known. Not "can't fill".
        "unavailable": v.skip in UNKNOWN_SKIPS,
        "price": v.best_price,
        "price_label": cents_label(v.best_price),
        "chance_label": chance_label(v.best_price),
        "avg_price": v.avg_price,
        "avg_price_label": cents_label(v.avg_price),
        "limit_price": v.limit_price,
        "fees": v.fees,
        "fillable": None if v.size_at_limit is None else math.floor(v.size_at_limit + 1e-9),
        "total_cost": v.all_in,
        "total_cost_per_contract": v.all_in_per_contract,
    }


def verdict_line(why: Any) -> str:
    """The SDK's comparison as one sentence, from its own numbers."""
    chosen = why.chosen
    size = f"{why.size:,g}"
    unknown = [v.venue for v in why.venues if v.skip in UNKNOWN_SKIPS]
    if unknown:
        return busy_sentence(unknown)
    if chosen is None:
        return "No trade: neither venue can fill this order right now."
    name = VENUE_NAMES.get(chosen.venue, chosen.venue)
    other = next((v for v in why.venues if v.venue != chosen.venue and v.ok), None)
    total = money_label(chosen.all_in)
    if other is None:
        return f"Only {name} can fill {size} contracts: {total}, fees included."
    if why.reason_code == "tie_more_size":
        return f"Same price on both ({total} for {size}, fees included). {name} has more for sale, so it goes there."
    if why.reason_code == "tie_first_listed":
        return f"Same price on both ({total} for {size}, fees included), so it goes to {name}."
    by = "less than 1¢" if why.saving is not None and why.saving < 0.005 else money_label(why.saving)
    return f"{name} is {by} cheaper for {size} contracts, fees included: {total} vs {money_label(other.all_in)}."


def compare_view(m: Match, why: Any) -> dict[str, Any]:
    """One order compared on both venues (``uselayer.best.BestVenue``), with labels for the app.

    Every number is the SDK's; this only names and formats them.
    """
    # A venue that didn't answer leaves the comparison open: the other isn't "cheaper" or "the only one".
    unknown = [VENUE_NAMES.get(v.venue, v.venue) for v in why.venues if v.skip in UNKNOWN_SKIPS]
    chosen = None if unknown else why.venue
    return {
        "action": why.action,
        "side": why.side,
        "size": why.size,
        "max_price": why.limit,
        "pair": pair_view(m),
        "venues": [_venue_row(v, chosen, why.limit) for v in why.venues],
        "cheaper": chosen,
        "cheaper_name": VENUE_NAMES.get(chosen, chosen) if chosen else None,
        "unavailable": unknown,  # venue names that didn't answer: compare again, don't trade
        "saving": None if unknown else why.saving,
        "saving_label": None if unknown else money_label(why.saving),
        "verdict": verdict_line(why),
        "as_of": why.as_of.isoformat(),
    }
