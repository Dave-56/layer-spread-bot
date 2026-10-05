"""Smoke test: every engine route against the real venues, in paper mode. Sends no real orders.

    cd engine && uv run python scripts/smoke.py --q nfl

Needs LAYER_API_KEY and a Kalshi key in .env (Kalshi books are read with your own key).
Prints what each route returned, never a key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import tempfile  # noqa: E402

os.environ["BOT_MODE"] = "paper"  # this script never runs live, whatever .env says
# Its own throwaway paper account, so smoke trades never land in yours.
os.environ["BOT_STORE_DIR"] = tempfile.mkdtemp(prefix="spread-smoke-")

from fastapi.testclient import TestClient  # noqa: E402

from spread_engine.app import app  # noqa: E402


def show(label: str, started: float, body: object) -> None:
    print(f"\n== {label} ({time.monotonic() - started:.1f}s)")
    print(json.dumps(body, indent=1, default=str)[:4000])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", default=None)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--size", type=int, default=10)
    args = ap.parse_args()
    # As the app's proxy calls it: this machine's own address, with the proxy header.
    c = TestClient(app, base_url="http://127.0.0.1", headers={"x-spread-proxy": "1"})

    t = time.monotonic()
    st = c.get("/status").json()
    show("status", t, st)
    assert st["mode"] == "paper", "smoke runs in paper mode only"

    lst = c.get("/strategies").json()
    print("\n== strategies:", ", ".join(f"{s['category']} / {s['name']}" + (f" (error: {s['error']})" if s["error"] else "") for s in lst["strategies"]))

    t = time.monotonic()
    r = c.get("/best/signal", params={"q": args.q, "limit": args.limit})
    show("best/signal (your strategy → both venues compared)", t, r.json())
    sig = r.json().get("signal")
    if sig:
        print("   verdict:", (r.json()["best"].get("compare") or {}).get("verdict"))
    else:
        print("   no trade:", r.json().get("no_trade"))

    # By hand: search matched markets by words, pick one, compare it on both venues.
    t = time.monotonic()
    found = c.get("/matches", params={"q": args.q, "limit": 5}).json()["matches"]
    if found:
        pick = found[0]
        r = c.post("/best/preview", json={"match_id": pick["id"], "side": "yes", "size": args.size})
        cmp = r.json().get("compare") or {}
        print(f"\n== by hand ({time.monotonic() - t:.1f}s): {pick['outcome']} · {pick['title']}")
        print("   ", (cmp.get("pair") or {}).get("note"))
        for v in cmp.get("venues", []):
            print(f"    {v['venue_name']:14} {v['price_label']} ({v['chance_label']}) fees {v['fees']} fillable {v['fillable']} total {v['total_cost']} {v['skip_reason'] or ''}")
        print("   ", cmp.get("verdict") or r.json().get("error"))

    # Every market: the next few sports markets, each compared on both venues, streamed.
    t = time.monotonic()
    with c.stream("POST", "/best/scan", json={"category": "sports", "limit": 3, "size": args.size}) as s:
        events = [json.loads(line) for line in s.iter_lines() if line]
    print(f"\n== best/scan ({time.monotonic() - t:.1f}s): {events[0]} → {events[-1]}")
    for e in events:
        if e["type"] == "row":
            cmp = e["best"].get("compare") or {}
            skipped = " ".join(v["skip_line"] for v in cmp.get("venues", []) if v.get("skip_line"))
            print(f"  {e['outcome']:14} {e['match']['id']:45} {cmp.get('saving_label')} {skipped or e['best'].get('error_line') or ''}")

    if sig:
        t = time.monotonic()
        body = {"match_id": sig["match_id"], "side": sig["side"], "size": args.size}
        r = c.post("/best/buy", json=body)
        show(f"best/buy {args.size} (paper)", t, r.json())

    t = time.monotonic()
    rows = []
    with c.stream("POST", "/arb/scan", json={"q": args.q, "limit": args.limit, "size": args.size}) as s:
        for line in s.iter_lines():
            if line:
                rows.append(json.loads(line))
    done = rows[-1]
    print(f"\n== arb/scan ({time.monotonic() - t:.1f}s): {done}")
    for e in rows:
        if e["type"] == "row":
            q = e["quote"] or {}
            print(
                f"  {e['verdict']:15} {e['match']['id']:45} gross@best={q.get('gross_at_best')} "
                f"net@best={q.get('edge_at_best')} contracts={q.get('contracts')} rpd={q.get('return_per_day_pct')} | {e['reason']}"
                + (f" | {e['match']['rule_warning']}" if e["match"].get("rule_warning") else "")
            )
    survivors = [e for e in rows if e.get("verdict") == "survivor"]
    if survivors:
        t = time.monotonic()
        r = c.post("/arb/trade", json={"match_id": survivors[0]["match"]["id"], "size": args.size})
        show("arb/trade (paper)", t, r.json())
    else:
        print("\n== arb/trade skipped: no survivor (fees say no trade)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
