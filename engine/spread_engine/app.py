"""The engine: a small HTTP service on 127.0.0.1 that runs the uselayer SDK with your own keys.

The web app calls it; nothing else should. It answers only requests from this machine.

    GET  /status          mode, which keys are set (yes/no only), SDK version
    GET  /paper/account   the bot's fake account: positions, money at risk, budget
    POST /paper/reset     paper mode only: start the fake account over
    GET  /matches         Layer's matched Kalshi ↔ Polymarket US markets (the one hosted call)
    GET  /strategies      the strategy files in strategies/ (yours and the examples), by category
    POST /strategies      add your own strategy file (saved in strategies/, checked that it loads)
    GET  /best/signal     Job 1: run a strategy, then compare its order on both venues
    POST /best/preview    Job 1: compare one order on both venues; sends nothing
    POST /best/buy        Job 1: send it to the cheaper venue (paper unless BOT_MODE=live)
    POST /arb/scan        Job 2: the funnel, streamed as newline-delimited JSON
    POST /arb/trade       Job 2: buy both sides of one survivor (paper unless BOT_MODE=live)
    GET  /replay/files    replayable files in recordings/ (npm run record) and a folder you pick
    POST /replay/run      Job 2 replayed: one file through the same scan, in backtest mode
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import uselayer
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from uselayer import Client, Match, VenueError
from uselayer.guardrails import order_risk

from . import config, replay, strategies
from .funnel import ScanSettings, quote_view, scan
from .strategies import upcoming
from .views import compare_view, error_view, match_id, match_view, over

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
    """A match by its Kalshi market id: one seen before, else its Polymarket US twin from Layer's matching."""
    m = _matches.get(mid)
    if m is None:
        try:
            m = replay.layer_match(client(), mid)
        except (VenueError, KeyError) as e:
            raise HTTPException(404, f"Layer has no Polymarket US match for {mid}. Search for the market first.") from e
        if "kalshi" not in m.markets() or "polymarket_us" not in m.markets():
            raise HTTPException(404, f"Layer has no Polymarket US match for {mid}. Search for the market first.")
        _matches[mid] = m
    return m


def _list_in(
    q: str | None, categories: tuple[str, ...] | None, limit: int, *, upcoming_only: bool = False
) -> tuple[list[Match], int]:
    """``_list`` for each of several Layer categories (``None``: all), up to ``limit`` each."""
    if not categories:
        return _list(q, None, None, None, limit, upcoming_only=upcoming_only)
    out: list[Match] = []
    skipped = 0
    for c in categories:
        ms, n = _list(q, c, None, None, limit, upcoming_only=upcoming_only)
        out += ms
        skipped += n
    return out, skipped


def _list(
    q: str | None, category: str | None, from_: str | None, to: str | None, limit: int, *, upcoming_only: bool = False
) -> tuple[list[Match], int]:
    """``limit`` current matches (not over; with ``upcoming_only``, not started either), and how many
    were skipped as started or over. Layer lists started and finished events too, so this pages on
    (up to 5 pages of 200) instead of filtering one short page."""
    keep: list[Match] = []
    skipped = 0
    for page in range(5):
        ms = client().matches(
            venue="polymarket_us", q=q or None, category=category or None, from_=from_ or None, to=to or None,
            limit=200, offset=page * 200,
        )
        for m in ms:
            if over(m) or (upcoming_only and not upcoming(m)):
                skipped += 1
            elif len(keep) < limit:
                keep.append(m)
        if len(keep) >= limit or len(ms) < 200:
            break
    return _remember(keep), skipped


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


@app.get("/paper/account")
def paper_account() -> dict[str, Any]:
    """The bot's own fake account: open positions, money at risk (as the budget rule counts it), budget."""
    c = client()
    positions = [p for p in c.positions() if getattr(p, "contracts", 0)]
    open_orders = c.orders(open=True)
    at_risk = sum(p.cost + max(p.fees, 0.0) for p in positions) + sum(order_risk(o) for o in open_orders)
    return {
        "mode": settings.mode,
        "store": str(settings.store),
        "budget": settings.budget,
        "at_risk": round(at_risk, 2),
        "open_orders": len(open_orders),
        "positions": [
            {
                "venue": p.venue,
                "market": p.market,
                "side": p.side,
                "contracts": p.contracts,
                "avg_price": p.avg_price,
                "cost": round(p.cost + max(p.fees, 0.0), 2),
            }
            for p in positions
        ],
    }


@app.post("/paper/reset")
def paper_reset() -> dict[str, Any]:
    """Paper mode only: delete the bot's fake account and start a fresh one."""
    global _client
    if settings.mode != "paper":
        raise HTTPException(403, "Only the paper account can be reset.")
    with _lock:
        if _client is not None:
            _client.close()
            _client = None
        for suffix in ("", "-wal", "-shm"):
            Path(f"{settings.store}{suffix}").unlink(missing_ok=True)
    _matches.clear()
    return paper_account()


@app.get("/matches")
def matches(
    q: str | None = None, category: str | None = None, from_: str | None = None, to: str | None = None, limit: int = 20
) -> dict[str, Any]:
    return {"matches": [match_view(m) for m in _list(q, category, from_, to, limit)[0]]}


class BestBody(BaseModel):
    match_id: str
    side: str = Field(pattern="^(yes|no)$")
    size: int = Field(gt=0, le=100_000)
    max_price: float | None = Field(default=None, gt=0, lt=1)


def _best_view(m: Match, r: Any) -> dict[str, Any]:
    """The SDK's BestOrder as it is, plus ``compare``: the same comparison named and labelled for the app."""
    return {**r.to_dict(), "compare": compare_view(m, r.why)}


@app.get("/strategies")
def list_strategies() -> dict[str, Any]:
    return {"categories": list(strategies.CATEGORIES), "strategies": strategies.available()}


class StrategyFile(BaseModel):
    filename: str = Field(max_length=60)
    code: str
    replace: bool = False


@app.post("/strategies")
def add_strategy(b: StrategyFile) -> dict[str, Any]:
    """Save your strategy file in strategies/ and check it loads. It runs your own code, on this machine only."""
    try:
        added = strategies.add(b.filename, b.code, replace=b.replace)
    except strategies.BadStrategy as e:
        raise HTTPException(422, str(e)) from e
    return {"added": added, "strategies": strategies.available()}


@app.get("/best/signal")
def best_signal(strategy: str = "sports_favorite", q: str | None = None, category: str | None = None, limit: int = 50) -> dict[str, Any]:
    try:
        mod = strategies.module(strategy)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    cats = (category,) if category else tuple(getattr(mod, "LAYER_CATEGORIES", ()) or ())
    ms, started = _list_in(q, cats or None, limit, upcoming_only=True)
    sig = mod.decide(ms, client())
    if not isinstance(sig, strategies.Signal):
        # No trade: the strategy's sentence, and what it looked at with why each wasn't picked, so any
        # can be compared by hand.
        why = sig.why if isinstance(sig, strategies.NoTrade) else None
        looked = [{**match_view(m), "reason": "rules differ" if m.caveats else "not picked"} for m in ms]
        return {"signal": None, "no_trade": f"No trade: {why}" if why else None, "matches": len(ms), "started": started, "looked": looked, "best": None}
    _matches[match_id(sig.match)] = sig.match
    body = BestBody(match_id=match_id(sig.match), side=sig.side, size=sig.size, max_price=sig.max_price)
    return {
        "signal": {**body.model_dump(), "why": sig.why, "match": match_view(sig.match)},
        "matches": len(ms),
        "best": _preview(body),
    }


def _preview(b: BestBody) -> dict[str, Any]:
    try:
        m = _find(b.match_id)
        r = client().preview_best(m, b.side, b.size, max_price=b.max_price)
        return {"ok": True, **_best_view(m, r)}
    except VenueError as e:
        return {"ok": False, "error": error_view(e)}


@app.post("/best/preview")
def best_preview(b: BestBody) -> dict[str, Any]:
    return {"match": match_view(_find(b.match_id)), **_preview(b)}


@app.post("/best/buy")
def best_buy(b: BestBody) -> dict[str, Any]:
    m = _find(b.match_id)
    r = client().buy_best(m, b.side, b.size, max_price=b.max_price)
    return {"mode": settings.mode, **_best_view(m, r)}


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
    ms, over_count = _list(b.q, b.category, b.from_, b.to, b.limit)
    s = ScanSettings(size=b.size, min_edge=b.min_edge, min_return_per_day_pct=b.min_return_per_day_pct)

    def lines() -> Iterator[str]:
        for event in scan(ms, client(), s):
            if event["type"] == "done":
                event["finished_skipped"] = over_count  # events already over, left out before the scan
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"cache-control": "no-store"})


class TradeBody(BaseModel):
    match_id: str
    size: int = Field(gt=0, le=100_000)
    min_edge: float = Field(default=0.01, ge=0, lt=1)


@app.get("/replay/files")
def replay_files(dir: str | None = None) -> dict[str, Any]:
    return {"folders": [str(p) for p in replay.folders(dir)], "files": replay.list_files(dir)}


class ReplayBody(BaseModel):
    path: str
    size: int = Field(default=100, gt=0, le=100_000)
    min_edge: float = Field(default=0.0, ge=0, lt=1)
    min_return_per_day_pct: float = Field(default=0.0, ge=0)


def _lookup(ticker: str) -> Match | None:
    try:
        return replay.layer_match(client(), ticker)
    except (VenueError, KeyError):
        return None


@app.post("/replay/run")
def replay_run(b: ReplayBody) -> dict[str, Any]:
    s = ScanSettings(size=b.size, min_edge=b.min_edge, min_return_per_day_pct=b.min_return_per_day_pct)
    try:
        return replay.replay(b.path, s, lookup=_lookup)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except LookupError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/arb/trade")
def arb_trade(b: TradeBody) -> dict[str, Any]:
    t = client().trade(_find(b.match_id), size=b.size, min_edge=b.min_edge)
    d = t.to_dict()
    d["quote"] = quote_view(t.quote)
    return {"mode": settings.mode, **d}
