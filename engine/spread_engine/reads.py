"""How the engine reads Polymarket US: few book reads, spaced out, and stopping when it says "too many".

What Polymarket US enforces (measured from this machine, 2026-10-04; it isn't published): its public
gateway (``gateway.polymarket.us``) answers ``/v1/markets/<slug>/book`` with 429 after about 5 reads
in 10 seconds from one IP address, when the request's User-Agent says it's Python. The SDK's does
(``uselayer-python/<version>``), as do ``python-requests`` and ``python-httpx``. The block then lasts up
to ~10 s (``Retry-After``), and it's shared by every Python program on the same IP. The same reads
with another User-Agent, and the gateway's other endpoints (markets, events), weren't limited at 5
a second. Its published limit is 20-25 requests a second, which is what the SDK paces to (16 a
second), so the SDK alone can't stay under it. The engine doesn't change the User-Agent: the limit
looks deliberate, and that's Polymarket US's call.

The engine gives the SDK this :class:`GatewayReads` as its HTTP transport (``Client(transport=...)``,
a public SDK option), which:

- **spaces book reads**: at most :data:`BOOK_READS` in any :data:`BOOK_WINDOW_S` seconds; a read
  past that waits for a slot. Other gateway requests are paced at :data:`GATEWAY_PER_S`;
- **stops when told to**: after a 429 on a book it sends no book read until ``Retry-After`` has
  passed. A wait of a few seconds (a whole block, in a background scan: ``cached_books(wait_out=)``)
  is waited out; a longer one is answered here, without a request,
  so the SDK's three retries end within ~3 s and the app can say "busy, try again" instead of
  hanging for half a minute;
- **reuses a book for a few seconds** (:data:`BOOK_TTL_S`) inside :func:`cached_books`, so a strategy's
  read, the comparison after it and the order preview after that read each book once. Outside that
  block (orders) every read goes to the venue. A cached answer keeps its own ``Date`` and ``Age``
  headers, so the SDK still sees how old the book really is;
- **counts** requests (:attr:`GatewayReads.counts`), for tests and the request log in the PR.

Only Polymarket US's gateway is touched; every other host (Kalshi, Layer) goes straight through, with
the SDK's own pacing.

``SPREAD_FAKE_BUSY=polymarket_us`` (paper mode only, off unless set) answers every Polymarket US book
read with a 429, to see the app's "busy" state without waiting for a real one.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

GATEWAY = "gateway.polymarket.us"
BOOK_READS, BOOK_WINDOW_S = 4, 10.0  # book reads in any 10 s, at most (Polymarket US blocks after ~5)
GATEWAY_PER_S = 8.0  # every other gateway request (market info, event titles), at most
BOOK_TTL_S = 3.0  # how long a book read is reused inside cached_books()
CACHE_MAX_AGE_S = 5.0  # a copy already older than this at the venue isn't reused
WAIT_OUT_S = 3.0  # a Retry-After this short is waited out; a longer one is answered as busy

_use_cache: ContextVar[bool] = ContextVar("spread_cache_books", default=False)
_wait_out: ContextVar[float] = ContextVar("spread_wait_out", default=WAIT_OUT_S)


@contextmanager
def cached_books(*, wait_out: float = WAIT_OUT_S) -> Iterator[None]:
    """Reads in this block may reuse a Polymarket US book read in the last few seconds. Never for orders.

    ``wait_out``: the longest "too many requests" wait to sit through before answering busy. A click
    waits a few seconds at most; a scan that runs in the background can wait out a whole block.
    """
    tokens = (_use_cache.set(True), _wait_out.set(wait_out))
    try:
        yield
    finally:
        _wait_out.reset(tokens[1])
        _use_cache.reset(tokens[0])


def is_book(request: httpx.Request) -> bool:
    return request.url.host == GATEWAY and request.method == "GET" and request.url.path.endswith("/book")


class _Pace:
    """At most ``rate`` a second, with a burst of ``rate``."""

    def __init__(self, rate: float, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.rate, self.clock, self.sleep = rate, clock, sleep
        self.tokens, self.at = rate, clock()
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            while True:
                now = self.clock()
                self.tokens = min(self.rate, self.tokens + (now - self.at) * self.rate)
                self.at = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                self.sleep((1 - self.tokens) / self.rate)


class _Window:
    """At most ``n`` in any ``per`` seconds: a read past that waits for the oldest to age out."""

    def __init__(self, n: int, per: float, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.n, self.per, self.clock, self.sleep = n, per, clock, sleep
        self.sent: deque[float] = deque()
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            while True:
                now = self.clock()
                while self.sent and now - self.sent[0] >= self.per:
                    self.sent.popleft()
                if len(self.sent) < self.n:
                    self.sent.append(now)
                    return
                self.sleep(self.sent[0] + self.per - now)


def _age(r: httpx.Response) -> float:
    try:
        return float(r.headers.get("age", "0"))
    except ValueError:
        return 0.0


def _retry_after(r: httpx.Response) -> float:
    try:
        return max(1.0, float(r.headers.get("retry-after", "1")))  # Polymarket US: wait at least 1 s
    except ValueError:
        return 1.0


def _busy(request: httpx.Request, why: str) -> httpx.Response:
    """A 429 made here, without a request. ``Retry-After: 0`` so the SDK's retries end within seconds."""
    return httpx.Response(
        429, headers={"retry-after": "0", "x-spread": why}, json={"status": 429, "message": "Too Many Requests"}, request=request
    )


class GatewayReads(httpx.BaseTransport):
    """The SDK's transport: paced, cached and counted reads from Polymarket US's gateway (see the module)."""

    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        fake_busy: bool | None = None,
    ) -> None:
        self.inner = inner or httpx.HTTPTransport()
        self.clock, self.sleep = clock, sleep
        self.books = _Window(BOOK_READS, BOOK_WINDOW_S, clock, sleep)
        self.gateway = _Pace(GATEWAY_PER_S, clock, sleep)
        self.cache: dict[str, tuple[float, httpx.Response, bytes]] = {}
        self.hold_until = 0.0  # no book read before this (after a 429)
        self.lock = threading.Lock()
        self.counts: Counter[str] = Counter()  # "book", "gateway" (other gateway calls), "cached", "held", "429"
        if fake_busy is None:
            fake_busy = os.environ.get("SPREAD_FAKE_BUSY", "").strip().lower() == "polymarket_us"
        self.fake_busy = fake_busy

    def _count(self, what: str) -> None:
        with self.lock:
            self.counts[what] += 1

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != GATEWAY:
            return self.inner.handle_request(request)
        book = is_book(request)
        if book and self.fake_busy:
            self._count("429")
            return _busy(request, "fake")
        key = str(request.url)
        if book and _use_cache.get():
            with self.lock:
                hit = self.cache.get(key)
            if hit and self.clock() - hit[0] <= BOOK_TTL_S:
                self._count("cached")
                return httpx.Response(hit[1].status_code, headers=hit[1].headers, stream=httpx.ByteStream(hit[2]), request=request)
        if not book:
            self.gateway.take()
            self._count("gateway")
            return self.inner.handle_request(request)
        patience = _wait_out.get()
        wait = self.hold_until - self.clock()
        if wait > patience:
            self._count("held")
            return _busy(request, "held")
        if wait > 0:
            self.sleep(wait)
        self.books.take()
        self._count("book")
        r = self.inner.handle_request(request)
        if r.status_code == 429:
            self._count("429")
            wait = _retry_after(r)
            with self.lock:
                self.hold_until = max(self.hold_until, self.clock() + wait)
            if wait > patience:
                # The SDK would sleep the whole Retry-After before each of its 3 retries (~30 s). The
                # hold above keeps the wait instead, and the retries are answered here: busy, fast.
                r.close()
                return _busy(request, "venue")
            return r
        if r.status_code != 200:
            return r
        body = b"".join(r.stream)  # type: ignore[arg-type]  # the bytes as sent (still encoded): the SDK's client decodes them
        r.close()
        if _age(r) <= CACHE_MAX_AGE_S:
            with self.lock:
                self.cache[key] = (self.clock(), r, body)
                if len(self.cache) > 500:
                    self.cache.clear()
        return httpx.Response(
            r.status_code, headers=r.headers, stream=httpx.ByteStream(body), request=request, extensions=r.extensions
        )

    def close(self) -> None:
        self.inner.close()
