"use client";

import { useRef, useState } from "react";
import {
  errorText,
  ndjson,
  VERDICT_LABEL,
  type QuoteView,
  type ScanEvent,
  type ScanRow,
  type TradeResult,
  type Verdict,
} from "@/lib/engine";
import { MatchLine } from "./BestVenue";
import { cents, count, money, pct, side, when } from "./format";

// Job 2: scan matched markets for the same bet priced differently on the two venues, and show
// what happened to every gap: dropped with a plain reason, or a survivor that's still money after
// fees, rule differences and depth.

const ORDER: Verdict[] = [
  "rules_differ",
  "unpriced",
  "no_offers",
  "no_gap",
  "fees",
  "below_min_edge",
  "too_thin",
  "no_payout_date",
  "per_day_low",
  "survivor",
];

export interface FunnelState {
  total: number;
  counts: Partial<Record<Verdict, number>>;
  rows: ScanRow[];
  done: boolean;
}

export function FunnelBars({ f }: { f: FunnelState }) {
  const seen = f.rows.length;
  return (
    <div className="funnel">
      <div className="step">
        <span>Matched markets scanned</span>
        <i style={{ width: "100%" }} />
        <em>
          {seen}
          {f.done ? "" : `/${f.total}`}
        </em>
      </div>
      {ORDER.map((v) => {
        const n = f.rows.filter((r) => r.verdict === v).length;
        if (!n && v !== "survivor") return null;
        return (
          <div key={v} className={`step ${v === "survivor" ? "survivor" : ""}`}>
            <span>{v === "survivor" ? "Still money after all of it" : `Dropped: ${VERDICT_LABEL[v].toLowerCase()}`}</span>
            <i style={{ width: n ? `${Math.max(2, (n / Math.max(1, seen)) * 100)}%` : 0 }} />
            <em>{n}</em>
          </div>
        );
      })}
    </div>
  );
}

export function SurvivorMath({ q }: { q: QuoteView }) {
  return (
    <div className="math">
      <div className="eq">
        <span>Gross spread</span>
        <span>{money(q.gross_spread)}</span>
        <span className="muted">{count(q.contracts)} contracts pay $1 each, minus what both legs cost</span>
      </div>
      <div className="eq">
        <span>− Fees</span>
        <span>{money(q.fees)}</span>
        <span className="muted">
          {q.a?.venue_name} {money(q.a?.fee)} + {q.b?.venue_name} {money(q.b?.fee)}
        </span>
      </div>
      <div className="eq total">
        <span>= Net</span>
        <span className={q.net_profit > 0 ? "pos" : "neg"}>{money(q.net_profit)}</span>
        <span className="muted">{pct(q.return_pct)} on {money(q.cost)}</span>
      </div>
      <div className="eq">
        <span>Return per day</span>
        <span>{q.return_per_day_pct == null ? "—" : pct(q.return_per_day_pct, 3)}</span>
        <span className="muted">
          {q.days_held == null ? "no payout date from either venue" : `${q.days_held} days until paid (${when(q.settles_at)})`}
        </span>
      </div>
    </div>
  );
}

function Legs({ q }: { q: QuoteView }) {
  if (!q.a || !q.b) return null;
  return (
    <div className="small" style={{ margin: "6px 0 10px" }}>
      Buy {side(q.a.side)} on {q.a.venue_name} at {cents(q.a.best_price)} + {side(q.b.side)} on {q.b.venue_name} at{" "}
      {cents(q.b.best_price)}
      <span className="muted"> · per contract at the best asks: {cents(q.gross_at_best)} before fees, {cents(q.edge_at_best)} after</span>
    </div>
  );
}

export function DroppedTable({ rows }: { rows: ScanRow[] }) {
  return (
    <table className="t">
      <thead>
        <tr>
          <th>Market</th>
          <th className="num">Gap</th>
          <th className="num">After fees</th>
          <th>Why it was dropped</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.match.id}>
            <td>
              {r.match.outcome ?? r.match.title}
              <div className="small muted">{r.match.title}</div>
            </td>
            <td className="num">{cents(r.quote?.gross_at_best)}</td>
            <td className={`num ${(r.quote?.edge_at_best ?? 0) > 0 ? "pos" : ""}`}>{cents(r.quote?.edge_at_best)}</td>
            <td>
              <span className="pill">{VERDICT_LABEL[r.verdict]}</span>
              <div className="small muted">{r.reason}</div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Survivor({ row, size, mode }: { row: ScanRow; size: number; mode: "paper" | "live" }) {
  const [busy, setBusy] = useState(false);
  const [trade, setTrade] = useState<TradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const q = row.quote!;

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/engine/arb/trade", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: row.match.id, size }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(errorText(body, r.status));
      setTrade(body as TradeResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  return (
    <div className="box good">
      <div className="label">Survivor</div>
      <b>{row.match.outcome ?? row.match.title}</b>
      <MatchLine m={row.match} />
      <Legs q={q} />
      <SurvivorMath q={q} />
      {row.reason && <p className="small muted">{row.reason}</p>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" onClick={go} disabled={busy}>
          {busy ? "Sending…" : mode === "live" ? "Send LIVE orders, both legs" : "Paper-trade both legs"}
        </button>
        <span className="small muted">Both books are read again first; if the gap is gone, nothing is sent.</span>
      </div>
      {error && <p className="error">{error}</p>}
      {trade && (
        <p className="small" style={{ marginTop: 10 }}>
          <b>{trade.status}</b>: {count(trade.hedged)} contracts hedged, {money(trade.locked_in)} locked in after fees
          {trade.unwind_loss ? `, unwind cost ${money(trade.unwind_loss)}` : ""}.{" "}
          {trade.status === "missed" ? "Fees say no trade: the gap closed before the orders." : ""}
        </p>
      )}
    </div>
  );
}

export function FunnelResult({ f, size, mode }: { f: FunnelState; size: number; mode: "paper" | "live" }) {
  const survivors = f.rows.filter((r) => r.verdict === "survivor");
  const dropped = f.rows
    .filter((r) => r.verdict !== "survivor")
    .sort((a, b) => (b.quote?.edge_at_best ?? -9) - (a.quote?.edge_at_best ?? -9));
  const closest = dropped.filter((r) => r.quote?.edge_at_best != null).slice(0, 5);
  return (
    <>
      <FunnelBars f={f} />
      {survivors.map((r) => (
        <Survivor key={r.match.id} row={r} size={size} mode={mode} />
      ))}
      {f.done && !survivors.length && (
        <div className="box">
          <b>No trade.</b> Nothing is money after fees, rules and depth right now.
          {dropped[0]?.quote && (
            <span className="muted">
              {" "}
              Closest: {dropped[0].match.outcome ?? dropped[0].match.title}, {cents(dropped[0].quote.edge_at_best)} a contract after
              fees ({VERDICT_LABEL[dropped[0].verdict].toLowerCase()}).
            </span>
          )}
        </div>
      )}
      {closest.length > 0 && (
        <>
          <h3>Closest gaps that didn&apos;t make it</h3>
          <DroppedTable rows={closest} />
        </>
      )}
      {f.done && dropped.length > 0 && (
        <details>
          <summary className="small muted" style={{ cursor: "pointer" }}>
            All {dropped.length} dropped, by reason
          </summary>
          {ORDER.filter((v) => v !== "survivor").map((v) => {
            const rows = dropped.filter((r) => r.verdict === v);
            return rows.length ? (
              <div key={v}>
                <h3>
                  {VERDICT_LABEL[v]} <span className="muted">({rows.length})</span>
                </h3>
                <DroppedTable rows={rows} />
              </div>
            ) : null;
          })}
        </details>
      )}
    </>
  );
}

function Live({ mode }: { mode: "paper" | "live" }) {
  const [q, setQ] = useState("");
  const [size, setSize] = useState(100);
  const [minEdge, setMinEdge] = useState(0);
  const [minPerDay, setMinPerDay] = useState(0);
  const [limit, setLimit] = useState(50);
  const [f, setF] = useState<FunnelState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useRef(0);

  async function scan() {
    const id = ++run.current;
    setBusy(true);
    setError(null);
    setF({ total: 0, counts: {}, rows: [], done: false });
    try {
      const r = await fetch("/engine/arb/scan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ q: q.trim() || null, limit, size, min_edge: minEdge / 100, min_return_per_day_pct: minPerDay }),
      });
      if (!r.ok || !r.body) throw new Error(errorText(await r.json().catch(() => null), r.status));
      for await (const e of ndjson<ScanEvent>(r.body)) {
        if (run.current !== id) return;
        if (e.type === "start") setF((s) => s && { ...s, total: e.total });
        if (e.type === "row") setF((s) => s && { ...s, rows: [...s.rows, e] });
        if (e.type === "done") setF((s) => s && { ...s, counts: e.counts, done: true });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    if (run.current === id) setBusy(false);
  }

  return (
    <>
      <div className="controls">
        <label className="field">
          Search
          <input className="wide" value={q} placeholder="e.g. nfl (blank: all)" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && scan()} />
        </label>
        <label className="field">
          Contracts a leg
          <input type="number" min={1} value={size} onChange={(e) => setSize(Math.max(1, +e.target.value || 1))} />
        </label>
        <label className="field">
          Min after fees (¢)
          <input type="number" min={0} step={0.1} value={minEdge} onChange={(e) => setMinEdge(Math.max(0, +e.target.value || 0))} />
        </label>
        <label className="field">
          Min return/day (%)
          <input type="number" min={0} step={0.01} value={minPerDay} onChange={(e) => setMinPerDay(Math.max(0, +e.target.value || 0))} />
        </label>
        <label className="field">
          Markets
          <input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Math.min(100, Math.max(1, +e.target.value || 1)))} />
        </label>
        <button className="btn" onClick={scan} disabled={busy}>
          {busy ? "Scanning…" : "Scan now"}
        </button>
      </div>
      {busy && f && (
        <div className="status">
          <span className="dot" /> Reading both venues&apos; books: {f.rows.length} of {f.total || "…"}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {f && <FunnelResult f={f} size={size} mode={mode} />}
    </>
  );
}

function Replay() {
  return (
    <div className="box">
      <b>Replay a gap you recorded.</b>
      <p className="muted small" style={{ margin: "6px 0 0" }}>
        Record both venues&apos; books with the SDK (<code>python -m uselayer record</code>), then replay them through
        the same scan in backtest mode. Coming in the next change.
      </p>
    </div>
  );
}

export default function Arbitrage({ mode }: { mode: "paper" | "live" }) {
  const [view, setView] = useState<"live" | "replay">("live");
  return (
    <section>
      <h2>Arbitrage</h2>
      <p className="lead">
        The same bet, priced differently on Kalshi and Polymarket US. Buying YES on one and NO on the other pays $1 a
        contract either way, so a gap is money only if it&apos;s still there after both venues&apos; fees, the rules
        match and the books are deep enough. Most gaps aren&apos;t. Here&apos;s what happened to each one.
      </p>
      <div className="switch" role="tablist">
        <button className={view === "live" ? "current" : ""} onClick={() => setView("live")}>
          Live
        </button>
        <button className={view === "replay" ? "current" : ""} onClick={() => setView("replay")}>
          Replay
        </button>
      </div>
      {view === "live" ? <Live mode={mode} /> : <Replay />}
    </section>
  );
}
