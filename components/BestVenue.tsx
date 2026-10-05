"use client";

import { useEffect, useState } from "react";
import {
  errorText,
  VENUE_NAME,
  type BestResult,
  type BestVenue as Why,
  type MatchView,
  type Signal,
  type StrategyInfo,
} from "@/lib/engine";
import { CAVEAT, cents, count, money, side, SKIP, when } from "./format";
import { fetchAccount, traded, type Account } from "./PaperAccount";

// Job 1: your strategy already knows the trade. The bot prices that exact order on both venues,
// after fees and depth, and sends it where it's cheaper for that size.

const ADD_YOUR_OWN = "https://github.com/Dave-56/layer-spread-bot#add-your-strategy";

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

/** Why a strategy made no trade, in one plain sentence. */
function noTradeLine(r: SignalResult, s: StrategyInfo | undefined): string {
  const started = r.started ?? 0;
  const looked = r.looked ?? [];
  if (!looked.length && started) return `No trade: all ${started} games had already started.`;
  if (!looked.length) return "No trade: no matched markets for that search.";
  const worded = looked.filter((m) => m.reason === "rules differ").length;
  if (worded === looked.length) return `No trade: Kalshi and Polymarket US word these ${worded} bets differently.`;
  return `No trade: nothing fit ${s?.example ? "the example's" : "your strategy's"} rules. Pick a market below to compare.`;
}

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(errorText(body, r.status));
  return body as T;
}

export default function BestVenue({ mode }: { mode: "paper" | "live" }) {
  const [how, setHow] = useState<"strategy" | "manual">("strategy");
  const [q, setQ] = useState("");
  const [list, setList] = useState<StrategyInfo[]>([]);
  const [pick, setPick] = useState("first_match");
  // manual: a market from the search, side, contracts, max price
  const [found, setFound] = useState<MatchView[] | null>(null);
  const [mid, setMid] = useState("");
  const [mSide, setMSide] = useState<"yes" | "no">("yes");
  const [mSize, setMSize] = useState(100);
  const [mMax, setMMax] = useState("");
  // the trade being compared, the comparison, the order sent
  const [trade, setTrade] = useState<Signal | null>(null);
  const [noTrade, setNoTrade] = useState<string | null>(null);
  const [looked, setLooked] = useState<Looked[] | null>(null);
  const [allLooked, setAllLooked] = useState(false);
  const [best, setBest] = useState<BestResult | null>(null);
  const [order, setOrder] = useState<BestResult | null>(null);
  const [busy, setBusy] = useState<null | "run" | "find" | "buy">(null);
  const [error, setError] = useState<string | null>(null);
  const [acct, setAcct] = useState<Account | null>(null);

  useEffect(() => {
    getJson<{ strategies: StrategyInfo[] }>("/engine/strategies")
      .then((b) => setList(b.strategies))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // After the paper account is reset, price the same trade again: the old verdict is stale.
  useEffect(() => {
    const again = () => {
      if (!trade) return;
      setOrder(null);
      getJson<BestResult>("/engine/best/preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: trade.match_id, side: trade.side, size: trade.size, max_price: trade.max_price }),
      })
        .then(setBest)
        .catch(fail);
    };
    window.addEventListener("spread:reset", again);
    return () => window.removeEventListener("spread:reset", again);
  }, [trade]);

  // A budget block is explained with the account's own numbers.
  const budgetBlocked = best?.preview?.blocked_by === "budget";
  useEffect(() => {
    if (budgetBlocked) fetchAccount().then(setAcct).catch(() => setAcct(null));
  }, [budgetBlocked, best]);

  function start(what: "run" | "find" | "buy") {
    setBusy(what);
    setError(null);
    if (what !== "buy") {
      setOrder(null);
      setTrade(null);
      setNoTrade(null);
      setBest(null);
    }
  }
  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }

  async function runStrategy() {
    start("run");
    setLooked(null);
    setAllLooked(false);
    try {
      const qs = new URLSearchParams({ strategy: pick, limit: "50" });
      if (q.trim()) qs.set("q", q.trim());
      const r = await getJson<SignalResult>(`/engine/best/signal?${qs}`);
      if (!r.signal) {
        setNoTrade(noTradeLine(r, list.find((s) => s.id === pick)));
        setLooked(r.looked ?? []);
      }
      setTrade(r.signal);
      setBest(r.best);
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }

  // Compare one market the strategy passed over: 100 YES, no max price.
  async function compareFor(m: MatchView) {
    start("run");
    try {
      const r = await getJson<BestResult>("/engine/best/preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: m.id, side: "yes", size: 100, max_price: null }),
      });
      setTrade({ match_id: m.id, side: "yes", size: 100, max_price: null, why: "You picked it from the list.", match: m });
      setBest(r);
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }

  async function findMarkets() {
    start("find");
    try {
      const qs = new URLSearchParams({ limit: "30" });
      if (q.trim()) qs.set("q", q.trim());
      const r = await getJson<{ matches: MatchView[] }>(`/engine/matches?${qs}`);
      setFound(r.matches);
      setMid(r.matches[0]?.id ?? "");
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }

  async function compareManual() {
    const m = found?.find((x) => x.id === mid);
    if (!m) return;
    start("run");
    const max = mMax.trim() ? Number(mMax) / 100 : null;
    try {
      const r = await getJson<BestResult & { match: MatchView }>("/engine/best/preview", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: m.id, side: mSide, size: mSize, max_price: max }),
      });
      setTrade({ match_id: m.id, side: mSide, size: mSize, max_price: max, why: "You picked this trade by hand.", match: m });
      setBest(r);
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }

  async function buy() {
    if (!trade) return;
    start("buy");
    try {
      const r = await getJson<BestResult>("/engine/best/buy", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ match_id: trade.match_id, side: trade.side, size: trade.size, max_price: trade.max_price }),
      });
      setOrder(r);
      traded();
    } catch (e) {
      fail(e);
    }
    setBusy(null);
  }

  const chosen = list.find((s) => s.id === pick);
  const why = best?.why;
  const p = best?.preview;
  // What the SDK's guardrails said about the chosen order, before anything is sent.
  const orderCost = why?.venues.find((v) => v.venue === why.venue)?.all_in ?? null;
  const blocked =
    p && !p.allowed
      ? budgetBlocked && acct && orderCost != null
        ? `Your ${acct.mode === "paper" ? "paper" : ""} account already has ${money(acct.at_risk)} in open trades; this ${money(orderCost)} order would take it over your ${money(acct.budget)} limit.`
        : [p.rules.decision.reason ?? (p.blocked_by ? `Blocked by ${p.blocked_by}.` : null), ...p.problems].filter(Boolean).join(" ")
      : null;

  return (
    <section>
      <div className="switch" role="tablist">
        <button className={how === "strategy" ? "current" : ""} onClick={() => setHow("strategy")}>
          Run a strategy
        </button>
        <button className={how === "manual" ? "current" : ""} onClick={() => setHow("manual")}>
          Pick a trade yourself
        </button>
      </div>

      {how === "strategy" ? (
        <>
          <div className="controls">
            <label className="field">
              Strategy
              <select value={pick} onChange={(e) => setPick(e.target.value)} style={{ minWidth: 300 }}>
                {list.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field grow">
              Markets it looks at
              <input
                className="search"
                value={q}
                placeholder="search, e.g. nba (blank: all matched markets)"
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runStrategy()}
              />
            </label>
            <button className="btn" onClick={runStrategy} disabled={busy !== null}>
              {busy === "run" ? "Running…" : "Run strategy"}
            </button>
          </div>
          {chosen && (
            <p className="small muted" style={{ marginTop: -8 }}>
              {chosen.description}
              {chosen.example ? " An example, not advice." : ""}
            </p>
          )}
          <p className="small">
            Add your own: copy <code>strategies/my_strategy.py</code>. <a href={ADD_YOUR_OWN}>How</a>
          </p>
        </>
      ) : (
        <>
          <div className="controls">
            <label className="field grow">
              Find a market
              <input
                className="search"
                value={q}
                placeholder="search, e.g. nba"
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && findMarkets()}
              />
            </label>
            <button className="btn quiet" onClick={findMarkets} disabled={busy !== null}>
              {busy === "find" ? "Searching…" : "Search"}
            </button>
          </div>
          {found && !found.length && <p className="small muted">No matched markets for that search.</p>}
          {found && found.length > 0 && (
            <div className="controls">
              <label className="field grow">
                Market
                <select value={mid} onChange={(e) => setMid(e.target.value)}>
                  {found.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.outcome ?? m.title} · {m.title}
                      {m.caveats.length ? " · rules differ" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Side
                <select value={mSide} onChange={(e) => setMSide(e.target.value as "yes" | "no")}>
                  <option value="yes">YES</option>
                  <option value="no">NO</option>
                </select>
              </label>
              <label className="field">
                Contracts
                <input type="number" min={1} value={mSize} onChange={(e) => setMSize(Math.max(1, +e.target.value || 1))} />
              </label>
              <label className="field">
                Max price (¢, optional)
                <input type="number" min={1} max={99} value={mMax} placeholder="none" onChange={(e) => setMMax(e.target.value)} />
              </label>
              <button className="btn" onClick={compareManual} disabled={busy !== null || !mid}>
                {busy === "run" ? "Comparing…" : "Compare venues"}
              </button>
            </div>
          )}
        </>
      )}

      {busy === "run" && (
        <div className="status">
          <span className="dot" /> Checking prices on both venues
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {noTrade && <p>{noTrade}</p>}
      {!trade && looked && looked.length > 0 && (
        <table className="t">
          <tbody>
            {(allLooked ? looked : looked.slice(0, 10)).map((m) => (
              <tr key={m.id}>
                <td>
                  {m.outcome ?? m.title}
                  <div className="small muted">{m.title}</div>
                </td>
                <td>
                  <span className={`pill ${m.reason === "rules differ" ? "warn" : ""}`}>
                    {m.reason === "rules differ" ? "worded differently" : m.reason}
                  </span>
                </td>
                <td className="num">
                  <button className="btn quiet" onClick={() => compareFor(m)} disabled={busy !== null}>
                    Compare
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
          {!allLooked && looked.length > 10 && (
            <tfoot>
              <tr>
                <td colSpan={3}>
                  <button className="link" onClick={() => setAllLooked(true)}>
                    Show all {looked.length}
                  </button>
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      )}

      {trade && (
        <div className="box stub">
          <div className="label">{how === "strategy" ? "Your strategy picked" : "Your trade"}</div>
          <div className="signal">
            buy {count(trade.size)} {side(trade.side)} · {trade.match.outcome ?? trade.match.title}
            {trade.max_price != null ? ` · max ${cents(trade.max_price)}` : ""}
          </div>
          <MatchLine m={trade.match} />
          <div className="small" style={{ marginTop: 6 }}>
            <b>Why:</b> {trade.why}
          </div>
        </div>
      )}

      {trade && best && !best.ok && (
        <p className="error">
          {best.error?.message} {best.error?.hint}
        </p>
      )}

      {trade && why && (
        <>
          <h3>Both venues</h3>
          <CompareTable why={why} />
          <p className={why.venue ? "" : "error"}>
            {why.venue ? verdictLine(why) : "No trade: neither venue can fill this order right now."}
          </p>
          {why.venue && blocked && (
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
                {mode === "live" ? "Real money." : "Fake money."} Pays at most{" "}
                {cents(why.venues.find((v) => v.venue === why.venue)?.limit_price)} a contract.
              </span>
            </div>
          )}
        </>
      )}

      {order?.order && (
        <div className="box good" style={{ marginTop: 16 }}>
          {order.mode === "live" ? "Bought" : "Paper trade"} on {VENUE_NAME[order.order.venue]}: {count(order.order.filled)} of{" "}
          {count(order.order.size)} {side(order.order.side)} at {cents(order.order.avg_price)}, fees {money(order.order.fees)}.
        </div>
      )}
    </section>
  );
}
