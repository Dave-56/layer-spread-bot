"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  errorText,
  ndjson,
  survivorOrder,
  VENUE_NAME,
  VERDICT_LABEL,
  type MatchView,
  type QuoteLeg,
  type QuoteView,
  type RecordGame,
  type Recording,
  type ReplayFile,
  type ReplayMoment,
  type ReplayResult,
  type ScanEvent,
  type ScanRow,
  type TradeResult,
} from "@/lib/engine";
import { gamesOf } from "./BestVenue";
import { cents, count, money, pct, side, when } from "./format";
import { DROPS, lasted, replayHeadline, said, scanHeadline, tradeLine } from "./gaps";
import { ruleTitle } from "./headlines";
import { traded } from "./PaperAccount";
import { LENGTHS, savedLine, savingLine } from "./saving";

// Job 2: scan matched markets for the same bet priced differently on the two venues. The answer
// comes first (how many gaps are still money after fees, or why none is), then each surviving gap
// with both venues side by side, then the dropped ones, folded, grouped by reason. A match worded
// differently on the two venues goes through the same checks and carries its warning.
// Every number and reason is the engine's (the SDK's quote()); nothing is computed here.

export interface FunnelState {
  total: number;
  counts: Partial<Record<ScanRow["verdict"], number>>;
  rows: ScanRow[];
  done: boolean;
  finishedSkipped?: number;
  searched?: boolean;
}

const VENUES = ["kalshi", "polymarket_us"] as const;

/** A price as the chance the market gives that side: 41¢ → "41%". */
const chance = (p: number) => cents(p).replace("¢", "%");

/** A quiet warning: the rules differ slightly, so in a rare case the two could settle differently.
 * Under it, Layer's reason for each difference when it sent one; without them the warning stands alone. */
function RuleNote({ text, reasons }: { text: string | null | undefined; reasons?: string[] }) {
  if (!text) return null;
  return (
    <div className="rule-note">
      {text}
      {reasons?.map((r) => (
        <div key={r} className="rule-reason">
          {r}
        </div>
      ))}
    </div>
  );
}

/** One venue's leg of the gap: its market, the side to buy and its price, and a link to it. */
function LegCell({ m, leg, venue }: { m: MatchView; leg: QuoteLeg | undefined; venue: (typeof VENUES)[number] }) {
  const mk = m[venue];
  return (
    <div className="venue-cell">
      <div className="venue-name">{VENUE_NAME[venue]}</div>
      {mk.question && <div className="venue-q">{mk.question}</div>}
      <div className="venue-chance">{leg ? chance(leg.best_price) : "—"}</div>
      {leg && (
        <div className="small">
          Buy {side(leg.side)} at {cents(leg.best_price)}
        </div>
      )}
      {mk.url && (
        <a className="small venue-link" href={mk.url} target="_blank" rel="noreferrer">
          Open on {VENUE_NAME[venue]} ↗
        </a>
      )}
    </div>
  );
}

/** Gross gap → fees → net → return per day, for the whole order. */
function Steps({ q }: { q: QuoteView }) {
  const legs = [q.a, q.b].filter((l): l is QuoteLeg => !!l);
  return (
    <div className="steps">
      <div className="step-cell">
        <span>Gross gap</span>
        <b>{money(q.gross_spread)}</b>
        <small>{count(q.contracts)} contracts</small>
      </div>
      <div className="step-cell">
        <span>Fees</span>
        <b>−{money(q.fees)}</b>
        <small>{legs.map((l) => `${l.venue_name} ${money(l.fee)}`).join(" + ")}</small>
      </div>
      <div className="step-cell net">
        <span>Net</span>
        <b>{money(q.net_profit)}</b>
        <small>
          {pct(q.return_pct)} on {money(q.cost)}
        </small>
      </div>
      <div className="step-cell">
        <span>Return per day</span>
        <b>{q.return_per_day_pct == null ? "—" : pct(q.return_per_day_pct, q.return_per_day_pct < 0.1 ? 3 : 2)}</b>
        <small>{q.settles_at ? `pays out ${when(q.settles_at)}` : "no payout date"}</small>
      </div>
    </div>
  );
}

/** A gap that's still money after fees: the market, both legs side by side, then the math. */
function GapCard({ row, kicker, children }: { row: Pick<ScanRow, "match" | "quote" | "reason">; kicker?: string; children?: ReactNode }) {
  const m = row.match;
  const q = row.quote!;
  const t = when(m.event_time);
  const legOf = (v: string) => [q.a, q.b].find((l) => l?.venue === v) ?? undefined;
  return (
    <div className="market gap">
      {kicker && <div className="kicker">{kicker}</div>}
      <div className="market-event">
        {m.title}
        {t ? ` · ${t}` : ""}
      </div>
      <div className="market-outcome">{m.outcome ?? m.title}</div>
      <div className="market-venues">
        {VENUES.map((v) => (
          <LegCell key={v} m={m} venue={v} leg={legOf(v)} />
        ))}
      </div>
      <Steps q={q} />
      {row.reason && <p className="small muted">{row.reason}</p>}
      <RuleNote text={m.rule_warning} reasons={m.rule_reasons} />
      {children}
    </div>
  );
}

/** A live survivor: the card and the paper-trade button. Both books are read again before anything is sent. */
function Survivor({ row, size, minEdge, mode }: { row: ScanRow; size: number; minEdge: number; mode: "paper" | "live" }) {
  const [busy, setBusy] = useState(false);
  const [trade, setTrade] = useState<TradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A reset paper account starts over: the old trade result no longer applies.
  useEffect(() => {
    const clear = () => {
      setTrade(null);
      setError(null);
    };
    window.addEventListener("spread:reset", clear);
    return () => window.removeEventListener("spread:reset", clear);
  }, []);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/engine/arb/trade", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: row.match.id, size, min_edge: minEdge }),
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
    <GapCard row={row}>
      {!trade && (
        <div className="row trade-row">
          <button className="btn" onClick={go} disabled={busy}>
            {busy ? "Reading both books…" : mode === "live" ? "Buy both sides (real money)" : "Paper-trade both sides"}
          </button>
          <span className="small muted">Both books are read again first. If the gap is gone, nothing is bought.</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {trade && <div className={`box ${trade.status === "hedged" ? "good" : ""} trade-done`}>{tradeLine(trade)}</div>}
    </GapCard>
  );
}

/** The dropped gaps, grouped by reason, each with one plain sentence. Closest to money first. */
function Dropped({ rows }: { rows: ScanRow[] }) {
  if (!rows.length) return null;
  const byEdge = [...rows].sort((a, b) => (b.quote?.edge_at_best ?? -9) - (a.quote?.edge_at_best ?? -9));
  return (
    <details className="fold">
      <summary>
        {count(rows.length)} dropped, by reason
      </summary>
      {DROPS.map((v) => {
        const group = byEdge.filter((r) => r.verdict === v);
        return group.length ? <DropGroup key={v} label={VERDICT_LABEL[v]} rows={group} /> : null;
      })}
    </details>
  );
}

const FIRST = 8; // rows shown per reason before "Show all"

function DropGroup({ label, rows }: { label: string; rows: ScanRow[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, FIRST);
  return (
    <div className="drop-group">
      <div className="label">
        {label} · {count(rows.length)}
      </div>
      <ul className="drops">
        {shown.map((r) => (
          <li key={r.match.id}>
            <span className="drop-name">{r.match.outcome ?? r.match.title}</span>
            <span className="muted"> · {r.match.title}</span>
            {r.match.rule_warning && (
              <span className="pill warn" title={ruleTitle(r.match)}>
                Rules differ
              </span>
            )}
            <div className="small muted">{r.reason}</div>
          </li>
        ))}
      </ul>
      {rows.length > shown.length && (
        <button className="link small" onClick={() => setAll(true)}>
          Show all {count(rows.length)}
        </button>
      )}
    </div>
  );
}

/** A scan's result: the answer, each survivor, then the dropped ones folded. Also used by the chat panel. */
export function FunnelResult({ f, size, mode, minEdge = 0 }: { f: FunnelState; size: number; mode: "paper" | "live"; minEdge?: number }) {
  const survivors = survivorOrder(f.rows.filter((r) => r.verdict === "survivor"));
  return (
    <div className="gaps">
      {f.done && <h2 className={`headline ${survivors.length ? "" : "none"}`}>{scanHeadline(f)}</h2>}
      {survivors.map((r) => (
        <Survivor key={r.match.id} row={r} size={size} minEdge={minEdge} mode={mode} />
      ))}
      {f.done && <Dropped rows={f.rows.filter((r) => r.verdict !== "survivor")} />}
    </div>
  );
}

function NumberField({ label, value, onChange, step = 1, min = 0, max }: { label: string; value: number; onChange: (n: number) => void; step?: number; min?: number; max?: number }) {
  return (
    <label className="field narrow">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => {
          const n = +e.target.value || 0;
          onChange(Math.min(max ?? Infinity, Math.max(min, n)));
        }}
      />
    </label>
  );
}

function Live({ mode }: { mode: "paper" | "live" }) {
  const [q, setQ] = useState("");
  const [size, setSize] = useState(100);
  const [minEdge, setMinEdge] = useState(0);
  const [minPerDay, setMinPerDay] = useState(0);
  const [limit, setLimit] = useState(50);
  const [f, setF] = useState<FunnelState | null>(null);
  const [sent, setSent] = useState({ size: 100, minEdge: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useRef(0);

  async function scan() {
    const id = ++run.current;
    setBusy(true);
    setError(null);
    setSent({ size, minEdge: minEdge / 100 });
    setF({ total: 0, counts: {}, rows: [], done: false, searched: !!q.trim() });
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
      setF(null);
    }
    if (run.current === id) setBusy(false);
  }

  return (
    <>
      <div className="controls run">
        <button className="btn big" onClick={scan} disabled={busy}>
          {busy ? "Scanning…" : "Scan"}
        </button>
        <details className="settings">
          <summary>Settings</summary>
          <div className="controls">
            <label className="field grow">
              Search
              <input className="search" value={q} placeholder="e.g. nfl (blank: every market)" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && scan()} />
            </label>
            <NumberField label="Contracts" value={size} min={1} onChange={setSize} />
            <NumberField label="Min profit (¢ a contract)" value={minEdge} step={0.1} onChange={setMinEdge} />
            <NumberField label="Min return a day (%)" value={minPerDay} step={0.01} onChange={setMinPerDay} />
            <NumberField label="Markets" value={limit} min={1} max={100} onChange={setLimit} />
          </div>
        </details>
      </div>
      {busy && f && (
        <div className="status">
          <span className="dot" /> Checking prices on both venues: {f.rows.length} of {f.total || "…"}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {f && <FunnelResult f={f} size={sent.size} minEdge={sent.minEdge} mode={mode} />}
    </>
  );
}

function span(from: string | null | undefined, to: string | null | undefined): string {
  const a = when(from);
  if (!a) return "—";
  const b = to ? new Date(to).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" }) : null;
  return b ? `${a} – ${b}` : a;
}

/** The file's name in the picker: its market and when it was saved. */
function fileLabel(f: ReplayFile): string {
  if (f.error) return `${f.file} (can't be read)`;
  return `${f.match ? (f.match.outcome ?? f.match.title) : f.file} · ${span(f.from, f.to)}`;
}


const POLL_MS = 1000;

/** Save prices: pick a matched game (on now first), how long, and the engine records both venues'
 * books in the background with the SDK's record_stream. Progress shows here; Stop keeps what's written. */
function SavePrices({ onSaved }: { onSaved: (path: string) => void }) {
  const [found, setFound] = useState<RecordGame[] | null>(null);
  const [game, setGame] = useState("");
  const [mid, setMid] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [rec, setRec] = useState<Recording | null>(null);
  const [polled, setPolled] = useState(0); // when rec was read, for the countdown between polls
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seen = useRef<string | null>(null); // the recording whose end was already handed to Saved prices

  function show(r: Recording | null) {
    setRec(r);
    setPolled(Date.now());
    setTick(Date.now());
    if (r && r.state !== "recording" && r.path && seen.current !== r.started_at) {
      seen.current = r.started_at;
      onSaved(r.path);
    }
  }

  useEffect(() => {
    // A late answer must not undo a game picked since (React runs this twice in development).
    let gone = false;
    fetch("/engine/record/games")
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) throw new Error(errorText(body, r.status));
        if (gone) return;
        const ms = (body as { matches: RecordGame[] }).matches;
        setFound(ms);
        setGame(ms[0] ? (ms[0].event_key ?? ms[0].id) : "");
        setMid(ms[0]?.id ?? "");
      })
      .catch((e) => !gone && setError(e instanceof Error ? e.message : String(e)));
    // A recording started before this page opened is picked up where it is; one that already ended isn't announced again.
    fetch("/engine/record/status")
      .then((r) => r.json())
      .then((b: { recording: Recording | null }) => {
        if (gone) return;
        if (b.recording?.state === "recording") show(b.recording);
        else seen.current = b.recording?.started_at ?? null;
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = rec?.state === "recording";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      setTick(Date.now());
      fetch("/engine/record/status")
        .then((r) => r.json())
        .then((b: { recording: Recording | null }) => show(b.recording))
        .catch(() => {});
    }, POLL_MS);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  async function post(path: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const b = await r.json().catch(() => null);
      if (!r.ok) throw new Error(errorText(b, r.status));
      show((b as { recording: Recording | null }).recording);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const games = gamesOf(found ?? []);
  const onNow = (g: (typeof games)[number]) => !!(g.outcomes[0] as RecordGame).on_now;
  const current = games.find((g) => g.key === game);
  const option = (g: (typeof games)[number]) => (
    <option key={g.key} value={g.key}>
      {g.title}
      {!onNow(g) && when(g.time) ? ` · ${when(g.time)}` : ""}
    </option>
  );
  const left = rec ? rec.seconds_left - (tick - polled) / 1000 : 0;
  const done = rec ? savedLine(rec) : null;

  return (
    <div className="box save-prices">
      <div className="label">Save prices</div>
      {running && rec ? (
        <>
          <div className="status">
            <span className="dot" /> Saving prices: {rec.match.outcome ?? rec.match.title} · {rec.match.title}
          </div>
          <div className="row">
            <span>{savingLine(rec, left)}</span>
            <button className="btn quiet" onClick={() => post("/engine/record/stop", {})} disabled={busy}>
              Stop
            </button>
          </div>
        </>
      ) : (
        <>
          {found === null && !error && (
            <div className="status">
              <span className="dot" /> Loading games
            </div>
          )}
          {found && !games.length && <p className="small muted">No game is open on both venues right now.</p>}
          {current && (
            <div className="controls run">
              <label className="field grow">
                Game
                <select
                  value={game}
                  onChange={(e) => {
                    setGame(e.target.value);
                    setMid(games.find((g) => g.key === e.target.value)?.outcomes[0]?.id ?? "");
                  }}
                >
                  {games.some(onNow) && <optgroup label="On now">{games.filter(onNow).map(option)}</optgroup>}
                  {games.some((g) => !onNow(g)) && <optgroup label="Later">{games.filter((g) => !onNow(g)).map(option)}</optgroup>}
                </select>
              </label>
              {current.outcomes.length > 1 && (
                <label className="field">
                  Outcome
                  <select value={mid} onChange={(e) => setMid(e.target.value)}>
                    {current.outcomes.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.outcome ?? m.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field">
                For
                <select value={minutes} onChange={(e) => setMinutes(+e.target.value)}>
                  {LENGTHS.map((l) => (
                    <option key={l.minutes} value={l.minutes}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </label>
              <button className="btn" onClick={() => post("/engine/record/start", { match_id: mid, minutes })} disabled={busy || !mid}>
                {busy ? "Starting…" : "Save prices"}
              </button>
            </div>
          )}
          {done && <p className={rec?.state === "failed" ? "error" : "small"}>{done}</p>}
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function Replay() {
  const [files, setFiles] = useState<ReplayFile[] | null>(null);
  const [folder, setFolder] = useState("");
  const [file, setFile] = useState("");
  const [size, setSize] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cant, setCant] = useState<string | null>(null);
  const [res, setRes] = useState<ReplayResult | null>(null);

  function load(dir: string, pick?: string) {
    fetch(`/engine/replay/files${dir.trim() ? `?dir=${encodeURIComponent(dir.trim())}` : ""}`)
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!r.ok) throw new Error(errorText(body, r.status));
        const list = (body as { files: ReplayFile[] }).files;
        setError(null);
        setFiles(list);
        setFile(list.find((f) => !f.error && f.path === pick)?.path ?? list.find((f) => !f.error)?.path ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }

  useEffect(() => load(""), []);

  async function replay() {
    setBusy(true);
    setError(null);
    setCant(null);
    setRes(null);
    try {
      const r = await fetch("/engine/replay/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: file, size }),
      });
      const body = await r.json().catch(() => null);
      // A file that can't be replayed is an answer, in one sentence: not an error.
      if (r.status === 404 || r.status === 422) setCant(errorText(body, r.status));
      else if (!r.ok) throw new Error(errorText(body, r.status));
      else setRes(body as ReplayResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  const usable = (files ?? []).filter((f) => !f.error);
  return (
    <>
      <p className="lead">Replay re-runs prices you saved from a live game, moment by moment, to show whether a gap would have made money after fees.</p>
      {files && !usable.length && <p className="lead">No saved prices yet. Pick a game that&apos;s on now and press Save prices.</p>}
      <SavePrices
        onSaved={(path) => {
          setRes(null);
          setCant(null);
          load(folder, path);
        }}
      />
      <div className="controls run">
        {usable.length > 0 && (
          <label className="field grow">
            Saved prices
            <select value={file} onChange={(e) => setFile(e.target.value)}>
              {files!.map((f) => (
                <option key={f.path} value={f.path} disabled={!!f.error}>
                  {fileLabel(f)}
                </option>
              ))}
            </select>
          </label>
        )}
        {usable.length > 0 && (
          <button className="btn big" onClick={replay} disabled={busy || !file}>
            {busy ? "Replaying…" : "Replay"}
          </button>
        )}
        <details className="settings">
          <summary>Settings</summary>
          <div className="controls">
            <label className="field grow">
              Folder
              <input className="search" value={folder} placeholder="recordings/ is always included" onChange={(e) => setFolder(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(folder)} />
            </label>
            <button className="btn quiet" onClick={() => load(folder)}>
              Open folder
            </button>
            <NumberField label="Contracts" value={size} min={1} onChange={setSize} />
          </div>
        </details>
      </div>
      {error && <p className="error">{error}</p>}
      {cant && <h2 className="headline none">{cant}</h2>}
      {res && <ReplayAnswer res={res} />}
    </>
  );
}

function ReplayAnswer({ res }: { res: ReplayResult }) {
  const best: ReplayMoment | null = res.best_survivor;
  const closest = !best ? res.best : null;
  const others = res.moments - (res.counts.survivor ?? 0);
  return (
    <div className="gaps">
      <div className="kicker">
        Replay of {span(res.from, res.to)} · {res.file}
      </div>
      <h2 className={`headline ${best ? "" : "none"}`}>{replayHeadline(res)}</h2>
      {best && <p className="lead">{lasted(res)}</p>}
      {closest?.quote?.edge_at_best != null && (
        <p className="lead">
          Closest: {cents(closest.quote.edge_at_best)} a contract after fees, {when(closest.at)}.
        </p>
      )}
      {best?.quote && <GapCard row={best} kicker={`Best moment · ${when(best.at)}`} />}
      {!best && <RuleNote text={res.match.rule_warning} reasons={res.match.rule_reasons} />}
      {res.size_note && <p className="small muted">{res.size_note}</p>}
      {best && others > 0 && (
        <details className="fold">
          <summary>
            {count(others)} other {others === 1 ? "moment" : "moments"}, by reason
          </summary>
          <ul className="drops">
            {DROPS.filter((v) => res.counts[v]).map((v) => (
              <li key={v}>
                {count(res.counts[v])} {said(v, res.counts[v], true)}.
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default function Arbitrage({ mode }: { mode: "paper" | "live" }) {
  const [view, setView] = useState<"live" | "replay">("live");
  const [opened, setOpened] = useState(false);
  return (
    <section>
      <p className="tab-lead">Scan for the same bet priced differently on Kalshi and Polymarket US. Spread keeps only the gaps that are still money after fees.</p>
      <div className="switch" role="tablist">
        <button className={view === "live" ? "current" : ""} onClick={() => setView("live")}>
          Live
        </button>
        <button
          className={view === "replay" ? "current" : ""}
          onClick={() => {
            setView("replay");
            setOpened(true);
          }}
        >
          Replay
        </button>
      </div>
      {/* Both stay mounted: switching never loses a scan or a replay. */}
      <div hidden={view !== "live"}>
        <Live mode={mode} />
      </div>
      {opened && (
        <div hidden={view !== "replay"}>
          <Replay />
        </div>
      )}
    </section>
  );
}
