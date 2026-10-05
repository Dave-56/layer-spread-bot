"use client";

import { useState } from "react";
import { errorText, VENUE_NAME, type BestResult, type BestVenue as Why, type MatchView, type Signal } from "@/lib/engine";
import { CAVEAT, cents, count, money, side, SKIP, when } from "./format";

/** The SDK's comparison as one sentence, from its own numbers. */
export function verdictLine(why: Why): string {
  const chosen = why.venues.find((v) => v.venue === why.venue);
  if (!chosen) return why.reason;
  const other = why.venues.find((v) => v.venue !== why.venue && v.ok);
  const name = VENUE_NAME[chosen.venue] ?? chosen.venue;
  if (!other) return `Only ${name} can fill ${count(why.size)} contracts: ${money(chosen.all_in)} all-in.`;
  if (why.reason_code === "tie_more_size")
    return `Same all-in cost on both (${money(chosen.all_in)} for ${count(why.size)} contracts). ${name} has more on offer at that price, so it goes there.`;
  if (why.reason_code === "tie_first_listed")
    return `Same all-in cost on both (${money(chosen.all_in)} for ${count(why.size)} contracts), so it goes to ${name}.`;
  const by = why.saving != null && why.saving < 0.005 ? "less than 1¢" : money(why.saving);
  return `${name} is ${by} cheaper all-in for ${count(why.size)} contracts: ${money(chosen.all_in)} vs ${money(other.all_in)} on ${VENUE_NAME[other.venue] ?? other.venue}.`;
}

// Job 1: your strategy already knows the trade. The bot prices that exact order on both venues,
// after fees and depth, and sends it where it's cheaper for that size.

export function CompareTable({ why }: { why: Why }) {
  return (
    <table className="t">
      <thead>
        <tr>
          <th>Venue</th>
          <th className="num">Avg price</th>
          <th className="num">Fees</th>
          <th className="num">Fillable</th>
          <th className="num">Total cost</th>
        </tr>
      </thead>
      <tbody>
        {why.venues.map((v) => (
          <tr key={v.venue} className={v.venue === why.venue ? "chosen" : undefined}>
            <td>
              {VENUE_NAME[v.venue] ?? v.venue}{" "}
              {v.venue === why.venue && <span className="pill good">cheaper</span>}
              {v.skip && (
                <div className="small muted">
                  Skipped: {SKIP[v.skip] ?? v.skip}
                  {v.detail ? `. ${v.detail}` : ""}
                </div>
              )}
            </td>
            <td className="num">{cents(v.avg_price)}</td>
            <td className="num">{money(v.fees)}</td>
            <td className="num" title="Contracts on offer at or better than the limit price">
              {count(v.size_at_limit)}
            </td>
            <td className="num">
              <b>{money(v.all_in)}</b>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function MatchLine({ m }: { m: MatchView }) {
  const t = when(m.event_time);
  return (
    <div className="small muted">
      {m.title}
      {t ? ` · ${t}` : ""} ·{" "}
      {m.kalshi.url ? <a href={m.kalshi.url} target="_blank" rel="noreferrer">Kalshi</a> : "Kalshi"} ↔{" "}
      {m.polymarket_us.url ? (
        <a href={m.polymarket_us.url} target="_blank" rel="noreferrer">Polymarket US</a>
      ) : (
        "Polymarket US"
      )}
      {m.caveats.length > 0 && (
        <span className="pill warn" style={{ marginLeft: 6 }}>
          rules differ: {m.caveats.map((c) => CAVEAT[c] ?? c).join(", ")}
        </span>
      )}
    </div>
  );
}

interface SignalResult {
  signal: Signal | null;
  matches: number;
  best: BestResult | null;
}

export default function BestVenue({ mode }: { mode: "paper" | "live" }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<null | "signal" | "buy">(null);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<SignalResult | null>(null);
  const [order, setOrder] = useState<BestResult | null>(null);

  async function runStrategy() {
    setBusy("signal");
    setError(null);
    setOrder(null);
    try {
      const qs = new URLSearchParams({ limit: "50" });
      if (q.trim()) qs.set("q", q.trim());
      const r = await fetch(`/engine/best/signal?${qs}`);
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(errorText(body, r.status));
      setRes(body as SignalResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(null);
  }

  async function buy() {
    if (!res?.signal) return;
    setBusy("buy");
    setError(null);
    try {
      const s = res.signal;
      const r = await fetch("/engine/best/buy", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: s.match_id, side: s.side, size: s.size, max_price: s.max_price }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(errorText(body, r.status));
      setOrder(body as BestResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(null);
  }

  const s = res?.signal;
  const why = res?.best?.why;
  const p = res?.best?.preview;
  // What the SDK's guardrails said about the chosen order, before anything is sent.
  const blocked =
    p && !p.allowed
      ? [p.rules.decision.reason ?? (p.blocked_by ? `Blocked by ${p.blocked_by}.` : null), ...p.problems].filter(Boolean).join(" ")
      : null;
  return (
    <section>
      <h2>Best venue</h2>
      <p className="lead">
        Your strategy decides the trade. The bot prices that exact order on Kalshi and Polymarket US from their live
        order books, with each venue&apos;s fees, and sends it to the one that&apos;s cheaper for that size.
      </p>

      <div className="controls">
        <label className="field">
          Markets to give your strategy
          <input className="wide" value={q} placeholder="search, e.g. nfl" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runStrategy()} />
        </label>
        <button className="btn" onClick={runStrategy} disabled={busy !== null}>
          {busy === "signal" ? "Running…" : "Run my strategy"}
        </button>
      </div>

      {busy === "signal" && (
        <div className="status">
          <span className="dot" /> Matching markets with Layer, then reading both order books
        </div>
      )}
      {error && <p className="error">{error}</p>}

      {res && (
        <div className="box stub">
          <div className="label">Your strategy here · engine/spread_engine/strategy.py</div>
          {s ? (
            <>
              <div className="signal">
                buy {count(s.size)} {side(s.side)} · {s.match.outcome ?? s.match.title}
                {s.max_price != null ? ` · max ${cents(s.max_price)}` : ""}
              </div>
              <MatchLine m={s.match} />
              <div className="small muted" style={{ marginTop: 4 }}>{s.why}</div>
            </>
          ) : (
            <div className="muted">No trade: your strategy returned nothing for {res.matches} matched markets.</div>
          )}
        </div>
      )}

      {s && res?.best && !res.best.ok && <p className="error">{res.best.error?.message} {res.best.error?.hint}</p>}

      {s && why && (
        <>
          <h3>Same order, both venues</h3>
          <CompareTable why={why} />
          <p className={why.venue ? "" : "error"}>
            {why.venue ? verdictLine(why) : "No venue can take this order right now, so nothing is sent."}
          </p>
          {why.venue && blocked && (
            <div className="box warn">
              <div className="label">Your rules say no</div>
              {blocked}
              <div className="small muted">
                Guardrails run before anything is sent. Change them in <code>.env</code> (<code>BOT_BUDGET</code>) or close
                positions first.
              </div>
            </div>
          )}
          {why.venue && (
            <div className="row">
              <button className="btn" onClick={buy} disabled={busy !== null || blocked !== null}>
                {busy === "buy"
                  ? "Sending…"
                  : mode === "live"
                    ? `Send LIVE order to ${VENUE_NAME[why.venue]}`
                    : `Paper-trade on ${VENUE_NAME[why.venue]}`}
              </button>
              <span className="small muted">
                {mode === "live" ? "Live mode: a real order with your own key." : "Paper mode: real books, fake money."} Limit{" "}
                {cents(why.venues.find((v) => v.venue === why.venue)?.limit_price)}, immediate-or-cancel.
              </span>
            </div>
          )}
        </>
      )}

      {order?.order && (
        <div className="box good" style={{ marginTop: 16 }}>
          <div className="label">{order.mode === "live" ? "Live order" : "Paper order"}</div>
          {order.order.status} on {VENUE_NAME[order.order.venue]}: {count(order.order.filled)} of {count(order.order.size)}{" "}
          {side(order.order.side)} at {cents(order.order.avg_price)} avg, fees {money(order.order.fees)}.
        </div>
      )}

      <p className="notice">
        The comparison is a snapshot of both books when you ran it. A book can move before the order arrives; the limit
        price caps what the order can pay.
      </p>
    </section>
  );
}
