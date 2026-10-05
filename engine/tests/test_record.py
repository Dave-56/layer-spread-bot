"""Save prices from the app (/record/*), with a MADE-UP stream in place of the venues (no network)."""

from __future__ import annotations

import importlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from uselayer import Match, VenueError

from tests.test_app import SECRET, local
from tests.test_replay import MATCH, book

KALSHI_ID, PM_ID = MATCH["kalshi"]["market_id"], MATCH["polymarket_us"]["market_id"]


class _Key:
    """Stands in for a venue key: recording never reads it here."""

    @classmethod
    def from_env(cls) -> _Key:
        return cls()


def throwaway_pem() -> str:
    """A fresh RSA key, made for this test only: the SDK client parses the Kalshi key when it's made."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


PEM = throwaway_pem()


def gap_stream(path: Path, on_event: Any) -> None:
    """Both venues' books for two moments, written the way record_stream writes them."""
    lines = [
        book("kalshi", KALSHI_ID, "2026-10-10T12:00:00Z", 0.39, 0.41),
        book("polymarket_us", PM_ID, "2026-10-10T12:00:00Z", 0.58, 0.60),
        book("kalshi", KALSHI_ID, "2026-10-10T12:00:05Z", 0.48, 0.50),
    ]
    with Path(path).open("a") as f:
        for e in lines:
            f.write(json.dumps(e) + "\n")
            on_event(e)


@pytest.fixture()
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # noqa: ANN201
    monkeypatch.setenv("LAYER_API_KEY", SECRET)
    monkeypatch.setenv("KALSHI_KEY_ID", "kalshi-id")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", PEM)
    monkeypatch.setenv("POLYMARKET_US_KEY_ID", "pm-id")
    monkeypatch.setenv("POLYMARKET_US_SECRET_KEY", "pm-secret-do-not-echo")
    monkeypatch.setenv("BOT_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.delenv("BOT_MODE", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
    from spread_engine import app as module
    from spread_engine import recorder, replay

    monkeypatch.setattr(replay, "RECORDINGS", tmp_path / "recordings")
    monkeypatch.setattr(recorder, "Kalshi", _Key)
    monkeypatch.setattr(recorder, "PolymarketUS", _Key)
    monkeypatch.setattr(recorder, "_current", None)
    monkeypatch.setattr(replay, "layer_match", lambda c, t: Match.model_validate(MATCH))
    return importlib.reload(module)


def wait_for(c: Any, state: str) -> dict[str, Any]:
    for _ in range(100):
        r = c.get("/record/status").json()["recording"]
        if r and r["state"] == state:
            return r
        time.sleep(0.02)
    raise AssertionError(f"the recording never reached {state}: {r}")


def test_records_both_legs_then_replays_the_file(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from spread_engine import recorder

    seen: dict[str, Any] = {}

    def fake(markets, path, *, duration_s, stop, on_event, **kw):  # noqa: ANN001, ANN202
        seen.update(markets=markets, duration_s=duration_s)
        gap_stream(path, on_event)

    monkeypatch.setattr(recorder, "record_stream", fake)
    c = local(engine.app)
    r = c.post("/record/start", json={"match_id": KALSHI_ID, "minutes": 2})
    assert r.status_code == 200, r.text
    done = wait_for(c, "done")
    assert seen == {"markets": [KALSHI_ID, PM_ID], "duration_s": 120}
    assert done["events"] == 3 and done["error"] is None
    assert done["file"].startswith(f"{KALSHI_ID}-") and done["file"].endswith("Z.jsonl")
    path = Path(done["path"])
    assert path.with_suffix(".match.json").exists()  # the match is saved beside it, as npm run record does
    # The new file is in Saved prices, with its match, and replays.
    files = c.get("/replay/files").json()["files"]
    assert [f["path"] for f in files] == [str(path)] and files[0]["match"]["id"] == KALSHI_ID
    out = c.post("/replay/run", json={"path": str(path)})
    assert out.status_code == 200, out.text
    assert out.json()["moments"] >= 1


def test_one_at_a_time_and_stop_keeps_what_was_written(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from spread_engine import recorder

    writing = threading.Event()

    def until_stopped(markets, path, *, stop, on_event, **kw):  # noqa: ANN001, ANN202
        gap_stream(path, on_event)
        writing.set()
        stop.wait(5)

    monkeypatch.setattr(recorder, "record_stream", until_stopped)
    c = local(engine.app)
    assert c.post("/record/start", json={"match_id": KALSHI_ID}).status_code == 200
    assert writing.wait(2)
    live = c.get("/record/status").json()["recording"]
    assert live["state"] == "recording" and live["minutes"] == 30  # 30 min unless asked
    assert 0 < live["seconds_left"] <= 1800 and live["events"] == 3
    again = c.post("/record/start", json={"match_id": KALSHI_ID})
    assert again.status_code == 409 and again.json()["detail"] == recorder.ALREADY
    assert c.post("/record/stop", json={}).status_code == 200
    stopped = wait_for(c, "stopped")
    assert Path(stopped["path"]).exists() and stopped["seconds_left"] == 0
    # Once it has ended, the next one may start.
    assert c.post("/record/start", json={"match_id": KALSHI_ID}).status_code == 200
    c.post("/record/stop", json={})
    wait_for(c, "stopped")


def test_nothing_saved_leaves_no_file(engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: ANN001
    from spread_engine import recorder

    monkeypatch.setattr(recorder, "record_stream", lambda *a, **kw: None)
    c = local(engine.app)
    c.post("/record/start", json={"match_id": KALSHI_ID, "minutes": 1})
    r = wait_for(c, "failed")
    assert r["error"] == recorder.NOTHING and r["path"] is None
    assert list((tmp_path / "recordings").iterdir()) == []


def test_a_venue_error_is_one_plain_sentence(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from spread_engine import recorder

    def refused(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        raise VenueError("auth_failed", "401 from the stream", venue="polymarket_us", status=401)

    monkeypatch.setattr(recorder, "record_stream", refused)
    c = local(engine.app)
    c.post("/record/start", json={"match_id": KALSHI_ID})
    assert wait_for(c, "failed")["error"] == "Polymarket US didn't accept your key. Check it in .env, then restart."


@pytest.mark.parametrize(
    ("unset", "names"),
    [
        (("LAYER_API_KEY",), "LAYER_API_KEY"),
        (("KALSHI_KEY_ID",), "KALSHI_KEY_ID and KALSHI_PRIVATE_KEY"),
        (("POLYMARKET_US_SECRET_KEY",), "POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY"),
    ],
)
def test_a_missing_key_names_its_env_vars(engine, monkeypatch: pytest.MonkeyPatch, unset: tuple[str, ...], names: str) -> None:  # noqa: ANN001
    for k in unset:
        monkeypatch.delenv(k)
    r = local(engine.app).post("/record/start", json={"match_id": KALSHI_ID})
    assert r.status_code == 400
    assert names in r.json()["detail"] and r.json()["detail"].startswith("Recording needs your ")


def test_no_match_is_one_sentence(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from spread_engine import recorder

    def none(client, ticker):  # noqa: ANN001, ANN202
        raise VenueError("not_found", "no match")

    monkeypatch.setattr(engine.replay, "layer_match", none)
    r = local(engine.app).post("/record/start", json={"match_id": "KXNOPE"})
    assert r.status_code == 404 and r.json()["detail"] == recorder.NO_MATCH


def test_status_never_carries_a_key(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from spread_engine import recorder

    monkeypatch.setattr(recorder, "record_stream", lambda markets, path, *, on_event, **kw: gap_stream(path, on_event))
    c = local(engine.app)
    assert c.get("/record/status").json() == {"recording": None}
    c.post("/record/start", json={"match_id": KALSHI_ID})
    body = json.dumps(wait_for(c, "done"))
    for secret in (SECRET, "pm-secret-do-not-echo", PEM.splitlines()[1], "kalshi-id"):
        assert secret not in body


def test_games_on_now_come_first(engine, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    from datetime import UTC, datetime, timedelta

    def at(mid: str, hours: float, kalshi_hours: float | None = None) -> Match:
        t = lambda h: (datetime.now(UTC) + timedelta(hours=h)).isoformat()  # noqa: E731
        d = json.loads(json.dumps(MATCH))
        d["kalshi"].update(market_id=mid, event_time=t(hours if kalshi_hours is None else kalshi_hours), close_time=None)
        d["polymarket_us"].update(market_id=f"aec-{mid.lower()}", event_time=t(hours), close_time=None)
        return Match.model_validate(d)

    later, soon, on = at("KXLATER", 5), at("KXSOON", 1), at("KXON", -1)
    # Kalshi's event time is often the expected end; Polymarket US's is the kickoff. Kicked off 20 min ago:
    kicked_off = at("KXKICKOFF", -1 / 3, kalshi_hours=2.7)
    monkeypatch.setattr(engine, "_list", lambda *a, **kw: ([later, soon, kicked_off, on], 0))
    ms = local(engine.app).get("/record/games").json()["matches"]
    assert [(m["id"], m["on_now"]) for m in ms] == [
        ("KXON", True), ("KXKICKOFF", True), ("KXSOON", False), ("KXLATER", False),
    ]
