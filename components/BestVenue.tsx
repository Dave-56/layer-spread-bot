"use client";

import { useEffect, useRef, useState } from "react";
import {
  errorText,
  VENUE_NAME,
  type BestResult,
  type BestVenue as Why,
  type CompareView,
  type MatchView,
  type Signal,
  type StrategyInfo,
  type StrategyList,
} from "@/lib/engine";
import { cents, count, money, side, SKIP, when } from "./format";
import { alreadyExists, bestHeadline, matchNote, strategyNoTrade } from "./headlines";
import { fetchAccount, traded, type Account } from "./PaperAccount";

// Job 1: your strategy already knows the trade. The bot prices that exact order on both venues,
// after fees and depth, and sends it where it's cheaper for that size.
//
// The flow: choose (a template, your own file, or a game by hand) → run → the match, the two
// venues' markets side by side, and the answer: where to buy, and by how much it's cheaper.
// Every number and label is the engine's (BestResult.compare); nothing is computed here.

const ADD_YOUR_OWN = "https://github.com/Dave-56/layer-spread-bot#add-your-own";
const YOUR_OWN = "Your own";
const upper = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// ---- Used by the chat panel and the Arbitrage tab ------------------------------------------------

/** The SDK's comparison as one sentence, from its own numbers. */
export function verdictLine(why: Why): string {
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

export function CompareTable({ why }: { why: Why }) {
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
          <tr key={v.venue} className={v.venue === why.venue ? "chosen" : undefined}>
            <td>
              {VENUE_NAME[v.venue] ?? v.venue}{" "}
              {v.venue === why.venue && <span className="pill good">cheaper</span>}
              {v.skip && (
                <div className="small muted">
                  Skipped: {SKIP[v.skip] ?? v.skip.replaceAll("_", " ")}
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

/** A quiet warning: the two venues word this bet differently, so they could settle differently. */
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
                    <div className="small muted">{upper(v.skip_reason ?? "can't fill it.")}</div>
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
              {!v.ok && v.skip_reason && <div className="small muted">{v.skip_reason}</div>}
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
  no_trade?: string | null; // the strategy's own sentence
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

type Busy = null | "run" | "find" | "buy";

/** One trade being compared and maybe bought. Each mode has its own, so nothing leaks between them. */
function useTrade() {
  const [trade, setTrade] = useState<(Signal & { picked: string }) | null>(null);
  const [best, setBest] = useState<BestResult | null>(null);
  const [order, setOrder] = useState<BestResult | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [acct, setAcct] = useState<Account | null>(null);

  // After the paper account is reset, price the same trade again: the old answer is stale.
  useEffect(() => {
    const again = () => {
      if (!trade) return;
      setOrder(null);
      getJson<BestResult>("/engine/best/preview", post(orderOf(trade)))
        .then(setBest)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    };
    window.addEventListener("spread:reset", again);
    return () => window.removeEventListener("spread:reset", again);
  }, [trade]);

  // A budget block is explained with the account's own numbers.
  const budgetBlocked = best?.preview?.blocked_by === "budget";
  useEffect(() => {
    if (budgetBlocked) fetchAccount().then(setAcct).catch(() => setAcct(null));
  }, [budgetBlocked, best]);

  function start(what: Exclude<Busy, null>) {
    setBusy(what);
    setError(null);
    if (what === "run") {
      setOrder(null);
      setTrade(null);
      setBest(null);
    }
  }
  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }
  function show(t: Signal, picked: string, b: BestResult | null) {
    setTrade({ ...t, picked });
    setBest(b);
  }
  async function compare(t: Signal, picked: string) {
    start("run");
    try {
      show(t, picked, await getJson<BestResult>("/engine/best/preview", post(orderOf(t))));
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }
  async function buy() {
    if (!trade) return;
    start("buy");
    try {
      setOrder(await getJson<BestResult>("/engine/best/buy", post(orderOf(trade))));
      traded();
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }
  return { trade, best, order, busy, error, acct, budgetBlocked, setBusy, start, fail, show, compare, buy };
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

/** The match, the two venues' markets, then the answer and the button. Numbers folded below. */
function TradeResult({ t, mode }: { t: Trade; mode: "paper" | "live" }) {
  const { trade, best, order, busy, acct, budgetBlocked } = t;
  const ref = useShowWhenReady(best);
  if (!trade || !best) return null;
  const c = best.ok ? best.compare : undefined;
  const p = best.preview;
  const chosen = c?.venues.find((v) => v.cheaper);
  // What the SDK's guardrails said about the chosen order, before anything is sent.
  const blocked =
    p && !p.allowed
      ? budgetBlocked && acct && chosen?.total_cost != null
        ? `Your ${acct.mode === "paper" ? "paper " : ""}account already has ${money(acct.at_risk)} in open trades. This ${money(chosen.total_cost)} order would take it over your ${money(acct.budget)} limit.`
        : [p.rules.decision.reason ?? (p.blocked_by ? `Blocked by ${p.blocked_by}.` : null), ...p.problems].filter(Boolean).join(" ")
      : null;
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
        <p className="error">
          {best.error?.message} {best.error?.hint}
        </p>
      )}
      {h && (
        <>
          <h2 className={`headline ${c?.cheaper ? "" : "none"}`}>{h.title}</h2>
          <p className="lead">{h.detail}</p>
        </>
      )}
      {c?.cheaper && blocked && (
        <div className="box warn">
          <div className="label">Over your limit</div>
          {blocked}
          <div className="small muted">
            {budgetBlocked
              ? mode === "paper"
                ? "Reset the paper account above, or raise your limit in .env."
                : "Raise your limit in .env, or close trades on the venue."
              : "Your safety limits are set in .env."}
          </div>
        </div>
      )}
      {c?.cheaper && !order?.order && (
        <div className="row">
          <button className="btn" onClick={t.buy} disabled={busy !== null || blocked !== null}>
            {busy === "buy"
              ? "Sending…"
              : mode === "live"
                ? `Send LIVE order to ${c.cheaper_name}`
                : `Paper-trade on ${c.cheaper_name}`}
          </button>
          <span className="small muted">
            {mode === "live" ? "Real money." : "Fake money."} Pays at most {cents(chosen?.limit_price)} a contract.
          </span>
        </div>
      )}
      {order?.order && (
        <div className="box good">
          {order.mode === "live" ? "Bought" : "Paper trade"} on {VENUE_NAME[order.order.venue]}: {count(order.order.filled)} of{" "}
          {count(order.order.size)} {side(order.order.side)} at {cents(order.order.avg_price)}, fees {money(order.order.fees)}.
        </div>
      )}
      {c && (
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

/** Add your own .py: the engine saves it in strategies/, checks it loads, and lists it. */
function AddYourOwn({ onAdded }: { onAdded: (b: StrategyList & { added: StrategyInfo }) => void }) {
  const [msg, setMsg] = useState<{ text: string; bad: boolean } | null>(null);
  const [replace, setReplace] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // The starter file (my_strategy.py), saved in the browser: edit it, rename it, upload it back.
  async function download() {
    try {
      const b = await getJson<{ filename: string; code: string }>("/engine/strategies/starter");
      const url = URL.createObjectURL(new Blob([b.code], { type: "text/x-python" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: b.filename });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : String(e), bad: true });
    }
  }

  async function send(file: File | undefined, again = false) {
    if (!file) return;
    setBusy(true);
    setMsg(null);
    setReplace(null);
    try {
      const b = await getJson<StrategyList & { added: StrategyInfo }>(
        "/engine/strategies",
        post({ filename: file.name, code: await file.text(), replace: again }),
      );
      setMsg({ text: `Added ${file.name}: it's now "${b.added.name}" under ${b.added.category}.`, bad: false });
      onAdded(b);
    } catch (e) {
      const text = e instanceof Error ? e.message : String(e);
      setMsg({ text, bad: true });
      if (alreadyExists(text)) setReplace(file);
    }
    setBusy(false);
    if (input.current) input.current.value = "";
  }

  return (
    <div className="card add">
      <div className="card-name">Add your own</div>
      <div className="card-desc">
        One Python file with <code>decide(matches, client)</code>. It returns the trade, or None for no trade.{" "}
        <a href={ADD_YOUR_OWN}>How</a>
      </div>
      <div className="row">
        <button className="btn quiet" onClick={() => input.current?.click()} disabled={busy}>
          {busy ? "Uploading…" : "Upload a .py file"}
        </button>
        <input ref={input} type="file" accept=".py" hidden onChange={(e) => send(e.target.files?.[0])} />
        <button className="link" onClick={download}>
          Download the starter file
        </button>
        {replace && (
          <button className="btn quiet" onClick={() => send(replace, true)} disabled={busy}>
            Replace it
          </button>
        )}
      </div>
      {msg && <div className={`small ${msg.bad ? "error" : "muted"}`}>{msg.text}</div>}
    </div>
  );
}

function StrategyMode({ mode }: { mode: "paper" | "live" }) {
  const t = useTrade();
  const [list, setList] = useState<StrategyInfo[] | null>(null);
  const [cats, setCats] = useState<string[]>([]);
  const [pick, setPick] = useState("sports_favorite");
  const [noTrade, setNoTrade] = useState<string | null>(null);
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
    t.start("run");
    setNoTrade(null);
    setLooked(null);
    setAllLooked(false);
    try {
      // Each strategy picks its own markets: no search here.
      const qs = new URLSearchParams({ strategy: pick, limit: "50" });
      const r = await getJson<SignalResult>(`/engine/best/signal?${qs}`);
      if (r.signal) t.show(r.signal, "Your strategy picked", r.best);
      else {
        setNoTrade(r.no_trade ?? `No trade: ${strategyNoTrade(r)}`);
        setLooked(r.looked ?? []);
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
  // The engine's categories, in its order. "Your own" is always shown: it holds the upload card.
  const groups = cats
    .map((name) => ({ name, items: (list ?? []).filter((s) => s.category === name) }))
    .filter((g) => g.items.length || g.name === YOUR_OWN);
  return (
    <>
      {list && <p className="small muted hint">Examples, not advice.</p>}
      {groups.map((g) => (
        <div key={g.name} className="card-group">
          <div className="label">{g.name}</div>
          <div className="cards">
            {g.items.map((s) => (
              <button
                key={s.id}
                aria-pressed={s.id === pick}
                className={`card ${s.id === pick ? "current" : ""}`}
                onClick={() => setPick(s.id)}
                disabled={!!s.error}
              >
                <span className="card-name">{s.name}</span>
                <span className={`card-desc ${s.error ? "bad" : ""}`}>{s.error ? `Didn't load. ${s.error}` : s.description}</span>
              </button>
            ))}
            {g.name === YOUR_OWN && <AddYourOwn onAdded={added} />}
          </div>
        </div>
      ))}

      <div className="controls run">
        <button className="btn big" onClick={run} disabled={t.busy !== null || !runnable}>
          {t.busy === "run" ? "Running…" : chosen ? `Run “${chosen.name}”` : "Run strategy"}
        </button>
      </div>

      <Working t={t} label="Running the strategy, then checking prices on both venues" />
      {noTrade && (
        <div className="result" ref={noTradeRef}>
          <h2 className="headline none">{noTrade}</h2>
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
                            worded differently
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
      <TradeResult t={t} mode={mode} />
    </>
  );
}

interface Game {
  key: string;
  title: string;
  time: string | null;
  outcomes: MatchView[];
}

/** Matches grouped into games by the engine's event_key: one match is one outcome of one game. */
function gamesOf(found: MatchView[]): Game[] {
  const games: Game[] = [];
  for (const m of found) {
    const key = m.event_key ?? m.id;
    const g = games.find((x) => x.key === key);
    if (g) g.outcomes.push(m);
    else games.push({ key, title: m.title, time: m.event_time, outcomes: [m] });
  }
  return games;
}

function ManualMode({ mode }: { mode: "paper" | "live" }) {
  const t = useTrade();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<MatchView[] | null>(null);
  const [searched, setSearched] = useState("");
  const [game, setGame] = useState("");
  const [mid, setMid] = useState("");
  const [mSide, setMSide] = useState<"yes" | "no">("yes");
  const [mSize, setMSize] = useState(100);
  const [mMax, setMMax] = useState("");
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
    const max = mMax.trim() ? Number(mMax) / 100 : null;
    t.compare({ match_id: picked.id, side: mSide, size: mSize, max_price: max, why: "", match: picked }, "Your trade");
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
          <RuleNote text={picked?.rule_warning} />
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
            <details className="settings">
              <summary>Settings</summary>
              <label className="field">
                Max price (¢, optional)
                <input type="number" min={1} max={99} value={mMax} placeholder="none" onChange={(e) => setMMax(e.target.value)} />
              </label>
            </details>
          </div>
        </>
      )}
      <Working t={t} />
      <TradeResult t={t} mode={mode} />
    </>
  );
}

export default function BestVenue({ mode }: { mode: "paper" | "live" }) {
  const [how, setHow] = useState<"strategy" | "manual">("strategy");
  const [opened, setOpened] = useState(false);
  return (
    <section>
      <p className="tab-lead">
        Pick a strategy and run it. Spread finds the same market on Kalshi and Polymarket US and buys where it&apos;s cheaper, after fees.
      </p>
      <div className="switch" role="tablist">
        <button className={how === "strategy" ? "current" : ""} onClick={() => setHow("strategy")}>
          Run a strategy
        </button>
        <button
          className={how === "manual" ? "current" : ""}
          onClick={() => {
            setHow("manual");
            setOpened(true);
          }}
        >
          Pick a game yourself
        </button>
      </div>
      {/* Both stay mounted, each with its own trade: switching never shows the other mode's result. */}
      <div hidden={how !== "strategy"}>
        <StrategyMode mode={mode} />
      </div>
      {opened && (
        <div hidden={how !== "manual"}>
          <ManualMode mode={mode} />
        </div>
      )}
    </section>
  );
}
