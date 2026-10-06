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
    POST /best/scan       Job 1 for every market: the next markets in a category, each compared, streamed
    POST /arb/scan        Job 2: the funnel, streamed as newline-delimited JSON
    POST /arb/trade       Job 2: buy both sides of one survivor (paper unless BOT_MODE=live)
    GET  /replay/files    replayable files in recordings/ (npm run record) and a folder you pick
    POST /replay/run      Job 2 replayed: one file through the same scan, in backtest mode
    GET  /record/games    matched games to save prices for: on now first, then soonest
    POST /record/start    save one matched pair's prices to recordings/ in the background (one at a time)
    GET  /record/status   the recording's progress: time left, events saved; or how it ended
    POST /record/stop     stop it early; what's written is kept
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uselayer
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator
from uselayer import Client, Match, VenueError
from uselayer.guardrails import order_risk

from . import config, every_market, recorder, replay, strategies
from . import spend as by_dollar
from .funnel import ScanSettings, quote_view, scan
from .reads import GatewayReads, cached_books
from .strategies import upcoming
from .views import _time, busy_sentence, compare_view, error_line, error_view, match_id, match_view, over, rule_reasons, rule_warning, trade_error

settings = config.load()
app = FastAPI(title="Spread bot engine", docs_url=None, redoc_url=None)

_alerts: deque[dict[str, Any]] = deque(maxlen=50)
_matches: dict[str, Match] = {}  # every match seen, by its Kalshi market id
_client: Client | None = None
_client_error: dict[str, Any] | None = None
_lock = threading.Lock()


_gateway: GatewayReads | None = None


def gateway() -> GatewayReads:
    """The one Polymarket US transport (reads.py) every SDK client here shares, so one window paces
    the engine's reads and the arbitrage scan's together."""
    global _gateway
    if _gateway is None:
        _gateway = GatewayReads(fake_busy=None if settings.mode == "paper" else False, keep_open=True)
    return _gateway


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
                    # Polymarket US reads: paced, stopped after a 429, a book reused for a few seconds
                    # outside orders (reads.py). SPREAD_FAKE_BUSY works in paper mode only.
                    transport=gateway(),
                )
                _client_error = None
            except VenueError as e:
                _client_error = error_view(e)
                raise
        return _client


# The scan only reads books (``quote()``); it never sends an order. Polymarket US serves its public
# book from a cache that's up to 30 s old, and asks for a 10 s pause when read often, so with the
# SDK's 10 s limit a scan waits for fresh copies again and again. The scan accepts a book up to 30 s
# old instead; the trade uses the engine's own client (10 s), reads both books again, and sends
# nothing if the gap is gone.
SCAN_MAX_AGE_S = 30
SCAN_READERS = 4  # matches priced at once
_scan_client: Client | None = None


def scan_client() -> Client:
    """A reads-only SDK client for the scan: paper mode, an in-memory store, books up to 30 s old."""
    global _scan_client
    with _lock:
        if _scan_client is None:
            _scan_client = Client(
                mode="paper",
                rules={"budget": settings.budget, "max_quote_age_s": SCAN_MAX_AGE_S},
                store=":memory:",
                on_alert=lambda e: None,
                transport=gateway(),  # paced with the engine's own reads (reads.py)
            )
        return _scan_client


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
PROXY_HEADER = "x-spread-proxy"  # set by the app's proxy; a cross-site browser request can't add it


def _host_name(host: str) -> str:
    """``127.0.0.1:8765`` → ``127.0.0.1``; ``[::1]:8765`` → ``::1``."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


@app.middleware("http")
async def local_only(request: Request, call_next: Any) -> Any:
    """Only this machine, and only the app (or your own script), may use the engine.

    It places orders and adds strategy files, which run as code. A website open in your browser can
    reach 127.0.0.1 too, so besides coming from this machine a request must:
    - name this machine as its Host (a site whose name points at 127.0.0.1 sends its own name), and
    - for a POST, be JSON and carry ``x-spread-proxy``: a browser won't send either cross-site
      without asking first, and the engine never says yes.
    """
    peer = request.client.host if request.client else ""
    if peer not in (*LOCAL_HOSTS, "testclient"):
        return JSONResponse({"error": "This engine answers only this machine."}, status_code=403)
    if _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
        return JSONResponse({"error": "This engine answers only at 127.0.0.1 or localhost."}, status_code=403)
    if request.method not in ("GET", "HEAD"):
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return JSONResponse({"error": "Send JSON (content-type: application/json)."}, status_code=415)
        if request.headers.get(PROXY_HEADER) != "1":
            return JSONResponse(
                {"error": f"Only the app can do that. Scripts: send the header {PROXY_HEADER}: 1."}, status_code=403
            )
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


def page_size(limit: int) -> int:
    """Matches asked of Layer a page: about twice what's wanted, 40 to 200."""
    return min(200, max(40, 2 * limit))


def _list(
    q: str | None, category: str | None, from_: str | None, to: str | None, limit: int, *, upcoming_only: bool = False
) -> tuple[list[Match], int]:
    """``limit`` current matches (not over; with ``upcoming_only``, not started either), and how many
    were skipped as started or over. Layer lists started and finished events too, so this pages on
    (up to 1,000 matches) instead of filtering one short page.

    A page is about twice ``limit``, not Layer's 200: the SDK reads each new event's titles from both
    venues (one Polymarket US request per event), so a smaller page is fewer venue requests."""
    keep: list[Match] = []
    skipped = 0
    size = page_size(limit)
    for page in range(-(-1000 // size)):
        ms = client().matches(
            venue="polymarket_us", q=q or None, category=category or None, from_=from_ or None, to=to or None,
            limit=size, offset=page * size,
        )
        for m in ms:
            if over(m) or (upcoming_only and not upcoming(m)):
                skipped += 1
            elif len(keep) < limit:
                keep.append(m)
        if len(keep) >= limit or len(ms) < size:
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
    size: int | None = Field(default=None, gt=0, le=100_000)  # contracts, or
    spend: float | None = Field(default=None, gt=0, le=by_dollar.MAX_SPEND)  # dollars (Best venue's Amount box)
    max_price: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def _one_size(self) -> BestBody:
        if (self.size is None) == (self.spend is None):
            raise ValueError("Give either size (contracts) or spend (dollars).")
        return self


def _best_view(m: Match, r: Any) -> dict[str, Any]:
    """The SDK's BestOrder as it is, plus ``compare``: the same comparison named and labelled for the app."""
    return {**r.to_dict(), "compare": compare_view(m, r.why, client().rules.price_collar)}


@app.get("/strategies")
def list_strategies() -> dict[str, Any]:
    return {"categories": list(strategies.CATEGORIES), "strategies": strategies.available()}


@app.get("/strategies/starter")
def strategy_starter() -> dict[str, Any]:
    """The starter file (my_strategy.py) to download and make your own. It isn't in the picker."""
    return {"filename": f"{strategies.STARTER}.py", "code": strategies.starter()}


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
    # The strategy's reads, the comparison and the preview share each book read (a few seconds).
    with cached_books(), strategies.read_failures() as failed:
        sig = mod.decide(ms, client())
        if isinstance(sig, strategies.Signal):
            _matches[match_id(sig.match)] = sig.match
            body = BestBody(match_id=match_id(sig.match), side=sig.side, size=sig.size, max_price=sig.max_price)
            return {
                "signal": {**body.model_dump(), "why": sig.why, "match": match_view(sig.match)},
                "matches": len(ms),
                "best": _preview(body),
            }
    # No trade: the strategy's sentence, and what it looked at with why each wasn't picked, so any
    # can be compared by hand. If a venue didn't answer, "no trade" isn't known: say that instead.
    looked = [{**match_view(m), "reason": "rules differ" if m.caveats else "not picked"} for m in ms]
    if failed:
        return {
            "signal": None, "no_trade": busy_sentence(failed, prices=True), "unavailable": True,
            "matches": len(ms), "started": started, "looked": looked, "best": None,
        }
    why = sig.why if isinstance(sig, strategies.NoTrade) else None
    return {"signal": None, "no_trade": f"No trade: {why}" if why else None, "matches": len(ms), "started": started, "looked": looked, "best": None}


def _price(m: Match, side: str, size: int, max_price: float | None = None) -> dict[str, Any]:
    """One order compared on both venues (``client.preview_best``); sends nothing."""
    try:
        r = client().preview_best(m, side, size, max_price=max_price)
        if any(v.skip == "stale_book" for v in r.why.venues):
            # Polymarket US's cached book can come back just over 10 s old: read both books once more.
            r = client().preview_best(m, side, size, max_price=max_price)
        return {"ok": True, **_best_view(m, r)}
    except VenueError as e:
        return {"ok": False, "error": error_view(e), "error_line": error_line(e)}


def _preview(b: BestBody) -> dict[str, Any]:
    if b.spend is not None:
        return _spend(_find(b.match_id), b.side, b.spend)
    return _price(_find(b.match_id), b.side, b.size, b.max_price)  # type: ignore[arg-type]


def _spend(m: Match, side: str, amount: float) -> dict[str, Any]:
    """``amount`` dollars on ``side``: the most each venue sells for it, and which pays more if you win.
    Each book is read once; every size is then priced by the SDK against those books (spend.py)."""
    c = client()
    books, failed = by_dollar.read_books(c, m)
    view = by_dollar.books_view(m, side, amount, books, rules=c.rules, failed=failed, collar=c.rules.price_collar)
    return {"ok": True, "compare": view}


@app.post("/best/preview")
def best_preview(b: BestBody) -> dict[str, Any]:
    with cached_books():  # the comparison's book read is reused by the preview of the chosen order
        return {"match": match_view(_find(b.match_id)), **_preview(b)}


@app.post("/best/buy")
def best_buy(b: BestBody) -> dict[str, Any]:
    if b.size is None:
        raise HTTPException(422, "Buying takes a number of contracts (size).")
    m = _find(b.match_id)
    r = client().buy_best(m, b.side, b.size, max_price=b.max_price)
    return {"mode": settings.mode, **_best_view(m, r)}


class EveryMarketBody(BaseModel):
    category: str = Field(default="sports", pattern="^(sports|news|crypto)$")
    limit: int = Field(default=25, gt=0, le=50)
    size: int = Field(default=100, gt=0, le=100_000)


def _scan_price(m: Match, side: str, size: int) -> dict[str, Any]:
    # Each comparison's book read is reused by the preview of its chosen order, and a scan runs in the
    # background, so it sits through a "too many requests" block rather than skipping markets.
    with cached_books(wait_out=15.0):
        return _price(m, side, size)


@app.post("/best/scan")
def best_scan(b: EveryMarketBody) -> StreamingResponse:
    """The next ``limit`` markets in a category (soonest first), each compared on both venues, streamed
    as newline-delimited JSON while the books are read."""
    ms, started = _list_in(None, every_market.CATEGORIES[b.category].layer, every_market.LISTED, upcoming_only=True)
    ms = every_market.soonest_first(ms)[: b.limit]

    def lines() -> Iterator[str]:
        for event in every_market.scan(ms, _scan_price, category=b.category, size=b.size, started=started):
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"cache-control": "no-store"})


class ScanBody(BaseModel):
    q: str | None = None
    category: str | None = None
    from_: str | None = None
    to: str | None = None
    limit: int = Field(default=50, gt=0, le=100)
    size: int = Field(default=100, gt=0, le=100_000)
    min_edge: float = Field(default=0.0, ge=0, lt=1)
    min_return_per_day_pct: float = Field(default=0.0, ge=0)


class _ScanQuotes:
    """The scan's quotes: a book read in the last 3 s is reused (the scan sends nothing), and a
    "too many requests" block is waited out (it runs in the background) instead of dropping markets."""

    def quote(self, pair: Any, **kw: Any) -> Any:
        with cached_books(wait_out=15.0):
            return scan_client().quote(pair, **kw)


@app.post("/arb/scan")
def arb_scan(b: ScanBody) -> StreamingResponse:
    ms, over_count = _list(b.q, b.category, b.from_, b.to, b.limit)
    s = ScanSettings(size=b.size, min_edge=b.min_edge, min_return_per_day_pct=b.min_return_per_day_pct)

    def lines() -> Iterator[str]:
        for event in scan(ms, _ScanQuotes(), s, readers=SCAN_READERS):
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
    except replay.CannotPrice as e:
        raise HTTPException(422, str(e)) from e


def _kickoff(m: Match) -> datetime | None:
    """The earlier of the two venues' event times. Polymarket US gives the kickoff; Kalshi's is often
    the expected end (France vs Belgium, Oct 5: Polymarket US 18:45 UTC, Kalshi 21:45 UTC)."""
    times = [t for t in (_time(m.kalshi.event_time), _time(m.polymarket_us.event_time)) if t]
    return min(times) if times else None


def _on_now(m: Match, now: datetime) -> bool:
    """The game has kicked off and isn't over (``_list`` leaves out the ones that are over)."""
    t = _kickoff(m)
    return t is not None and t <= now


@app.get("/record/games")
def record_games(q: str | None = None, limit: int = Query(default=100, gt=0, le=200)) -> dict[str, Any]:
    """Matched markets that aren't over, for Save prices: games on now first (prices move most), then soonest."""
    ms, _ = _list(q, None, None, None, limit)
    now = datetime.now(UTC)
    far = datetime.max.replace(tzinfo=UTC)
    ordered = sorted(ms, key=lambda m: (not _on_now(m, now), _kickoff(m) or far))
    return {"matches": [{**match_view(m), "on_now": _on_now(m, now)} for m in ordered]}


class RecordBody(BaseModel):
    match_id: str
    minutes: float = Field(default=30, gt=0, le=recorder.MAX_MINUTES)


def _record_view() -> dict[str, Any]:
    r = recorder.current()
    return {"recording": r.view() if r else None}


@app.post("/record/start")
def record_start(b: RecordBody) -> dict[str, Any]:
    """Save prices: the pair's books on both venues, recorded with your keys (nothing is traded)."""
    missing = recorder.missing_key()
    if missing:
        raise HTTPException(400, missing)
    try:
        m = _find(b.match_id)
    except HTTPException as e:
        raise HTTPException(404, recorder.NO_MATCH) from e
    try:
        recorder.start(m, b.minutes)
    except recorder.Busy as e:
        raise HTTPException(409, str(e)) from e
    return _record_view()


@app.get("/record/status")
def record_status() -> dict[str, Any]:
    return _record_view()


@app.post("/record/stop")
def record_stop() -> dict[str, Any]:
    recorder.stop()
    return _record_view()


@app.post("/arb/trade")
def arb_trade(b: TradeBody) -> dict[str, Any]:
    m = _find(b.match_id)
    for attempt in (1, 2):
        try:
            t = client().trade(m, size=b.size, min_edge=b.min_edge)
            break
        except VenueError as e:
            # A book older than 10 s sends nothing; read both books once more, then say so.
            if e.code == "stale_quote" and attempt == 1:
                continue
            raise HTTPException(409, trade_error(e)) from e
    d = t.to_dict()
    d["quote"] = quote_view(t.quote)
    # A match Layer flagged as worded differently is traded like any other, and says so with the result.
    return {"mode": settings.mode, **d, "rule_warning": rule_warning(m), "rule_reasons": rule_reasons(m)}
