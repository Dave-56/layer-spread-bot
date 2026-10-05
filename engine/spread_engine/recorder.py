"""Save prices from the app: one matched pair's books, recorded in the background for Replay.

The same recording ``npm run record`` (scripts/record.py) makes: the SDK's ``record_stream`` writes
every book change and trade from both venues to ``recordings/<ticker>-<UTC time>.jsonl``, with the
match saved next to it (``.match.json``). One recording runs at a time; the app polls its progress
and can stop it early. What's written before a stop is kept.

Recording reads each venue's live stream with your own keys (nothing is traded). The keys stay in
this process: a recording's view never includes them.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from uselayer import Kalshi, Match, PolymarketUS, VenueError, record_stream

from . import config, replay
from .views import match_view, plain_error

ALREADY = "A recording is already running. Stop it, or wait for it to end."
NO_MATCH = "Layer has no Polymarket US match for this game."
NOTHING = "Nothing was saved: neither venue sent a price while recording."
MAX_MINUTES = 240


def missing_key() -> str | None:
    """Which key recording still needs, as one sentence naming the env vars, or None."""
    keys = config.load().keys
    if not keys["layer"]:
        return "Recording needs your Layer key: set LAYER_API_KEY."
    if not keys["kalshi"]:
        return "Recording needs your Kalshi key: set KALSHI_KEY_ID and KALSHI_PRIVATE_KEY (or KALSHI_PRIVATE_KEY_PATH)."
    if not keys["polymarket_us"]:
        return "Recording needs your Polymarket US key: set POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY."
    return None


def new_file(m: Match, now: datetime | None = None) -> Path:
    """``recordings/<ticker>-<UTC time>.jsonl`` for a new recording, with the match saved beside it."""
    replay.RECORDINGS.mkdir(exist_ok=True)
    path = replay.RECORDINGS / f"{m.kalshi.market_id}-{(now or datetime.now(UTC)):%Y%m%dT%H%M%SZ}.jsonl"
    replay.sidecar(path).write_text(json.dumps(m.to_dict(), indent=1))
    return path


def markets(m: Match) -> list[str]:
    # The twin's own id: "<slug>:short" records the short side's book under that id, which is what
    # quote() looks for on replay.
    return [m.kalshi.market_id, m.polymarket_us.market_id]


class Recording:
    """One recording, run on its own thread. ``view()`` is what the app shows while it runs and after."""

    def __init__(self, m: Match, minutes: float, *, record: Callable[..., Any] | None = None) -> None:
        self.match = m
        self.minutes = minutes
        self.record = record or record_stream
        self.started_at = datetime.now(UTC)
        self.ends_at = self.started_at + timedelta(minutes=minutes)
        self.path = new_file(m, self.started_at)
        self.events = 0
        self.state = "recording"  # then "done", "stopped" or "failed"
        self.error: str | None = None
        self.stop_flag = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self, kalshi: Kalshi, polymarket_us: PolymarketUS) -> Recording:
        self.thread = threading.Thread(target=self._run, args=(kalshi, polymarket_us), daemon=True, name="record")
        self.thread.start()
        return self

    @property
    def running(self) -> bool:
        return self.state == "recording"

    def stop(self) -> None:
        self.stop_flag.set()

    def _count(self, _e: Any) -> None:
        self.events += 1

    def _run(self, kalshi: Kalshi, polymarket_us: PolymarketUS) -> None:
        try:
            self.record(
                markets(self.match),
                self.path,
                kalshi=kalshi,
                polymarket_us=polymarket_us,
                duration_s=self.minutes * 60,
                stop=self.stop_flag,
                on_event=self._count,
            )
            state, error = ("stopped" if self.stop_flag.is_set() else "done"), None
        except VenueError as e:
            state, error = "failed", plain_error(e)
        except Exception as e:  # noqa: BLE001  (a thread's error would otherwise vanish)
            state, error = "failed", f"The recording stopped: {e}"
        if self.events == 0:
            # An empty file can't be replayed: leave nothing behind, and say why.
            self.path.unlink(missing_ok=True)
            replay.sidecar(self.path).unlink(missing_ok=True)
            if error is None:
                state, error = "failed", NOTHING
        self.error = error
        self.state = state

    def view(self) -> dict[str, Any]:
        left = max(0.0, (self.ends_at - datetime.now(UTC)).total_seconds()) if self.running else 0.0
        return {
            "state": self.state,
            "match": match_view(self.match),
            "minutes": self.minutes,
            "started_at": self.started_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "seconds_left": round(left),
            "events": self.events,
            "path": str(self.path) if self.events or self.running else None,
            "file": self.path.name if self.events or self.running else None,
            "error": self.error,
        }


class Busy(Exception):
    """A recording is already running."""


_current: Recording | None = None
_lock = threading.Lock()


def start(m: Match, minutes: float, *, record: Callable[..., Any] | None = None) -> Recording:
    """Start recording ``m`` for ``minutes``. Raises :class:`Busy` if one is running, VenueError for a bad key."""
    global _current
    with _lock:
        if _current is not None and _current.running:
            raise Busy(ALREADY)
        kalshi, pm = Kalshi.from_env(), PolymarketUS.from_env()
        _current = Recording(m, minutes, record=record).start(kalshi, pm)
        return _current


def current() -> Recording | None:
    return _current


def stop() -> Recording | None:
    if _current is not None:
        _current.stop()
    return _current
