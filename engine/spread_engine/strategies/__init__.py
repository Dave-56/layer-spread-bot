"""Strategies: where your bot's own logic goes.

Each file in this folder is one strategy, named the way traders talk ("Back the favorite", "Longshot
under 20¢"). A file has:

- ``NAME``: what the picker shows.
- ``CATEGORY``: the group it's listed under (:data:`CATEGORIES`).
- ``DESCRIPTION``: one line on what it buys.
- ``decide(matches, client)``: returns a :class:`Signal` (the trade you want), a :class:`NoTrade` (no
  trade, with one plain sentence why) or None (no trade).
- Optional ``LAYER_CATEGORIES``: which of Layer's categories to ask for (e.g. ``("crypto",)``). Left
  out, the strategy gets every matched market for the search on screen.

The app's strategy picker lists every file here, so adding a file adds a choice, without a restart.
Start from ``my_strategy.py``, or add a file from the app ("Add your strategy"), which saves it here.

The bot doesn't judge your strategy. It takes the Signal and does Job 1: it prices that exact order
on both venues, after fees and depth, and sends it to the cheaper one (paper unless BOT_MODE=live).
"""

from __future__ import annotations

import contextvars
import importlib
import pkgutil
import re
import sys
import traceback
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from uselayer import Client, Match, Prices, VenueError

SPORTS = "Sports"
CRYPTO = "Crypto"
NEWS = "News, politics & economics"
YOURS = "Your own"
CATEGORIES = (SPORTS, CRYPTO, NEWS, YOURS)  # the order the picker groups them in

FOLDER = Path(__file__).resolve().parent
# The starter file: where your own strategy begins. It never trades, so the picker doesn't list it;
# the app offers it as a download instead (GET /strategies/starter).
STARTER = "my_strategy"


@dataclass(frozen=True)
class Signal:
    """The trade your strategy wants."""

    match: Match  # the market (one of the matches you were given)
    side: str  # "yes" or "no": the outcome both venues' markets name
    size: int  # contracts
    max_price: float | None = None  # never pay more than this a contract, in dollars (None: the SDK's price collar)
    why: str = ""  # one line, shown in the app: why your strategy picked this


@dataclass(frozen=True)
class NoTrade:
    """No trade, and one plain sentence why (shown in the app)."""

    why: str


Decide = Callable[[list[Match], Client], "Signal | NoTrade | None"]


# ---- reading a match ----------------------------------------------------------------------------


def _time(t: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None
    except ValueError:
        return None


def starts_at(m: Match) -> datetime | None:
    """When the event starts (the game's kickoff), as the venues say, or None."""
    return _time(m.kalshi.event_time) or _time(m.polymarket_us.event_time)


def closes_at(m: Match) -> datetime | None:
    """When the first of the two markets stops trading (usually when the result is due), or None.

    Venues set their own close: Kalshi often closes at the result, Polymarket US days later.
    """
    closes = [t for t in (_time(m.kalshi.close_time), _time(m.polymarket_us.close_time)) if t]
    return min(closes) if closes else None


def hours_until(t: datetime | None, now: datetime | None = None) -> float | None:
    if t is None:
        return None
    return (t - (now or datetime.now(UTC))).total_seconds() / 3600


def upcoming(m: Match) -> bool:
    """The event hasn't started yet (or has no start time)."""
    t = starts_at(m)
    return t is None or t > datetime.now(UTC)


def game_winner(m: Match) -> bool:
    """A "who wins this game" market (Kalshi's ``…GAME`` series), not a spread, total or player prop."""
    series = (m.kalshi.series or m.kalshi.market_id.split("-")[0]).upper()
    return series.endswith("GAME")


def soonest(matches: Iterable[Match]) -> list[Match]:
    """Matches in the order their events start, soonest first (no start time: last)."""
    far = datetime.max.replace(tzinfo=UTC)
    return sorted(matches, key=lambda m: starts_at(m) or far)


def outcome(m: Match) -> str:
    return m.kalshi.outcome or m.polymarket_us.outcome or m.kalshi.question or m.kalshi.market_id


def event(m: Match) -> str:
    return m.kalshi.event or m.polymarket_us.event or m.kalshi.market_id


def price_words(p: float) -> str:
    """A price as cents and as the chance the market gives it: ``54¢ (54%)``."""
    c = round(p * 100, 1)
    n = f"{c:g}"
    return f"{n}¢ ({n}%)"


# ---- prices ---------------------------------------------------------------------------------------

# A YES ask at 1¢ or 99¢ is a book with no real price left: the outcome is all but decided, or
# nobody is quoting it. priced() skips it so a comparison shows two real prices side by side.
DEAD_LOW, DEAD_HIGH = 0.01, 0.99


# Venues that didn't answer while a strategy read them (busy, down): "no trade" isn't known then.
_failed: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar("spread_read_failures", default=None)
DIDNT_ANSWER = frozenset({"rate_limited", "venue_unavailable", "venue_maintenance"})


@contextmanager
def read_failures() -> Iterator[set[str]]:
    """Collect the venues that didn't answer a read in this block (e.g. ``{"polymarket_us"}``)."""
    failed: set[str] = set()
    token = _failed.set(failed)
    try:
        yield failed
    finally:
        _failed.reset(token)


def _note(e: VenueError) -> None:
    failed = _failed.get()
    if failed is not None and e.code in DIDNT_ANSWER and e.venue:
        failed.add(e.venue)


def open_on_both(m: Match, client: Client) -> bool:
    """Both venues say the market is open for trading (``client.market(...).open``)."""
    try:
        return all(client.market(x.market_id, venue=x.venue).open for x in (m.kalshi, m.polymarket_us))
    except VenueError as e:
        _note(e)
        return False


def live_price(ask: float | None) -> bool:
    """A YES ask someone is really quoting: on offer, and above 1¢ and below 99¢."""
    return ask is not None and DEAD_LOW < ask < DEAD_HIGH


def priced(
    matches: Iterable[Match], client: Client, *, limit: int = 10, rules_differ_ok: bool = False
) -> Iterator[tuple[Match, Prices]]:
    """Upcoming matches open on both venues, with both venues' best prices (``client.prices``), in order.

    Skips a match that has started, a market either venue says isn't open, and a venue with no real
    YES price (none on offer, or 1¢/99¢). Reads at most ``limit`` matches' prices (each read is both
    venues' books), one at a time and only when you ask for the next: Polymarket US allows only a
    few book reads every 10 seconds (see ``reads.py``), so a strategy that finds its trade in the
    first game reads one. A match Layer flagged as worded differently (``m.caveats``) is skipped
    unless ``rules_differ_ok``: then it's yielded too, and the app shows its warning if you pick it.
    """
    chosen: list[Match] = []
    for m in matches:
        if len(chosen) == limit:
            break
        if (m.caveats and not rules_differ_ok) or not upcoming(m):
            continue
        if open_on_both(m, client):
            chosen.append(m)
    for m in chosen:
        try:
            p = client.prices(m)
        except VenueError as e:
            _note(e)
            continue
        if live_price(p.a.yes_ask) and live_price(p.b.yes_ask):
            yield m, p


def cheapest(p: Prices, side: str = "yes") -> float | None:
    """The lower of the two venues' best asks for ``side`` ("yes" or "no"), or None if neither sells it."""
    asks = [getattr(x, f"{side}_ask") for x in (p.a, p.b)]
    found = [a for a in asks if a is not None]
    return min(found) if found else None


def cheapest_yes(p: Prices) -> float:
    """The lower of the two venues' best YES asks."""
    return cheapest(p, "yes")  # type: ignore[return-value]


# ---- the folder -----------------------------------------------------------------------------------


def _load(name: str) -> ModuleType:
    importlib.invalidate_caches()  # a file added since the last look is found
    full = f"{__name__}.{name}"
    if full in sys.modules:
        return importlib.reload(sys.modules[full])  # pick up edits without a restart
    return importlib.import_module(full)


def _problem(e: BaseException) -> str:
    """Why a strategy file didn't load, in one line (the file's own line number when there is one)."""
    if isinstance(e, SyntaxError):
        return f"Line {e.lineno}: {e.msg}."
    frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.startswith(str(FOLDER))]
    where = f"Line {frames[-1].lineno}: " if frames else ""
    return f"{where}{type(e).__name__}: {e}"


def _entries() -> list[tuple[str, ModuleType | None, str | None]]:
    """Every strategy file: ``(id, module or None, why it didn't load or None)``."""
    out: list[tuple[str, ModuleType | None, str | None]] = []
    for info in sorted(pkgutil.iter_modules([str(FOLDER)]), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        try:
            mod = _load(info.name)
        except Exception as e:  # noqa: BLE001  (a broken file is listed with why, never breaks the list)
            out.append((info.name, None, _problem(e)))
            continue
        if not callable(getattr(mod, "decide", None)):
            out.append((info.name, None, "It has no decide(matches, client) function."))
            continue
        out.append((info.name, mod, None))
    return out


def _row(sid: str, m: ModuleType | None, error: str | None) -> dict[str, Any]:
    category = getattr(m, "CATEGORY", YOURS)
    return {
        "id": sid,
        "name": getattr(m, "NAME", sid),
        "category": category if category in CATEGORIES else YOURS,
        "description": getattr(m, "DESCRIPTION", ""),
        "example": bool(getattr(m, "EXAMPLE", False)),
        "order": getattr(m, "ORDER", 50),
        "error": error,
    }


def available() -> list[dict[str, Any]]:
    """Every strategy file: ``{"id", "name", "category", "description", "example", "order", "error"}``.

    Grouped in :data:`CATEGORIES` order, then by ``ORDER``. A file that doesn't load is listed with
    ``error`` (one line) so it can be fixed, and can't be run.
    """
    rows = [_row(*e) for e in _entries() if e[0] != STARTER]
    return sorted(rows, key=lambda r: (CATEGORIES.index(r["category"]), r["order"], r["name"]))


def module(strategy_id: str) -> ModuleType:
    for sid, m, error in _entries():
        if sid == strategy_id:
            if m is None:
                raise ValueError(f"{sid}.py didn't load. {error}")
            return m
    raise KeyError(f"No strategy named {strategy_id!r} in engine/spread_engine/strategies/.")


def get(strategy_id: str) -> Decide:
    return module(strategy_id).decide  # type: ignore[no-any-return]


def starter() -> str:
    """The starter file's text, to download and edit."""
    return (FOLDER / f"{STARTER}.py").read_text()


# ---- adding your own file -------------------------------------------------------------------------

FILE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}\.py$")
MAX_BYTES = 200_000


class BadStrategy(ValueError):
    """A strategy file that can't be added, with one plain sentence why."""


def add(filename: str, code: str, *, replace: bool = False) -> dict[str, Any]:
    """Save ``code`` as ``strategies/<filename>`` and check it loads and has ``decide()``.

    This runs your own code on your own machine, the same as dropping the file in the folder: it is
    imported to check it. If it doesn't load, the file is removed again (or the old one put back) and
    :class:`BadStrategy` says why. Example files can't be replaced.
    """
    name = filename.strip().lower()
    if not FILE_NAME.match(name):
        raise BadStrategy(
            "Name the file in lowercase letters, numbers and underscores, ending in .py (e.g. momentum.py)."
        )
    if len(code.encode()) > MAX_BYTES:
        raise BadStrategy("That file is over 200 KB. A strategy file is usually a few KB.")
    path = FOLDER / name
    sid = name[:-3]
    old = path.read_text() if path.exists() else None
    if sid == STARTER:
        raise BadStrategy(f"{name} is the starter file. Save yours under another name, e.g. momentum.py.")
    if old is not None:
        existing = next((r for r in available() if r["id"] == sid), None)
        if existing and existing["example"]:
            raise BadStrategy(f"{name} is one of the examples. Pick another name.")
        if not replace:
            raise BadStrategy(f"There's already a {name}. Replace it, or pick another name.")
    path.write_text(code)
    _drop_bytecode(sid)  # a same-second rewrite could otherwise load the old compiled copy
    try:
        m = _load(sid)
        if not callable(getattr(m, "decide", None)):
            raise BadStrategy(f"{name} has no decide(matches, client) function. Start from my_strategy.py.")
    except BadStrategy:
        _undo(path, old, sid)
        raise
    except Exception as e:  # noqa: BLE001
        _undo(path, old, sid)
        raise BadStrategy(f"{name} didn't load. {_problem(e)}") from e
    return _row(sid, m, None)


def _drop_bytecode(sid: str) -> None:
    for pyc in (FOLDER / "__pycache__").glob(f"{sid}.*.pyc"):
        pyc.unlink(missing_ok=True)


def _undo(path: Path, old: str | None, sid: str) -> None:
    _drop_bytecode(sid)
    if old is None:
        path.unlink(missing_ok=True)
        sys.modules.pop(f"{__name__}.{sid}", None)
    else:
        path.write_text(old)
        try:
            _load(sid)
        except Exception:  # noqa: BLE001  (the old file is back as it was, loading or not)
            pass
