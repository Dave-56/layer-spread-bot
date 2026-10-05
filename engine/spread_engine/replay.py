"""Job 2, replayed: run a recorded pair through the same scan, moment by moment, in backtest mode.

Any file the SDK's ``import_events`` reads works (its own JSON lines, CSV, Parquet...), from
``recordings/`` or any folder you pick. ``npm run record -- <kalshi ticker>`` (engine/scripts/record.py)
records one with ``record_stream`` and saves the match next to it (``.match.json``). For a file without
one, the pair is found with Layer's matching: the file's Kalshi ticker and its Polymarket US twin.

Each time either leg's book changes (at most once a second of recorded time), the pair goes through
the same gates as the live scan (:func:`spread_engine.funnel.judge`), priced by the SDK's ``quote()``
against the books as they stood then.

A file whose sizes are placeholders (``"sizes_unknown": true`` in ``<name>.meta.json``) is priced at an
assumed size, the one asked for, at the top price of both books: ``size_note`` says so with every
result. A file from before the SDK's first fee schedule for a venue can't be priced at all
(:class:`CannotPrice`, one plain sentence).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from uselayer import Client, Match, VenueError, import_events, reconstruct_book
from uselayer.books import Book, BookLevelChange, Level
from uselayer.events import StreamGap
from uselayer.venue_rules import history

from .config import ROOT
from .funnel import GATES, ScanSettings, judge
from .views import VENUE_NAMES, match_view

RECORDINGS = ROOT / "recordings"
STEP = timedelta(seconds=1)
KINDS = (".jsonl", ".ndjson", ".csv", ".parquet")

Lookup = Callable[[str], Match | None]  # a Kalshi ticker → its matched pair, or None


class CannotPrice(Exception):
    """The file can't be priced at all, with one plain sentence why."""


def sidecar(path: Path) -> Path:
    return path.with_suffix(".match.json")


def meta(path: Path) -> dict[str, Any]:
    """An optional ``<name>.meta.json`` beside a file: ``settles_at`` (when the money comes back), and
    whether its book sizes are real depth (``sizes_unknown: true``, or a note saying they're placeholders)."""
    p = path.with_suffix(".meta.json")
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def sizes_unknown(m: dict[str, Any]) -> bool:
    if m.get("sizes_unknown") or m.get("placeholder_sizes"):
        return True
    text = " ".join(str(m.get(k, "")) for k in ("sizes", "size", "note", "notes")).lower()
    return "placeholder" in text


def size_note(n: int) -> str:
    """What a replay of a file without real sizes assumes, in words."""
    contracts = "1 contract" if n == 1 else f"{n:,} contracts"
    return f"Size unknown: assumes {contracts} at the top price on both venues."


def assume_size(events: list[Any], legs: set[tuple[str, str]], n: int) -> list[Any]:
    """A file whose sizes are placeholders, as books with only the top price on each side, ``n`` at each.

    The prices are the file's; the size is the assumption. Level changes are applied to the last
    full book first (the SDK's ``reconstruct_book``); a gap clears the book until the next full one.
    """
    out: list[Any] = []
    current: dict[tuple[str, str], Book] = {}
    for e in sorted(events, key=lambda e: e.as_of):
        key = (getattr(e, "venue", None), getattr(e, "market", None))
        if key not in legs:
            out.append(e)
            continue
        if isinstance(e, StreamGap):
            current.pop(key, None)  # type: ignore[arg-type]
            out.append(e)
            continue
        if isinstance(e, Book):
            book: Book | None = e
        elif isinstance(e, BookLevelChange):
            last = current.get(key)  # type: ignore[arg-type]
            book = reconstruct_book([last, e]) if last is not None else None
        else:
            out.append(e)
            continue
        if book is None:
            continue
        current[key] = book  # type: ignore[index]
        out.append(
            book.model_copy(
                update={
                    "bids": tuple(Level(price=lv.price, size=n) for lv in book.bids[:1]),
                    "asks": tuple(Level(price=lv.price, size=n) for lv in book.asks[:1]),
                }
            )
        )
    return out


def no_rules_sentence(e: VenueError) -> str:
    """Why a file from before a venue's first fee schedule in the SDK can't be priced, in one sentence."""
    venue = e.venue or ""
    name = VENUE_NAMES.get(venue, venue or "a venue")
    try:
        first = history(venue)[0].effective_from
        since = f"{first:%b} {first.day}, {first.year}"
    except (IndexError, VenueError):
        return f"Can't replay this file: the SDK doesn't have {name}'s fees for the time it was recorded yet."
    return f"Can't replay this file: it's from before {since}, and the SDK doesn't have {name}'s fees from before then yet."


def _parse(t: str | None) -> datetime | None:
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def payout_at(m: Match) -> datetime | None:
    """When the money is expected back: the later event time + 6 h, never past the later close.

    The rule ``client.profit()`` uses; a backtest has no venue times, so ``quote()`` is given it.
    """
    events = [t for t in (_parse(m.kalshi.event_time), _parse(m.polymarket_us.event_time)) if t]
    closes = [t for t in (_parse(m.kalshi.close_time), _parse(m.polymarket_us.close_time)) if t]
    if not events and not closes:
        return None
    at = max(events) + timedelta(hours=6) if events else max(closes)
    return min(at, max(closes)) if closes else at


def _load(path: Path) -> list[Any]:
    # strict=False: a recording with a gap or an odd tick still replays; gaps clear that book.
    return list(import_events(path, strict=False).events)


def _summary(path: Path) -> dict[str, Any]:
    markets: dict[str, set[str]] = {}
    times: list[datetime] = []
    depth = 0
    for e in _load(path):
        markets.setdefault(e.venue, set()).add(e.market)
        times.append(e.as_of)
        if isinstance(e, Book):
            depth = max(depth, len(e.bids), len(e.asks))
    return {
        "events": len(times),
        "from": min(times).isoformat() if times else None,
        "to": max(times).isoformat() if times else None,
        "markets": {v: sorted(s) for v, s in markets.items()},
        "top_of_book_only": depth <= 1,
    }


_cache: dict[tuple[str, float, int], dict[str, Any]] = {}


def _summary_cached(p: Path) -> dict[str, Any]:
    st = p.stat()
    key = (str(p), st.st_mtime, st.st_size)
    if key not in _cache:
        _cache[key] = _summary(p)
    return _cache[key]


def folders(extra: str | None = None) -> list[Path]:
    out = [RECORDINGS]
    if extra:
        p = Path(extra).expanduser()
        if p.is_dir() and p.resolve() != RECORDINGS.resolve():
            out.append(p)
    return out


def list_files(extra: str | None = None) -> list[dict[str, Any]]:
    """Every replayable file in recordings/ (and ``extra``, a folder you pick), newest first."""
    paths = [p for d in folders(extra) if d.is_dir() for p in d.iterdir() if p.suffix in KINDS and p.is_file()]
    out = []
    for p in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            s = _summary_cached(p)
        except Exception as e:  # noqa: BLE001  (a file the SDK can't read is listed with why)
            out.append({"path": str(p), "file": p.name, "error": str(e)})
            continue
        m = _saved_match(p)
        no_depth = sizes_unknown(meta(p))
        out.append({
            "path": str(p),
            "file": p.name,
            "bytes": p.stat().st_size,
            **s,
            "top_of_book_only": s["top_of_book_only"] or no_depth,
            "size_unknown": no_depth,
            "match": match_view(m) if m else None,
        })
    return out


def _saved_match(path: Path) -> Match | None:
    sc = sidecar(path)
    return Match.model_validate(json.loads(sc.read_text())) if sc.exists() else None


def layer_match(client: Client, ticker: str) -> Match:
    """A Kalshi ticker's Polymarket US twin, from Layer's matching (the SDK's only hosted call)."""
    d = client.match(ticker, venue="kalshi", with_="polymarket_us")
    keep = {k: d.get(k) for k in ("confidence", "basis", "caveats", "tier")}
    return Match.model_validate({**keep, "kalshi": d["source_market"], "polymarket_us": d["matched_market"]})


def find_pair(path: Path, markets: dict[str, list[str]], lookup: Lookup | None) -> Match:
    """The recorded pair: the saved match, else the first Kalshi ticker whose twin is in the file."""
    m = _saved_match(path)
    if m is not None:
        return m
    pm = set(markets.get("polymarket_us", []))
    for ticker in markets.get("kalshi", []):
        found = lookup(ticker) if lookup else None
        if found is not None and found.polymarket_us.market_id in pm:
            return found
    raise LookupError(
        f"{path.name} has no Kalshi market and its matched Polymarket US twin together. "
        "Record both with: npm run record -- <kalshi ticker>"
    )


class _At:
    """Quotes against the replay's books, with the payout time a backtest can't read from the venues."""

    def __init__(self, client: Client, settles_at: datetime | None) -> None:
        self.c, self.settles_at = client, settles_at
        self.error: VenueError | None = None

    def quote(self, pair: Any, *, size: int | None = None, min_edge: float = 0.0) -> Any:
        try:
            return self.c.quote(pair, size=size, min_edge=min_edge, settles_at=self.settles_at)
        except VenueError as e:
            self.error = e
            raise


def resolve(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = RECORDINGS / p.name  # a bare name means a file in recordings/
    if p.suffix not in KINDS or not p.is_file():
        raise FileNotFoundError(f"No replayable file at {path} ({', '.join(KINDS)}).")
    return p


def replay(path: str, s: ScanSettings, *, lookup: Lookup | None = None) -> dict[str, Any]:
    """Replay one file through the scan."""
    p = resolve(path)
    evs = _load(p)
    summary = _summary_cached(p)
    m = find_pair(p, summary["markets"], lookup)
    legs = {("kalshi", m.kalshi.market_id), ("polymarket_us", m.polymarket_us.market_id)}
    info = meta(p)
    settles_at = _parse(info.get("settles_at")) or payout_at(m)
    no_depth = sizes_unknown(info)
    if no_depth:
        # The file's sizes aren't real depth. Price an assumed size (the one asked for) at the top
        # price of both books, and say so. One contract would be wrong the other way: Kalshi rounds
        # each order's fee up to the cent, so a 0.3¢ fee bills 1¢ and eats a real 1-2¢ gap.
        evs = assume_size(evs, legs, s.size)

    counts = {g: 0 for g in GATES} | {"survivor": 0}
    st: dict[str, Any] = {"last": None, "prev": None, "span_start": None, "priced": False}
    best: dict[str, Any] = {"any": None, "survivor": None, "total": 0.0, "longest": 0.0}

    no_rules: list[VenueError] = []

    def on_book(c: Client, b: Any) -> None:
        if (b.venue, b.market) not in legs:
            return
        if st["last"] is not None and b.as_of - st["last"] < STEP:
            return
        at = _At(c, settles_at)
        row = judge(m, at, s)
        if row["verdict"] == "unpriced" and not st["priced"]:
            if at.error is not None and at.error.code == "no_venue_rules":
                no_rules.append(at.error)
            return  # before both legs have a book
        st["priced"] = True
        st["last"] = b.as_of
        row["at"] = b.as_of.isoformat()
        counts[row["verdict"]] += 1
        # How long survivors lasted, in recorded time: a survivor counts until the next moment that isn't one.
        if st["span_start"] is not None:
            best["total"] += (b.as_of - st["prev"]).total_seconds()
            best["longest"] = max(best["longest"], (b.as_of - st["span_start"]).total_seconds())
        if row["verdict"] == "survivor":
            st["span_start"] = st["span_start"] or b.as_of
            if best["survivor"] is None or row["quote"]["net_profit"] > best["survivor"]["quote"]["net_profit"]:
                best["survivor"] = row
        else:
            st["span_start"] = None
        st["prev"] = b.as_of
        q = row["quote"]
        if q and q.get("edge_at_best") is not None:
            if best["any"] is None or q["edge_at_best"] > best["any"]["quote"]["edge_at_best"]:
                best["any"] = row

    Client(mode="backtest", books=evs, store=":memory:", on_alert=lambda e: None).replay(on_book)
    if not st["priced"] and no_rules:
        raise CannotPrice(no_rules_sentence(no_rules[0]))
    return {
        "path": str(p),
        "file": p.name,
        "from": summary["from"],
        "to": summary["to"],
        "top_of_book_only": summary["top_of_book_only"] or no_depth,
        "size_unknown": no_depth,
        "assumed_size": s.size if no_depth else None,
        "size_note": size_note(s.size) if no_depth else None,
        "match": match_view(m),
        "settles_at": settles_at.isoformat() if settles_at else None,
        "moments": sum(counts.values()),
        "counts": counts,
        "best": best["any"],
        "best_survivor": best["survivor"],
        "survivor_seconds": round(best["total"], 1),
        "longest_survivor_s": round(best["longest"], 1),
    }
