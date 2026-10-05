"use client";

import { useEffect, useRef, useState } from "react";
import {
  errorText,
  ndjson,
  VENUE_NAME,
  type BestResult,
  type EveryEvent,
  type EveryOutcome,
  type EveryRow,
  type BestVenue as Why,
  type CompareView,
  type MatchView,
  type Signal,
  type StrategyInfo,
  type StrategyList,
} from "@/lib/engine";
import { cents, count, money, side, skipText, UNKNOWN_SKIPS, when } from "./format";
import {
  alreadyExists,
  bestHeadline,
  DEFAULT_HOW,
  everyCell,
  everyOrder,
  everySummary,
  HOW,
  matchNote,
  skipLine,
  strategyNoTrade,
  type How,
} from "./headlines";

// Job 1: you (or your strategy) already know the trade. The bot prices that exact order on both
// venues, after fees and depth, and shows where it's cheaper for that size.
//
// The flow: choose (a game by hand, or a strategy) → compare → the match, the two venues' markets
// side by side, and the answer: where it's cheaper, and by how much. Nothing is sent from here.
// Every number and label is the engine's (BestResult.compare); nothing is computed here.

const ADD = "__add__"; // the dropdown's last option: add your own .py

// ---- Used by the chat panel and the Arbitrage tab ------------------------------------------------

/** The SDK's comparison as one sentence, from its own numbers. */
export function verdictLine(why: Why): string {
  const unknown = why.venues.filter((v) => v.skip && UNKNOWN_SKIPS.has(v.skip)).map((v) => VENUE_NAME[v.venue] ?? v.venue);
  if (unknown.length)
    return `Couldn't get ${unknown.map((n) => `${n}'s`).join(" or ")} ${unknown.length > 1 ? "prices" : "price"} just now, so we can't compare yet.`;
  const chosen = why.venues.find((v) => v.venue === why.venue);
  if (!chosen) return why.reason;
  const other = why.venues.find((v) => v.venue !== why.venue && v.ok);
  const name = VENUE_NAME[chosen.venue] ?? chosen.venue;
  if (!other) return `Only ${name} can fill ${count(why.size)} contracts: ${money(chosen.all_in)}, fees included.`;
  if (why.reason_code === "tie_more_size")
    return `Same price on both (${money(chosen.all_in)} for ${count(why.size)}, fees included). ${name} has more for sale, so it goes there.`;
  if (why.reason_code === "tie_first_listed")
    return `Same price on both (${money(chosen.all_in)} for ${count(why.size)}, fees included), so it goes to ${name}.`;
  const by = why.saving != null && why.saving < 0.005 ? "less than 1¢" : money(why.saving);
  return `${name} is ${by} cheaper for ${count(why.size)} contracts, fees included: ${money(chosen.all_in)} vs ${money(other.all_in)}.`;
}

export function CompareTable({ why, c }: { why: Why; c?: CompareView }) {
  return (
    <table className="t">
      <thead>
        <tr>
          <th>Venue</th>
          <th className="num">Avg price</th>
          <th className="num">Fees</th>
          <th className="num">For sale</th>
          <th className="num">Total cost</th>
        </tr>
      </thead>
      <tbody>
        {why.venues.map((v) => (
          <tr key={v.venue} className={v.venue === (c ? c.cheaper : why.venue) ? "chosen" : undefined}>
            <td>
              {VENUE_NAME[v.venue] ?? v.venue}{" "}
              {v.venue === (c ? c.cheaper : why.venue) && <span className="pill good">cheaper</span>}
              {v.skip && (
                <div className="small muted">
                  {c?.venues.find((x) => x.venue === v.venue)?.skip_reason ?? skipText(v.skip, VENUE_NAME[v.venue] ?? v.venue)}
                </div>
              )}
            </td>
            <td className="num">{cents(v.avg_price)}</td>
            <td className="num">{money(v.fees)}</td>
            <td
              className="num"
              title="Whole contracts for sale at or under the price it would pay (venues also sell fractions of one)"
            >
              {v.size_at_limit == null ? "—" : count(Math.floor(v.size_at_limit))}
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
      {m.rule_warning && (
        <span className="pill warn" style={{ marginLeft: 6 }}>
          {m.rule_warning}
        </span>
      )}
    </div>
  );

}

// ---- Best venue ---------------------------------------------------------------------------------

/** A quiet warning: the rules differ slightly, so in a rare case the two could settle differently. */
function RuleNote({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return <div className="rule-note">{text}</div>;
}

/** The match, Polymarket-style: the outcome big, then each venue's market side by side with its chance. */
function MarketCard({ m, c }: { m: MatchView; c?: CompareView }) {
  const t = when(m.event_time);
  const warning = c?.pair.rule_warning ?? m.rule_warning;
  return (
    <div className="market">
      <div className="market-event">
        {m.title}
        {t ? ` · ${t}` : ""}
      </div>
      <div className="market-outcome">{m.outcome ?? m.title}</div>
      <div className="market-venues">
        {(["kalshi", "polymarket_us"] as const).map((venue) => {
          const p = c?.pair[venue];
          const mk = m[venue];
          const v = c?.venues.find((x) => x.venue === venue);
          const url = p?.url ?? mk.url;
          return (
            <div key={venue} className={`venue-cell ${v?.cheaper ? "cheaper" : ""} ${v && !v.ok ? "out" : ""}`}>
              <div className="venue-name">
                {v?.venue_name ?? VENUE_NAME[venue]}
                {v?.cheaper && <span className="pill good">Cheaper</span>}
              </div>
              <div className="venue-q">{p?.question ?? p?.title ?? mk.question ?? mk.event ?? mk.market_id}</div>
              {v &&
                (v.ok ? (
                  <>
                    <div className="venue-chance">{v.chance_label ?? "—"}</div>
                    <div className="small muted">
                      {side(c!.side)} at {v.price_label ?? "—"}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="venue-chance">—</div>
                    <div className="small muted">{skipLine(v)}</div>
                  </>
                ))}
              {url && (
                <a className="small venue-link" href={url} target="_blank" rel="noreferrer">
                  Open on {VENUE_NAME[venue]} ↗
                </a>
              )}
            </div>
          );
        })}
      </div>
      <div className="matched">{c ? matchNote(c.pair.note, c.pair.rule_warning) : "Matched by Layer: the same bet on both venues."}</div>
      <RuleNote text={warning} />
    </div>
  );
}

/** Each venue's numbers for the whole order, as the engine labels them. */
function Numbers({ c }: { c: CompareView }) {
  return (
    <table className="t">
      <thead>
        <tr>
          <th>Venue</th>
          <th className="num">Avg price</th>
          <th className="num">Fees</th>
          <th className="num" title="Whole contracts for sale at or under the price it would pay">
            For sale
          </th>
          <th className="num">Total cost</th>
        </tr>
      </thead>
      <tbody>
        {c.venues.map((v) => (
          <tr key={v.venue} className={v.cheaper ? "chosen" : undefined}>
            <td>
              {v.venue_name}
              {!v.ok && <div className="small muted">{skipLine(v)}</div>}
            </td>
            <td className="num">{v.avg_price_label ?? "—"}</td>
            <td className="num">{money(v.fees)}</td>
            <td className="num">{count(v.fillable)}</td>
            <td className="num">
              <b>{money(v.total_cost)}</b>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface Looked extends MatchView {
  reason: string;
}

interface SignalResult {
  signal: Signal | null;
  no_trade?: string | null; // the strategy's own sentence, or the engine's when a venue didn't answer
  unavailable?: boolean; // a venue didn't answer while the strategy read prices: try again
  matches: number;
  started?: number;
  looked?: Looked[];
  best: BestResult | null;
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(errorText(body, r.status));
  return body as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

const orderOf = (t: Signal) => ({ match_id: t.match_id, side: t.side, size: t.size, max_price: t.max_price });

type Busy = null | "run" | "find";

/** One trade being compared. Each mode has its own, so nothing leaks between them. */
function useTrade() {
  const [trade, setTrade] = useState<(Signal & { picked: string }) | null>(null);
  const [best, setBest] = useState<BestResult | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);

  function start() {
    setBusy("run");
    setError(null);
    setTrade(null);
    setBest(null);
  }
  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }
  function show(t: Signal, picked: string, b: BestResult | null) {
    setTrade({ ...t, picked });
    setBest(b);
  }
  async function compare(t: Signal, picked: string) {
    start();
    try {
      show(t, picked, await getJson<BestResult>("/engine/best/preview", post(orderOf(t))));
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }
  /** The same comparison again, after a venue didn't answer. */
  const again = () => trade && compare(trade, trade.picked);
  return { trade, best, busy, error, setBusy, start, fail, show, compare, again };
}

type Trade = ReturnType<typeof useTrade>;

/** Bring a new result into view: on a laptop screen it lands below the chooser. */
function useShowWhenReady(key: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (key) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [key]);
  return ref;
}

function TryAgain({ onClick, busy }: { onClick: () => void; busy: boolean }) {
  return (
    <div className="row again">
      <button className="btn" onClick={onClick} disabled={busy}>
        {busy ? "Checking…" : "Try again"}
      </button>
    </div>
  );
}

/** The match, the two venues' markets, then the answer. Numbers folded below. Nothing is sent from here. */
function TradeResult({ t }: { t: Trade }) {
  const { trade, best, busy } = t;
  const ref = useShowWhenReady(best);
  if (!trade || !best) return null;
  const c = best.ok ? best.compare : undefined;
  const h = c ? bestHeadline(c, best.why?.reason_code) : null;
  return (
    <div className="result" ref={ref}>
      <div className="kicker">
        {trade.picked}: buy {count(trade.size)} {side(trade.side)}
        {trade.max_price != null ? `, at most ${cents(trade.max_price)} each` : ""}
        {trade.why ? <span className="muted"> · {trade.why}</span> : null}
      </div>
      <MarketCard m={trade.match} c={c} />

      {!best.ok && (
        <>
          <p className="error">
            {best.error?.message} {best.error?.hint}
          </p>
          {best.error?.unavailable && <TryAgain onClick={t.again} busy={busy !== null} />}
        </>
      )}
      {h && (
        <>
          <h2 className={`headline ${c?.cheaper ? "" : "none"}`}>{h.title}</h2>
          {h.detail && <p className="lead">{h.detail}</p>}
          {h.retry && <TryAgain onClick={t.again} busy={busy !== null} />}
        </>
      )}
      {c && !h?.retry && (
        <details className="fold">
          <summary>Price, fees and size on each venue</summary>
          <Numbers c={c} />
        </details>
      )}
    </div>
  );
}

function Working({ t, label = "Checking prices on both venues" }: { t: Trade; label?: string }) {
  return (
    <>
      {t.busy === "run" && (
        <div className="status">
          <span className="dot" /> {label}
        </div>
      )}
      {t.error && <p className="error">{t.error}</p>}
    </>
  );
}

/**
 * The strategy dropdown: every file in strategies/, grouped by category, and "Add your own (.py)…"
 * last. Choosing that opens the file picker: the engine saves the file in strategies/, checks it
 * loads, and it's selected. Cancel goes back to the strategy you had.
 */
function StrategyPicker({
  list,
  cats,
  pick,
  onPick,
  onAdded,
}: {
  list: StrategyInfo[];
  cats: string[];
  pick: string;
  onPick: (id: string) => void;
  onAdded: (b: StrategyList & { added: StrategyInfo }) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [replace, setReplace] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // Closing the file picker without a file goes back to the strategy you had.
  useEffect(() => {
    const el = input.current;
    const cancel = () => setAdding(false);
    el?.addEventListener("cancel", cancel);
    return () => el?.removeEventListener("cancel", cancel);
  }, []);

  // The starter file (my_strategy.py), saved in the browser: edit it, rename it, add it back.
  async function download() {
    try {
      const b = await getJson<{ filename: string; code: string }>("/engine/strategies/starter");
      const url = URL.createObjectURL(new Blob([b.code], { type: "text/x-python" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: b.filename });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
    }
  }

  async function send(file: File | undefined, again = false) {
    if (input.current) input.current.value = "";
    if (!file) return setAdding(false);
    setUploading(true);
    setFailed(null);
    setReplace(null);
    try {
      const b = await getJson<StrategyList & { added: StrategyInfo }>(
        "/engine/strategies",
        post({ filename: file.name, code: await file.text(), replace: again }),
      );
      onAdded(b);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      setFailed(text);
      if (alreadyExists(text)) setReplace(file);
    }
    setAdding(false);
    setUploading(false);
  }

  function choose(id: string) {
    setFailed(null);
    setReplace(null);
    if (id === ADD) {
      setAdding(true);
      input.current?.click();
      return;
    }
    setAdding(false);
    onPick(id);
  }

  const chosen = list.find((s) => s.id === pick);
  const groups = cats.map((name) => ({ name, items: list.filter((s) => s.category === name) })).filter((g) => g.items.length);
  const starter = (
    <button className="link" onClick={download}>
      starter file
    </button>
  );
  return (
    <>
      <select
        className="picker"
        aria-label="Strategy"
        value={adding ? ADD : pick}
        onChange={(e) => choose(e.target.value)}
        disabled={uploading}
      >
        {groups.map((g) => (
          <optgroup key={g.name} label={g.name}>
            {g.items.map((s) => (
              <option key={s.id} value={s.id} disabled={!!s.error} title={s.error ?? undefined}>
                {s.error ? `${s.name} (didn't load)` : s.name}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={ADD}>Add your own (.py)…</option>
      </select>
      <input ref={input} type="file" accept=".py" hidden onChange={(e) => send(e.target.files?.[0])} />
      {failed ? (
        <p className="small desc">
          <span className="error">{failed}</span>{" "}
          {replace && (
            <button className="link" onClick={() => send(replace, true)} disabled={uploading}>
              Replace it
            </button>
          )}{" "}
          <span className="muted">Start from the {starter}.</span>
        </p>
      ) : (
        <p className="small muted desc">
          {uploading
            ? "Adding your file…"
            : adding
              ? <>One Python file with <code>decide(matches, client)</code>. Start from the {starter}.</>
              : chosen
                ? `${chosen.description}${chosen.example ? " An example, not advice." : ""}`
                : null}
        </p>
      )}
    </>
  );
}

function StrategyMode() {
  const t = useTrade();
  const [list, setList] = useState<StrategyInfo[] | null>(null);
  const [cats, setCats] = useState<string[]>([]);
  const [pick, setPick] = useState("sports_favorite");
  const [noTrade, setNoTrade] = useState<{ text: string; retry: boolean } | null>(null);
  const [looked, setLooked] = useState<Looked[] | null>(null);
  const [allLooked, setAllLooked] = useState(false);
  const { fail } = t;

  useEffect(() => {
    getJson<StrategyList>("/engine/strategies")
      .then((b) => {
        setList(b.strategies);
        setCats(b.categories);
      })
      .catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function added(b: StrategyList & { added: StrategyInfo }) {
    setList(b.strategies);
    setPick(b.added.id);
  }

  async function run() {
    t.start();
    setNoTrade(null);
    setLooked(null);
    setAllLooked(false);
    try {
      // Each strategy picks its own markets: no search here.
      const qs = new URLSearchParams({ strategy: pick, limit: "50" });
      const r = await getJson<SignalResult>(`/engine/best/signal?${qs}`);
      if (r.signal) t.show(r.signal, "Your strategy picked", r.best);
      else {
        setNoTrade({ text: r.no_trade ?? `No trade: ${strategyNoTrade(r)}`, retry: !!r.unavailable });
        setLooked(r.unavailable ? [] : (r.looked ?? []));
      }
    } catch (e) {
      t.fail(e);
    }
    t.setBusy(null);
  }

  function compareFor(m: MatchView) {
    t.compare({ match_id: m.id, side: "yes", size: 100, max_price: null, why: "", match: m }, "You picked");
  }

  const noTradeRef = useShowWhenReady(noTrade);
  const chosen = list?.find((s) => s.id === pick);
  const runnable = chosen && !chosen.error;
  const shown = looked ? (allLooked ? looked : looked.slice(0, 5)) : [];
  return (
    <>
      {list && (
        <StrategyPicker
          list={list}
          cats={cats}
          pick={pick}
          onPick={setPick}
          onAdded={added}
        />
      )}

      <div className="controls run">
        <button className="btn big" onClick={run} disabled={t.busy !== null || !runnable}>
          {t.busy === "run" ? "Running…" : "Run"}
        </button>
      </div>

      <Working t={t} label="Running the strategy, then checking prices on both venues" />
      {noTrade && (
        <div className="result" ref={noTradeRef}>
          <h2 className="headline none">{noTrade.text}</h2>
          {noTrade.retry && <TryAgain onClick={run} busy={t.busy !== null} />}
          {shown.length > 0 && (
            <>
              <p className="lead">It looked at these. Compare one yourself:</p>
              <table className="t">
                <tbody>
                  {shown.map((m) => (
                    <tr key={m.id}>
                      <td>
                        {m.outcome ?? m.title}
                        {m.rule_warning && (
                          <span className="pill warn" style={{ marginLeft: 8 }} title={m.rule_warning}>
                            rules differ
                          </span>
                        )}
                        <div className="small muted">{m.title}</div>
                      </td>
                      <td className="num">
                        <button className="btn quiet" onClick={() => compareFor(m)} disabled={t.busy !== null}>
                          Compare
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                {!allLooked && looked && looked.length > 5 && (
                  <tfoot>
                    <tr>
                      <td colSpan={2}>
                        <button className="link" onClick={() => setAllLooked(true)}>
                          Show all {looked.length}
                        </button>
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </>
          )}
        </div>
      )}
      <TradeResult t={t} />
    </>
  );
}

export interface Game {
  key: string;
  title: string;
  time: string | null;
  outcomes: MatchView[];
}

/** Matches grouped into games by the engine's event_key: one match is one outcome of one game. */
export function gamesOf(found: MatchView[]): Game[] {
  const games: Game[] = [];
  for (const m of found) {
    const key = m.event_key ?? m.id;
    const g = games.find((x) => x.key === key);
    if (g) g.outcomes.push(m);
    else games.push({ key, title: m.title, time: m.event_time, outcomes: [m] });
  }
  return games;
}

function ManualMode() {
  const t = useTrade();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<MatchView[] | null>(null);
  const [searched, setSearched] = useState("");
  const [game, setGame] = useState("");
  const [mid, setMid] = useState("");
  const [mSide, setMSide] = useState<"yes" | "no">("yes");
  const [mSize, setMSize] = useState(100);
  const { fail } = t;

  function showFound(ms: MatchView[], words: string) {
    setFound(ms);
    setSearched(words);
    setGame(ms[0] ? (ms[0].event_key ?? ms[0].id) : "");
    setMid(ms[0]?.id ?? "");
  }

  async function find(words: string) {
    t.setBusy("find");
    try {
      const qs = new URLSearchParams({ limit: "30" });
      if (words.trim()) qs.set("q", words.trim());
      showFound((await getJson<{ matches: MatchView[] }>(`/engine/matches?${qs}`)).matches, words.trim());
    } catch (e) {
      t.fail(e);
    }
    t.setBusy(null);
  }

  // Open games are listed as soon as this opens: nothing to guess before the one button.
  useEffect(() => {
    getJson<{ matches: MatchView[] }>("/engine/matches?limit=30")
      .then((r) => showFound(r.matches, ""))
      .catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const games = gamesOf(found ?? []);
  const current = games.find((g) => g.key === game);
  const picked = current?.outcomes.find((m) => m.id === mid);

  function compare() {
    if (!picked) return;
    t.compare({ match_id: picked.id, side: mSide, size: mSize, max_price: null, why: "", match: picked }, "Your trade");
  }

  return (
    <>
      <div className="controls">
        <label className="field grow">
          Search a game
          <input
            className="search"
            value={q}
            placeholder="e.g. nba, yankees (blank: all open games)"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && find(q)}
          />
        </label>
        <button className="btn quiet" onClick={() => find(q)} disabled={t.busy !== null}>
          {t.busy === "find" ? "Searching…" : "Search"}
        </button>
      </div>
      {found === null && !t.error && (
        <div className="status">
          <span className="dot" /> Loading open games
        </div>
      )}
      {found && !found.length && (
        <p className="lead">{searched ? "No game on both venues matches that search." : "No game is open on both venues right now."}</p>
      )}
      {current && (
        <>
          <div className="controls">
            <label className="field grow">
              Game
              <select
                value={game}
                onChange={(e) => {
                  setGame(e.target.value);
                  setMid(games.find((g) => g.key === e.target.value)?.outcomes[0]?.id ?? "");
                }}
              >
                {games.map((g) => (
                  <option key={g.key} value={g.key}>
                    {g.title}
                    {when(g.time) ? ` · ${when(g.time)}` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field">
            Outcome
            <div className="outcomes">
              {current.outcomes.map((m) => (
                <button key={m.id} aria-pressed={m.id === mid} className={`outcome ${m.id === mid ? "current" : ""}`} onClick={() => setMid(m.id)}>
                  {m.outcome ?? m.title}
                  {m.rule_warning ? <span className="warn-dot" title={m.rule_warning} /> : null}
                </button>
              ))}
            </div>
          </div>
          <div className="controls" style={{ marginTop: 14 }}>
            <div className="field">
              Side
              <div className="switch tight">
                {(["yes", "no"] as const).map((s) => (
                  <button key={s} aria-pressed={mSide === s} className={mSide === s ? "current" : ""} onClick={() => setMSide(s)}>
                    {side(s)}
                  </button>
                ))}
              </div>
            </div>
            <label className="field narrow">
              Contracts
              <input type="number" min={1} value={mSize} onChange={(e) => setMSize(Math.max(1, +e.target.value || 1))} />
            </label>
            <button className="btn big" onClick={compare} disabled={t.busy !== null || !picked}>
              {t.busy === "run" ? "Comparing…" : "Compare venues"}
            </button>
          </div>
        </>
      )}
      <Working t={t} />
      <TradeResult t={t} />
    </>
  );
}

// ---- Every market: the next markets in a category, each compared, biggest saving first ------------

// Layer's categories, named as the strategy picker names them (engine/spread_engine/every_market.py).
const EVERY_CATEGORIES = [
  { id: "sports", name: "Sports" },
  { id: "news", name: "News, politics & economics" },
  { id: "crypto", name: "Crypto" },
] as const;
const EVERY_LIMIT = 25;
const EVERY_SIZE = 100;

interface EveryScan {
  total: number | null; // null until the engine has listed the markets
  rows: EveryRow[];
  empty: string | null;
  counts: Record<EveryOutcome, number> | null; // set when it's done
}

/** One venue's price for the row: the chance it gives YES, with the price in cents. */
function EveryPrice({ r, venue }: { r: EveryRow; venue: "kalshi" | "polymarket_us" }) {
  const v = r.best.compare?.venues.find((x) => x.venue === venue);
  return (
    <span className={`every-price ${v?.cheaper ? "cheaper" : ""} ${v && !v.ok ? "out" : ""}`} data-venue={VENUE_NAME[venue]}>
      {v?.chance_label ?? "—"}
      {v?.price_label && <span className="small muted"> · {v.price_label}</span>}
    </span>
  );
}

function EveryMarketMode() {
  const t = useTrade();
  const [category, setCategory] = useState<string>("sports");
  const [scan, setScan] = useState<EveryScan | null>(null);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stop = useRef<AbortController | null>(null);

  useEffect(() => () => stop.current?.abort(), []); // leaving the page stops the scan

  async function run() {
    stop.current?.abort();
    const ctl = new AbortController();
    stop.current = ctl;
    setRunning(true);
    setOpen(null);
    setError(null);
    setScan({ total: null, rows: [], empty: null, counts: null });
    try {
      const r = await fetch("/engine/best/scan", { ...post({ category, limit: EVERY_LIMIT, size: EVERY_SIZE }), signal: ctl.signal });
      if (!r.ok || !r.body) throw new Error(errorText(await r.json().catch(() => null), r.status));
      for await (const e of ndjson<EveryEvent>(r.body)) {
        if (e.type === "start") setScan((s) => s && { ...s, total: e.total, empty: e.empty });
        else if (e.type === "row") setScan((s) => s && { ...s, rows: [...s.rows, e] });
        else if (e.type === "done") setScan((s) => s && { ...s, counts: e.counts });
      }
    } catch (e) {
      if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    }
    if (stop.current === ctl) setRunning(false);
  }

  function pick(r: EveryRow) {
    if (open === r.match.id) return setOpen(null);
    setOpen(r.match.id);
    t.show({ ...r.order, why: "", match: r.match }, "You picked", r.best);
  }

  const rows = scan ? [...scan.rows].sort(everyOrder) : [];
  const name = EVERY_CATEGORIES.find((c) => c.id === category)?.name.toLowerCase();
  return (
    <>
      <div className="controls">
        <label className="field">
          Markets
          <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={running}>
            {EVERY_CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button className="btn big" onClick={run} disabled={running}>
          {running ? "Checking…" : "Check every market"}
        </button>
        {running && (
          <button className="link" onClick={() => stop.current?.abort()}>
            Stop
          </button>
        )}
      </div>
      <p className="small muted hint">
        The next {EVERY_LIMIT} markets on both venues, soonest first: where {EVERY_SIZE} YES costs less, after fees.
      </p>

      {scan && running && (
        <div className="status">
          <span className="dot" />
          {scan.total == null
            ? `Finding the next ${EVERY_LIMIT} ${name} markets on both venues`
            : `Checked ${count(scan.rows.length)} of ${count(scan.total)}`}
        </div>
      )}
      {scan && !running && !scan.counts && !error && scan.total != null && scan.total > 0 && (
        <p className="small muted">Stopped after {count(scan.rows.length)} of {count(scan.total)}.</p>
      )}
      {error && <p className="error">{error}</p>}
      {scan?.empty && <h2 className="headline none">{scan.empty}</h2>}
      {scan?.counts && scan.total ? <p className="lead every-summary">{everySummary(scan.counts, scan.total)}</p> : null}

      {rows.length > 0 && (
        <div className="every" role="list">
          <div className="every-head" aria-hidden>
            <span>Market</span>
            <span>Kalshi</span>
            <span>Polymarket US</span>
            <span>
              Cheaper for {EVERY_SIZE} YES, after fees
            </span>
          </div>
          {rows.map((r) => {
            const cell = everyCell(r);
            const t0 = when(r.match.event_time);
            return (
              <div key={r.match.id} role="listitem">
                <button className={`every-row ${open === r.match.id ? "current" : ""}`} aria-expanded={open === r.match.id} onClick={() => pick(r)}>
                  <span className="every-market">
                    <span className="every-outcome">{r.match.outcome ?? r.match.title}</span>
                    <span className="small muted">
                      {r.match.title}
                      {t0 ? ` · ${t0}` : ""}
                    </span>
                    {r.match.rule_warning && (
                      <span className="pill warn" title={r.match.rule_warning}>
                        Rules differ
                      </span>
                    )}
                  </span>
                  <EveryPrice r={r} venue="kalshi" />
                  <EveryPrice r={r} venue="polymarket_us" />
                  <span className={`every-best ${r.outcome}`}>
                    <span className="every-best-title">{cell.title}</span>
                    {cell.detail && <span className="small muted">{cell.detail}</span>}
                  </span>
                </button>
                {open === r.match.id && (
                  <>
                    <TradeResult t={t} />
                    {t.error && <p className="error">{t.error}</p>}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default function BestVenue() {
  const [how, setHow] = useState<How>(DEFAULT_HOW);
  return (
    <section>
      <p className="tab-lead">
        Pick a game, or run a strategy. Spread finds the same market on Kalshi and Polymarket US and shows where your order is cheaper, after fees.
      </p>
      <div className="switch" role="tablist">
        {HOW.map((h) => (
          <button key={h.id} role="tab" aria-selected={how === h.id} className={how === h.id ? "current" : ""} onClick={() => setHow(h.id)}>
            {h.label}
          </button>
        ))}
      </div>
      {/* Each stays mounted, with its own trade: switching never shows another mode's result. */}
      <div hidden={how !== "manual"}>
        <ManualMode />
      </div>
      <div hidden={how !== "strategy"}>
        <StrategyMode />
      </div>
      <div hidden={how !== "every"}>
        <EveryMarketMode />
      </div>
    </section>
  );
}
