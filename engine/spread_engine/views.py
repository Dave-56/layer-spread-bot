"""SDK objects as the plain JSON the web app shows. No math here: every number comes from the SDK."""

from __future__ import annotations

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
