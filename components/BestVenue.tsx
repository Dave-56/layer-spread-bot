"use client";

import { useEffect, useRef, useState } from "react";
import {
  errorText,
  VENUE_NAME,
  type BestResult,
  type BestVenue as Why,
  type MatchView,
  type Signal,
  type StrategyInfo,
  type VenueCost,
} from "@/lib/engine";
import { CAVEAT, cents, count, money, side, SKIP, when } from "./format";
import { bestHeadline, chance, strategyNoTrade } from "./headlines";
import { fetchAccount, traded, type Account } from "./PaperAccount";

// Job 1: your strategy already knows the trade. The bot prices that exact order on both venues,
// after fees and depth, and sends it where it's cheaper for that size.
//
// The flow: choose (a template, your own file, or a game by hand) → run → the match, the two
// venues' markets side by side, and the answer: where to buy, and by how much it's cheaper.

const ADD_YOUR_OWN = "https://github.com/Dave-56/layer-spread-bot#add-your-strategy";
const VENUES = ["kalshi", "polymarket_us"] as const;

// ---- TODO(engine adapters) -------------------------------------------------------------------
// The implementation engineer (branch spread-bot-rule-warnings-and-sizes) is adding strategy
// CATEGORY, an upload route, and per-venue probability. Until the field names are final, these read
// them if present and fall back to what the engine returns today. Swap the names here only.

/** A strategy's group: the engine's CATEGORY (Sports, Crypto, News…) once it sends one. */
function categoryOf(s: StrategyInfo): string {
  const c = (s as StrategyInfo & { category?: string | null }).category;
  return c || (s.example ? "Templates" : "Yours");
}

/** One venue's price as a chance: the engine's probability once it sends one, else its best price. */
function probabilityOf(v: VenueCost): number | null {
  const p = (v as VenueCost & { probability?: number | null }).probability;
  return p ?? v.best_price;
}

/** Upload a strategy file. Assumed route: POST /strategies/upload {filename, source} → {id}. */
async function uploadStrategy(file: File): Promise<{ id: string | null } | { missing: true }> {
  const r = await fetch("/engine/strategies/upload", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ filename: file.name, source: await file.text() }),
  });
  if (r.status === 404 || r.status === 405) return { missing: true };
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(errorText(body, r.status));
  const b = body as { id?: string; strategy?: { id?: string } } | null;
  return { id: b?.id ?? b?.strategy?.id ?? null };
}
// ------------------------------------------------------------------------------------------------

/** Both venues' numbers for one order. Also used by the chat panel. */
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
                  Skipped: {SKIP[v.skip] ?? v.skip}
                  {v.detail ? `. ${v.detail}` : ""}
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

/** The SDK's comparison as one sentence (the chat panel). */
export function verdictLine(why: Why): string {
  const h = bestHeadline(why);
  return `${h.title}. ${h.detail}`;
}

/** One line under a market: event, time, both venues' links. Used by the Arbitrage tab and the chat. */
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

/** A quiet warning: the two venues word this bet differently, so they could pay out differently. */
function RuleNote({ caveats, text }: { caveats: string[]; text?: string | null }) {
  if (!text && !caveats.length) return null;
  return (
    <div className="rule-note">
      <b>Worded differently</b>: {text ?? `${caveats.map((c) => CAVEAT[c] ?? c).join(", ")}. The venues could pay out differently.`}
    </div>
  );
}

/** The match, Polymarket-style: the outcome big, then each venue's market side by side with its chance. */
function MarketCard({ m, why, sideName }: { m: MatchView; why?: Why; sideName: string }) {
  const t = when(m.event_time);
  return (
    <div className="market">
      <div className="market-event">
        {m.title}
        {t ? ` · ${t}` : ""}
      </div>
      <div className="market-outcome">{m.outcome ?? m.title}</div>
      <div className="market-venues">
        {VENUES.map((venue) => {
          const mk = m[venue];
          const v = why?.venues.find((x) => x.venue === venue);
          const cheaper = why?.venue === venue;
          return (
            <div key={venue} className={`venue-cell ${cheaper ? "cheaper" : ""} ${v && !v.ok ? "out" : ""}`}>
              <div className="venue-name">
                {VENUE_NAME[venue]}
                {cheaper && <span className="pill good">Cheaper</span>}
              </div>
              <div className="venue-q">{mk.question ?? mk.event ?? mk.market_id}</div>
              {v && (
                <>
                  <div className="venue-chance">{v.ok ? chance(probabilityOf(v)) : "—"}</div>
                  <div className="small muted">
                    {v.ok ? `${sideName} at ${cents(v.best_price)}` : (SKIP[v.skip ?? ""] ?? v.skip ?? "can't fill it")}
                  </div>
                </>
              )}
              {mk.url && (
                <a className="small venue-link" href={mk.url} target="_blank" rel="noreferrer">
                  Open on {VENUE_NAME[venue]} ↗
                </a>
              )}
            </div>
          );
        })}
      </div>
      <div className="matched">Matched by Layer: the same bet on both venues.</div>
      <RuleNote caveats={m.caveats} />
    </div>
  );
}

interface Looked extends MatchView {
  reason: string;
}

interface SignalResult {
  signal: Signal | null;
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

/** The match, the two venues' markets, then the answer and the button. Numbers folded below. */
/** Bring a new result into view: on a laptop screen it lands below the chooser. */
function useShowWhenReady(key: unknown) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (key) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [key]);
  return ref;
}

function TradeResult({ t, mode }: { t: Trade; mode: "paper" | "live" }) {
  const { trade, best, order, busy, acct, budgetBlocked } = t;
  const ref = useShowWhenReady(best);
  if (!trade || !best) return null;
  const why = best.ok ? best.why : undefined;
  const sideName = side(trade.side);
  const p = best.preview;
  const chosen = why?.venues.find((v) => v.venue === why.venue);
  // What the SDK's guardrails said about the chosen order, before anything is sent.
  const blocked =
    p && !p.allowed
      ? budgetBlocked && acct && chosen?.all_in != null
        ? `Your ${acct.mode === "paper" ? "paper " : ""}account already has ${money(acct.at_risk)} in open trades. This ${money(chosen.all_in)} order would take it over your ${money(acct.budget)} limit.`
        : [p.rules.decision.reason ?? (p.blocked_by ? `Blocked by ${p.blocked_by}.` : null), ...p.problems].filter(Boolean).join(" ")
      : null;
  const h = why ? bestHeadline(why) : null;
  return (
    <div className="result" ref={ref}>
      <div className="kicker">
        {trade.picked}: buy {count(trade.size)} {sideName}
        {trade.max_price != null ? `, at most ${cents(trade.max_price)} each` : ""}
        {trade.why ? <span className="muted"> · {trade.why}</span> : null}
      </div>
      <MarketCard m={trade.match} why={why} sideName={sideName} />

      {!best.ok && (
        <p className="error">
          {best.error?.message} {best.error?.hint}
        </p>
      )}
      {h && (
        <>
          <h2 className={`headline ${why?.venue ? "" : "none"}`}>{h.title}</h2>
          <p className="lead">{h.detail}</p>
        </>
      )}
      {why?.venue && blocked && (
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
      {why?.venue && !order?.order && (
        <div className="row">
          <button className="btn" onClick={t.buy} disabled={busy !== null || blocked !== null}>
            {busy === "buy"
              ? "Sending…"
              : mode === "live"
                ? `Send LIVE order to ${VENUE_NAME[why.venue]}`
                : `Paper-trade on ${VENUE_NAME[why.venue]}`}
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
      {why && (
        <details className="fold">
          <summary>Price, fees and size on each venue</summary>
          <CompareTable why={why} />
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

/** Strategy names from the examples start with "Example:"; the group already says so. */
const cardName = (s: StrategyInfo) => s.name.replace(/^Example:\s*/, "").replace(/^./, (c) => c.toUpperCase());

function AddYourOwn({ onAdded }: { onAdded: (id: string | null) => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function pickFile(file: File | undefined) {
    if (!file) return;
    if (!file.name.endsWith(".py")) {
      setMsg("Pick a .py file.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const r = await uploadStrategy(file);
      if ("missing" in r)
        setMsg("This engine can't take uploads yet. Copy the file into engine/spread_engine/strategies/ and reload.");
      else {
        setMsg(`Added ${file.name}.`);
        onAdded(r.id);
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
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
        <input ref={input} type="file" accept=".py,text/x-python" hidden onChange={(e) => pickFile(e.target.files?.[0])} />
        {msg && <span className="small muted">{msg}</span>}
      </div>
    </div>
  );
}

function StrategyMode({ mode }: { mode: "paper" | "live" }) {
  const t = useTrade();
  const [list, setList] = useState<StrategyInfo[] | null>(null);
  const [pick, setPick] = useState("first_match");
  const [q, setQ] = useState("");
  const [noTrade, setNoTrade] = useState<string | null>(null);
  const [looked, setLooked] = useState<Looked[] | null>(null);
  const [allLooked, setAllLooked] = useState(false);
  const { fail } = t;

  function load(select?: string | null) {
    getJson<{ strategies: StrategyInfo[] }>("/engine/strategies")
      .then((b) => {
        setList(b.strategies);
        if (select) setPick(select);
      })
      .catch(fail);
  }
  useEffect(() => {
    getJson<{ strategies: StrategyInfo[] }>("/engine/strategies")
      .then((b) => setList(b.strategies))
      .catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run() {
    t.start("run");
    setNoTrade(null);
    setLooked(null);
    setAllLooked(false);
    try {
      const qs = new URLSearchParams({ strategy: pick, limit: "50" });
      if (q.trim()) qs.set("q", q.trim());
      const r = await getJson<SignalResult>(`/engine/best/signal?${qs}`);
      if (r.signal) t.show(r.signal, "Your strategy picked", r.best);
      else {
        const s = list?.find((x) => x.id === pick);
        setNoTrade(strategyNoTrade(r, s && { example: s.example, category: (s as { category?: string | null }).category }, !!q.trim()));
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

  // Templates grouped by category, in the engine's order; your own files last.
  const groups: { name: string; items: StrategyInfo[] }[] = [];
  const yours = "Yours";
  for (const s of list ?? []) {
    const name = categoryOf(s);
    const g = groups.find((x) => x.name === name);
    if (g) g.items.push(s);
    else groups.push({ name, items: [s] });
  }
  const noTradeRef = useShowWhenReady(noTrade);
  const chosen = list?.find((s) => s.id === pick);
  const shown = looked ? (allLooked ? looked : looked.slice(0, 5)) : [];
  return (
    <>
      {groups.map((g) => (
        <div key={g.name} className="card-group">
          <div className="label">
            {g.name}
            {g.name === "Templates" ? <span className="muted"> · examples, not advice</span> : null}
          </div>
          <div className="cards">
            {g.items.map((s) => (
              <button
                key={s.id}
                aria-pressed={s.id === pick}
                className={`card ${s.id === pick ? "current" : ""}`}
                onClick={() => setPick(s.id)}
              >
                <span className="card-name">{cardName(s)}</span>
                <span className="card-desc">{s.description}</span>
              </button>
            ))}
            {g.name === yours && <AddYourOwn onAdded={load} />}
          </div>
        </div>
      ))}
      {!groups.some((g) => g.name === yours) && list && (
        <div className="card-group">
          <div className="label">Yours</div>
          <div className="cards">
            <AddYourOwn onAdded={load} />
          </div>
        </div>
      )}

      <div className="controls run">
        <button className="btn big" onClick={run} disabled={t.busy !== null || !chosen}>
          {t.busy === "run" ? "Running…" : chosen ? `Run “${cardName(chosen)}”` : "Run strategy"}
        </button>
        <details className="settings">
          <summary>Settings</summary>
          <label className="field">
            Markets it looks at
            <input
              className="search"
              value={q}
              placeholder="search, e.g. nba (blank: all)"
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
          </label>
        </details>
      </div>

      <Working t={t} label="Running the strategy, then checking prices on both venues" />
      {noTrade && (
        <div className="result" ref={noTradeRef}>
          <h2 className="headline none">No trade</h2>
          <p className="lead">{noTrade}</p>
          {shown.length > 0 && (
            <table className="t">
              <tbody>
                {shown.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.outcome ?? m.title}
                      {m.caveats.length > 0 && (
                        <span className="pill warn" style={{ marginLeft: 8 }} title={m.caveats.map((c) => CAVEAT[c] ?? c).join(", ")}>
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
          )}
        </div>
      )}
      <TradeResult t={t} mode={mode} />
    </>
  );
}

/** Matches grouped into games: one Layer match is one outcome of one event. */
function gamesOf(found: MatchView[]): { title: string; time: string | null; outcomes: MatchView[] }[] {
  const games: { title: string; time: string | null; outcomes: MatchView[] }[] = [];
  for (const m of found) {
    const g = games.find((x) => x.title === m.title);
    if (g) g.outcomes.push(m);
    else games.push({ title: m.title, time: m.event_time, outcomes: [m] });
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
    setGame(ms[0]?.title ?? "");
    setMid(ms[0]?.id ?? "");
  }

  async function find(words: string) {
    t.setBusy("find");
    try {
      const qs = new URLSearchParams({ limit: "50" });
      if (words.trim()) qs.set("q", words.trim());
      showFound((await getJson<{ matches: MatchView[] }>(`/engine/matches?${qs}`)).matches, words.trim());
    } catch (e) {
      t.fail(e);
    }
    t.setBusy(null);
  }

  // Open games are listed as soon as this opens: nothing to guess before the one button.
  useEffect(() => {
    getJson<{ matches: MatchView[] }>("/engine/matches?limit=50")
      .then((r) => showFound(r.matches, ""))
      .catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const games = gamesOf(found ?? []);
  const current = games.find((g) => g.title === game);

  function compare() {
    const m = found?.find((x) => x.id === mid);
    if (!m) return;
    const max = mMax.trim() ? Number(mMax) / 100 : null;
    t.compare({ match_id: m.id, side: mSide, size: mSize, max_price: max, why: "", match: m }, "Your trade");
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
                  setMid(games.find((g) => g.title === e.target.value)?.outcomes[0]?.id ?? "");
                }}
              >
                {games.map((g) => (
                  <option key={g.title} value={g.title}>
                    {g.title}
                    {when(g.time) ? ` · ${when(g.time)}` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="field">
            Outcome
            <div className="outcomes" role="radiogroup" aria-label="Outcome">
              {current.outcomes.map((m) => (
                <button
                  key={m.id}
                  role="radio"
                  aria-checked={m.id === mid}
                  className={`outcome ${m.id === mid ? "current" : ""}`}
                  onClick={() => setMid(m.id)}
                >
                  {m.outcome ?? m.title}
                  {m.caveats.length ? <span className="warn-dot" title="Worded differently on the two venues" /> : null}
                </button>
              ))}
            </div>
          </div>
          <div className="controls" style={{ marginTop: 14 }}>
            <div className="field">
              Side
              <div className="switch tight" role="radiogroup" aria-label="Side">
                {(["yes", "no"] as const).map((s) => (
                  <button key={s} role="radio" aria-checked={mSide === s} className={mSide === s ? "current" : ""} onClick={() => setMSide(s)}>
                    {side(s)}
                  </button>
                ))}
              </div>
            </div>
            <label className="field narrow">
              Contracts
              <input type="number" min={1} value={mSize} onChange={(e) => setMSize(Math.max(1, +e.target.value || 1))} />
            </label>
            <button className="btn big" onClick={compare} disabled={t.busy !== null || !mid}>
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
