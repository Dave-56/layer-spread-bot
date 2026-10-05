"""SDK objects as the plain JSON the web app shows. No math here: every number comes from the SDK."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from uselayer import Match, VenueError

VENUE_NAMES = {"kalshi": "Kalshi", "polymarket_us": "Polymarket US"}


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
    if isinstance(e, VenueError):
        return {"code": e.code, "message": e.message, "hint": getattr(e, "hint", None), "venue": e.venue}
    return {"code": "error", "message": str(e) or type(e).__name__, "hint": None, "venue": None}


# ---- Best venue: the comparison as the app shows it -------------------------------------------

# The SDK's skip codes (uselayer.best), in words: one short clause each, never the SDK's own detail
# text ("The best ask is 0.98, above max_price 0.97."). The app adds the venue's name.
SKIP = {
    "switched_off": "orders here are switched off in this release",
    "no_key": "no key for this venue",
    "not_allowed": "not allowed by your rules",
    "not_found": "market not found",
    "market_closed": "market closed",
    "no_book": "no prices yet",
    "stale_book": "its prices were too old to use; try again in a few seconds",
    "no_offers": "nobody selling",
    "above_max_price": "best price above your max",
    "below_min_price": "best price below your min",
    "not_enough_size": "not enough for sale within your max price",
    "invalid_order": "breaks the market's price step or minimum",
    "not_held": "you don't hold it here",
    "unavailable": "the venue didn't answer; try again",
}


def skip_reason(v: Any, limit: float | None = None) -> str | None:
    """Why a venue was left out, as one plain clause, with the SDK's own numbers where they help."""
    if not v.skip:
        return None
    if v.skip == "above_max_price" and v.best_price is not None and limit is not None:
        return f"best price {cents_label(v.best_price)}, above your max of {cents_label(limit)}"
    if v.skip == "below_min_price" and v.best_price is not None and limit is not None:
        return f"best price {cents_label(v.best_price)}, below your min of {cents_label(limit)}"
    if v.skip == "not_enough_size" and v.cap is not None:
        if v.action == "sell":
            return f"not enough bids at {cents_label(v.cap)} or more"
        return f"not enough for sale at {cents_label(v.cap)} or less"
    return SKIP.get(v.skip, v.skip.replace("_", " "))


def _venue(e: VenueError) -> str:
    return VENUE_NAMES.get(e.venue or "", "A venue")


def price_error(e: VenueError) -> str:
    """Why a pair's prices couldn't be read, in one plain sentence (never the SDK's own text)."""
    v = _venue(e)
    return {
        "no_key": f"{v} needs your key to show its prices.",
        "auth_failed": f"{v} didn't accept your key.",
        "rate_limited": f"{v} asked for fewer requests; scan again in a minute.",
        "venue_unavailable": f"{v} didn't answer.",
        "stale_quote": f"{v}'s prices were too old to use.",
        "not_found": f"{v} doesn't list this market any more.",
        "market_closed": f"{v} has closed this market.",
    }.get(e.code, f"{v}'s prices couldn't be read right now.")


def trade_error(e: VenueError) -> str:
    """Why a paper or live trade sent nothing, in one plain sentence."""
    if e.code == "stale_quote":
        return f"{_venue(e)}'s prices were more than 10 seconds old, so nothing was bought. Try again."
    if e.code == "blocked_by_rule":
        rule = getattr(e, "rule", None)
        if rule == "kill_switch":
            return "The kill switch is on, so nothing was bought."
        if rule == "budget":
            return "This trade would take your account over its limit, so nothing was bought. Reset the paper account, or raise BOT_BUDGET in .env."
        return "Your safety rules in .env blocked this trade, so nothing was bought."
    if e.code == "market_closed":
        return f"{_venue(e)} has closed this market, so nothing was bought."
    return f"{price_error(e)} Nothing was bought."


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


def _venue_row(v: Any, chosen: str | None, limit: float | None = None) -> dict[str, Any]:
    return {
        "venue": v.venue,
        "venue_name": VENUE_NAMES.get(v.venue, v.venue),
        "market": v.market,
        "ok": v.ok,
        "cheaper": v.venue == chosen,
        "skip": v.skip,
        "skip_reason": skip_reason(v, limit),
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
    chosen = why.venue
    return {
        "action": why.action,
        "side": why.side,
        "size": why.size,
        "max_price": why.limit,
        "pair": pair_view(m),
        "venues": [_venue_row(v, chosen, why.limit) for v in why.venues],
        "cheaper": chosen,
        "cheaper_name": VENUE_NAMES.get(chosen, chosen) if chosen else None,
        "saving": why.saving,
        "saving_label": money_label(why.saving),
        "verdict": verdict_line(why),
        "as_of": why.as_of.isoformat(),
    }
