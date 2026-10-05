"""The engine: a small HTTP service on 127.0.0.1 that runs the uselayer SDK with your own keys.

The web app calls it; nothing else should. It answers only requests from this machine.

    GET  /status          mode, which keys are set (yes/no only), SDK version
    GET  /matches         Layer's matched Kalshi ↔ Polymarket US markets (the one hosted call)
    GET  /best/signal     Job 1: run your strategy, then compare its order on both venues
    POST /best/preview    Job 1: compare one order on both venues; sends nothing
    POST /best/buy        Job 1: send it to the cheaper venue (paper unless BOT_MODE=live)
    POST /arb/scan        Job 2: the funnel, streamed as newline-delimited JSON
    POST /arb/trade       Job 2: buy both sides of one survivor (paper unless BOT_MODE=live)
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterator
from typing import Any

import uselayer
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from uselayer import Client, Match, VenueError

from . import config, strategy
from .funnel import ScanSettings, quote_view, scan
from .views import error_view, match_id, match_view

settings = config.load()
app = FastAPI(title="Spread bot engine", docs_url=None, redoc_url=None)

_alerts: deque[dict[str, Any]] = deque(maxlen=50)
_matches: dict[str, Match] = {}  # every match seen, by its Kalshi market id
_client: Client | None = None
_client_error: dict[str, Any] | None = None
_lock = threading.Lock()


def client() -> Client:
    """One SDK client for the engine's life, made on first use."""
    global _client, _client_error
    with _lock:
        if _client is None:
            if settings.store_dir:
                settings.store_dir.mkdir(parents=True, exist_ok=True)
            try:
                _client = Client(
                    mode=settings.mode,  # type: ignore[arg-type]
                    rules={"budget": settings.budget},
                    store=settings.store,
                    # A rule that wants a yes gets a no here: there's no terminal to ask in.
                    on_approval=lambda order, reason: False,
                    on_alert=_alerts.append,
                )
                _client_error = None
            except VenueError as e:
                _client_error = error_view(e)
                raise
        return _client


@app.middleware("http")
async def local_only(request: Request, call_next: Any) -> Any:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return JSONResponse({"error": "This engine answers only this machine."}, status_code=403)
    return await call_next(request)


@app.exception_handler(VenueError)
async def venue_error(_: Request, e: VenueError) -> JSONResponse:
    return JSONResponse({"error": error_view(e)}, status_code=400)


def _remember(ms: list[Match]) -> list[Match]:
    pairs = [m for m in ms if "kalshi" in m.markets() and "polymarket_us" in m.markets()]
    for m in pairs:
        _matches[match_id(m)] = m
    return pairs


def _find(mid: str) -> Match:
    m = _matches.get(mid)
    if m is None:
        raise HTTPException(404, f"Unknown match {mid}. Load matches first.")
    return m


def _list(q: str | None, category: str | None, from_: str | None, to: str | None, limit: int) -> list[Match]:
    ms = client().matches(venue="polymarket_us", q=q or None, category=category or None, from_=from_ or None, to=to or None, limit=limit)
    return _remember(ms)


@app.get("/status")
def status() -> dict[str, Any]:
    try:
        client()
    except VenueError:
        pass
    return {
        "mode": settings.mode,
        "budget": settings.budget,
        "keys": settings.keys,
        "sdk_version": uselayer.__version__,
        "client_error": _client_error,
        "alerts": list(_alerts)[-10:],
    }


@app.get("/matches")
def matches(
    q: str | None = None, category: str | None = None, from_: str | None = None, to: str | None = None, limit: int = 20
) -> dict[str, Any]:
    return {"matches": [match_view(m) for m in _list(q, category, from_, to, limit)]}


class BestBody(BaseModel):
    match_id: str
    side: str = Field(pattern="^(yes|no)$")
    size: int = Field(gt=0, le=100_000)
    max_price: float | None = Field(default=None, gt=0, lt=1)


def _best_view(r: Any) -> dict[str, Any]:
    return r.to_dict()


@app.get("/best/signal")
def best_signal(q: str | None = None, category: str | None = None, limit: int = 50) -> dict[str, Any]:
    ms = _list(q, category, None, None, limit)
    sig = strategy.decide(ms, client())
    if sig is None:
        return {"signal": None, "matches": len(ms), "best": None}
    _matches[match_id(sig.match)] = sig.match
    body = BestBody(match_id=match_id(sig.match), side=sig.side, size=sig.size, max_price=sig.max_price)
    return {
        "signal": {**body.model_dump(), "why": sig.why, "match": match_view(sig.match)},
        "matches": len(ms),
        "best": _preview(body),
    }


def _preview(b: BestBody) -> dict[str, Any]:
    try:
        r = client().preview_best(_find(b.match_id), b.side, b.size, max_price=b.max_price)
        return {"ok": True, **_best_view(r)}
    except VenueError as e:
        return {"ok": False, "error": error_view(e)}


@app.post("/best/preview")
def best_preview(b: BestBody) -> dict[str, Any]:
    return {"match": match_view(_find(b.match_id)), **_preview(b)}


@app.post("/best/buy")
def best_buy(b: BestBody) -> dict[str, Any]:
    r = client().buy_best(_find(b.match_id), b.side, b.size, max_price=b.max_price)
    return {"mode": settings.mode, **_best_view(r)}


class ScanBody(BaseModel):
    q: str | None = None
    category: str | None = None
    from_: str | None = None
    to: str | None = None
    limit: int = Field(default=50, gt=0, le=100)
    size: int = Field(default=100, gt=0, le=100_000)
    min_edge: float = Field(default=0.0, ge=0, lt=1)
    min_return_per_day_pct: float = Field(default=0.0, ge=0)


@app.post("/arb/scan")
def arb_scan(b: ScanBody) -> StreamingResponse:
    ms = _list(b.q, b.category, b.from_, b.to, b.limit)
    s = ScanSettings(size=b.size, min_edge=b.min_edge, min_return_per_day_pct=b.min_return_per_day_pct)

    def lines() -> Iterator[str]:
        for event in scan(ms, client(), s):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"cache-control": "no-store"})


class TradeBody(BaseModel):
    match_id: str
    size: int = Field(gt=0, le=100_000)
    min_edge: float = Field(default=0.01, ge=0, lt=1)


@app.post("/arb/trade")
def arb_trade(b: TradeBody) -> dict[str, Any]:
    t = client().trade(_find(b.match_id), size=b.size, min_edge=b.min_edge)
    d = t.to_dict()
    d["quote"] = quote_view(t.quote)
    return {"mode": settings.mode, **d}
