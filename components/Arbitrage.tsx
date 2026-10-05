"use client";

import { useEffect, useRef, useState } from "react";
import {
  errorText,
  ndjson,
  VERDICT_LABEL,
  VERDICT_PHRASE,
  type QuoteView,
  type ReplayFile,
  type ReplayResult,
  type ScanEvent,
  type ScanRow,
  type TradeResult,
  type Verdict,
} from "@/lib/engine";
import { MatchLine } from "./BestVenue";
import { cents, count, money, pct, side, when } from "./format";
import { traded } from "./PaperAccount";

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
  finishedSkipped?: number;
}

export function FunnelBars({ f }: { f: FunnelState }) {
  const seen = f.rows.length;
  return (
    <div className="funnel">
      <div className="step">
        <span>Markets checked</span>
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
            <span>{VERDICT_LABEL[v]}</span>
            <i style={{ width: n ? `${Math.max(2, (n / Math.max(1, seen)) * 100)}%` : 0 }} />
            <em>{n}</em>
          </div>
        );
      })}
    </div>
  );
}

export function SurvivorMath({ q, perContract = false }: { q: QuoteView; perContract?: boolean }) {
  // perContract: the size behind the prices is unknown, so show one contract's numbers only.
  const amt = perContract ? cents : money;
  return (
    <div className="math">
      <div className="eq">
        <span>Gross spread</span>
        <span>{amt(q.gross_spread)}</span>
        <span className="muted">
          {perContract ? "a contract: $1 at settlement, minus what both legs cost" : `${count(q.contracts)} contracts pay $1 each, minus what both legs cost`}
        </span>
      </div>
      <div className="eq">
        <span>− Fees</span>
        <span>{amt(q.fees)}</span>
        <span className="muted">
          {q.a?.venue_name} {amt(q.a?.fee)} + {q.b?.venue_name} {amt(q.b?.fee)}
        </span>
      </div>
      <div className="eq total">
        <span>= Net</span>
        <span className={q.net_profit > 0 ? "pos" : "neg"}>{amt(q.net_profit)}</span>
        <span className="muted">
          {pct(q.return_pct)} on {amt(q.cost)}
          {perContract ? " · top of book only, size unknown" : ""}
        </span>
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
      traded();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  return (
    <div className="box good">
      <div className="label">Still money after fees</div>
      <b>{row.match.outcome ?? row.match.title}</b>
      <MatchLine m={row.match} />
      <Legs q={q} />
      <SurvivorMath q={q} />
      {row.reason && <p className="small muted">{row.reason}</p>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" onClick={go} disabled={busy}>
          {busy ? "Sending…" : mode === "live" ? "Buy both sides (real money)" : "Paper-trade both sides"}
        </button>
        <span className="small muted">Prices are checked again first. If the gap is gone, nothing is bought.</span>
      </div>
      {error && <p className="error">{error}</p>}
      {trade && (
        <p className="small" style={{ marginTop: 10 }}>
          <b>{trade.status}</b>: {count(trade.hedged)} contracts hedged, {money(trade.locked_in)} locked in after fees
          {trade.unwind_loss ? `, unwind cost ${money(trade.unwind_loss)}` : ""}.{" "}
          {trade.status === "missed" ? "No trade: the gap closed before the orders." : ""}
        </p>
      )}
    </div>
  );
}

/** Why a scan found nothing, in one plain sentence: the biggest reasons, largest first. */
export function noTradeLine(f: FunnelState): string {
  const n = f.rows.length;
  if (!n)
    return f.finishedSkipped
      ? `No trade: all ${f.finishedSkipped} events were already over.`
      : "No trade: no matched markets for that search.";
  const parts = ORDER.filter((v) => v !== "survivor")
    .map((v) => ({ v, k: f.rows.filter((r) => r.verdict === v).length }))
    .filter((x) => x.k)
    .sort((a, b) => b.k - a.k);
  if (parts.length === 1) return `No trade: all ${n} ${VERDICT_PHRASE[parts[0].v]}.`;
  const named = parts.slice(0, 3).map((x) => `${x.k} ${VERDICT_PHRASE[x.v]}`);
  const rest = parts.slice(3).reduce((t, x) => t + x.k, 0);
  if (rest) named.push(`${rest} for other reasons`);
  return `No trade: of ${n} markets, ${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}.`;
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
      {f.done && !survivors.length && <p>{noTradeLine(f)}</p>}
      {closest.length > 0 && (
        <>
          <h3>Closest gaps</h3>
          <DroppedTable rows={closest} />
        </>
      )}
      {f.done && dropped.length > 0 && (
        <details>
          <summary className="small muted" style={{ cursor: "pointer" }}>
            All {dropped.length}, by reason
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
        if (e.type === "done") setF((s) => s && { ...s, counts: e.counts, done: true, finishedSkipped: e.finished_skipped });
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
          Contracts
          <input type="number" min={1} value={size} onChange={(e) => setSize(Math.max(1, +e.target.value || 1))} />
        </label>
        <label className="field">
          Min profit (¢ each)
          <input type="number" min={0} step={0.1} value={minEdge} onChange={(e) => setMinEdge(Math.max(0, +e.target.value || 0))} />
        </label>
        <label className="field">
          Min profit a day (%)
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
          <span className="dot" /> Checking prices: {f.rows.length} of {f.total || "…"}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {f && <FunnelResult f={f} size={size} mode={mode} />}
    </>
  );
}

function span(from: string | null, to: string | null): string {
  const a = when(from);
  if (!a) return "—";
  const b = to ? new Date(to).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) : null;
  return b ? `${a} – ${b}` : a;
}

function seconds(s: number): string {
  return s < 90 ? `${s.toFixed(0)} s` : `${(s / 60).toFixed(1)} min`;
}

function Replay() {
  const [files, setFiles] = useState<ReplayFile[] | null>(null);
  const [folder, setFolder] = useState("");
  const [file, setFile] = useState("");
  const [size, setSize] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<ReplayResult | null>(null);

  function load(dir: string) {
    fetch(`/engine/replay/files${dir.trim() ? `?dir=${encodeURIComponent(dir.trim())}` : ""}`)
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) throw new Error(errorText(body, r.status));
        const list = (body as { files: ReplayFile[] }).files;
        setError(null);
        setFiles(list);
        setFile(list.find((f) => !f.error)?.path ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => load(""), []);

  async function run() {
    setBusy(true);
    setError(null);
    setRes(null);
    try {
      const r = await fetch("/engine/replay/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: file, size }),
      });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(errorText(body, r.status));
      setRes(body as ReplayResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const moments = res ? ORDER.filter((v) => res.counts[v]).map((v) => ({ v, n: res.counts[v] })) : [];
  const shown = res?.best_survivor ?? res?.best ?? null;
  return (
    <>
      <p className="small muted" style={{ marginTop: 0 }}>
        Replays order-book history you have on this machine through the same checks as the live scan, in the
        SDK&apos;s backtest mode. Record a matched pair with{" "}
        <code>npm run record -- &lt;kalshi ticker&gt; --minutes 60</code> (files go to <code>recordings/</code>), or pick
        a folder of files the SDK&apos;s <code>import_events</code> reads.
      </p>
      <div className="controls">
        <label className="field">
          Folder (optional)
          <input className="wide" value={folder} placeholder="recordings/ is always listed" onChange={(e) => setFolder(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(folder)} />
        </label>
        <button className="btn quiet" onClick={() => load(folder)}>
          List files
        </button>
      </div>
      {files && !files.length && <p className="small muted">No files yet. Record a pair with the command above.</p>}
      {files && files.length > 0 && (
        <div className="controls">
          <label className="field">
            File
            <select value={file} onChange={(e) => setFile(e.target.value)} style={{ minWidth: 340 }}>
              {files.map((f) => (
                <option key={f.path} value={f.path} disabled={!!f.error}>
                  {f.error
                    ? `${f.file} (can't read it)`
                    : `${f.match ? f.match.outcome ?? f.match.title : f.file} · ${span(f.from ?? null, f.to ?? null)}${f.top_of_book_only ? " · top of book" : ""}`}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Contracts a leg
            <input type="number" min={1} value={size} onChange={(e) => setSize(Math.max(1, +e.target.value || 1))} />
          </label>
          <button className="btn" onClick={run} disabled={busy || !file}>
            {busy ? "Replaying…" : "Replay"}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {res && (
        <>
          <h3>Replay of {span(res.from, res.to)}</h3>
          <MatchLine m={res.match} />
          <p className="small muted">
            {res.file}, replayed in the SDK&apos;s backtest mode: every moment either book changed, at most once a
            second, through the same checks as the live scan.
            {res.size_unknown
              ? " Top of book only, size unknown: prices are per contract, and nothing here says how many would fill."
              : res.top_of_book_only
                ? " Top of book only: the file has one price level a side, so depth beyond it is unknown."
                : ""}
          </p>
          <div className="funnel">
            <div className="step">
              <span>Moments checked</span>
              <i style={{ width: "100%" }} />
              <em>{res.moments}</em>
            </div>
            {moments.map(({ v, n }) => (
              <div key={v} className={`step ${v === "survivor" ? "survivor" : ""}`}>
                <span>{v === "survivor" ? "Still money after all of it" : VERDICT_LABEL[v]}</span>
                <i style={{ width: `${Math.max(2, (n / Math.max(1, res.moments)) * 100)}%` }} />
                <em>{n}</em>
              </div>
            ))}
          </div>
          {res.best_survivor && shown?.quote ? (
            <div className="box good">
              <div className="label">Best moment · {when(shown.at)}</div>
              <Legs q={shown.quote} />
              <SurvivorMath q={shown.quote} perContract={res.size_unknown} />
              <p className="small muted" style={{ marginBottom: 0 }}>
                A gap survived for {seconds(res.survivor_seconds)} in all, {seconds(res.longest_survivor_s)} at the longest.
              </p>
            </div>
          ) : (
            <div className="box">
              <b>No moment was money after fees, rules and depth.</b>
              {shown?.quote && (
                <span className="muted">
                  {" "}
                  Closest: {cents(shown.quote.edge_at_best)} a contract after fees at {when(shown.at)} ({VERDICT_LABEL[shown.verdict].toLowerCase()}).
                </span>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}

export default function Arbitrage({ mode }: { mode: "paper" | "live" }) {
  const [view, setView] = useState<"live" | "replay">("live");
  return (
    <section>
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
