"""Record both venues' books for a matched pair, to replay later on the Arbitrage screen.

    npm run record -- KXNBAGAME-26OCT05MEMATL-ATL --minutes 60

Give a Kalshi ticker. Layer finds its Polymarket US twin; the SDK's record_stream then writes every
book change and trade from both venues to recordings/<ticker>-<UTC time>.jsonl, with the match
saved next to it (.match.json). Everything stays on this machine.

Needs LAYER_API_KEY, your Kalshi key, and your Polymarket US key (its live stream is read with your
key; nothing is traded).
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from datetime import UTC, datetime

from uselayer import Client, Kalshi, PolymarketUS, VenueError, record_stream

from spread_engine import config  # loads .env
from spread_engine.replay import RECORDINGS, layer_match, sidecar

print = functools.partial(print, flush=True)  # noqa: A001  (show progress at once, even into a file)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticker", help="a Kalshi market ticker Layer has matched, e.g. KXNBAGAME-26OCT05MEMATL-ATL")
    ap.add_argument("--minutes", type=float, default=60, help="how long to record (default 60)")
    a = ap.parse_args()
    config.load()

    try:
        m = layer_match(Client(store=":memory:"), a.ticker.upper())
        kalshi, pm = Kalshi.from_env(), PolymarketUS.from_env()
    except VenueError as e:
        print(f"✗ {e.message} {e.hint or ''}")
        return 1

    k, u = m.kalshi, m.polymarket_us
    print(f"● {k.event or k.market_id}: {k.outcome or ''}")
    print(f"  Kalshi        {k.market_id}")
    print(f"  Polymarket US {u.market_id}")
    if m.caveats:
        print(f"  ! Layer flags a rule difference ({', '.join(m.caveats)}); the replay will drop this pair for it.")

    RECORDINGS.mkdir(exist_ok=True)
    path = RECORDINGS / f"{k.market_id}-{datetime.now(UTC):%Y%m%dT%H%MZ}.jsonl"
    sidecar(path).write_text(json.dumps(m.to_dict(), indent=1))
    print(f"  → {path.relative_to(RECORDINGS.parent)} for {a.minutes:g} min (Ctrl-C stops it; what's written is kept)")
    try:
        s = record_stream(
            # The twin's own id: "<slug>:short" records the short side's book under that id,
            # which is what quote() looks for on replay.
            [k.market_id, u.market_id],
            path,
            kalshi=kalshi,
            polymarket_us=pm,
            duration_s=a.minutes * 60,
        )
    except KeyboardInterrupt:
        print("\n  stopped")
        return 0
    print(f"✓ {s}")
    print("  Replay it: Arbitrage → Replay in the app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
