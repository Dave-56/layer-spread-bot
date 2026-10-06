"use client";

import { useEffect, useState } from "react";
import Arbitrage from "@/components/Arbitrage";
import BestVenue from "@/components/BestVenue";
import PaperAccount from "@/components/PaperAccount";
import type { Status } from "@/lib/engine";

type Tab = "best" | "arb";

// Owner-approved wording (see the PR body). Change it only with the owner's OK.
const INTRO =
  "With uselayer, your trading bot keeps its own strategy and gains two abilities: it buys every trade on whichever venue is cheapest after fees, and it catches cross-venue price gaps that are real money after fees, rules and depth, while skipping the fake ones.";

export default function Page() {
  const [tab, setTab] = useState<Tab>("best");
  const [status, setStatus] = useState<Status | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    fetch("/engine/status")
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((s: Status) => setStatus(s))
      .catch(() => setDown(true));
  }, []);

  const mode = status?.mode ?? "paper";
  const missing = status
    ? [!status.keys.layer && "LAYER_API_KEY", !status.keys.kalshi && "KALSHI_KEY_ID + KALSHI_PRIVATE_KEY_PATH"].filter(Boolean)
    : [];

  return (
    <>
      <header className="header">
        <div className="brand">
          Spread{" "}
          <span className="brand-tag">
            an example bot on <a href="https://uselayer.sh">uselayer</a>
            {status ? (
              <>
                {" "}
                <a className="quiet-link" href="https://pypi.org/project/uselayer/" title="The uselayer SDK on PyPI">
                  {status.sdk_version}
                </a>
              </>
            ) : null}
          </span>
        </div>
        <div className="header-actions">
          <span
            className="info"
            title="Runs on your computer with your own keys. Layer finds which markets are the same bet; prices and orders go straight to each venue. Prices are a snapshot and can move before an order lands."
          >
            ⓘ
          </span>
          <span className="venues-label">Kalshi · Polymarket US</span>
          <span className={`mode ${mode === "live" ? "live" : ""}`} title={mode === "live" ? "Orders are real, with your own keys" : "Real books, fake money"}>
            {mode === "live" ? "LIVE" : "Paper"}
          </span>
        </div>
      </header>

      <div className="layout">
        <main className="main">
          <div className="page">
            <p className="intro">{INTRO}</p>

            {down && (
              <p className="notice">
                The engine isn&apos;t running. Start it with <code>npm run dev</code>.
              </p>
            )}
            {missing.length > 0 && (
              <p className="notice">
                Add {missing.join(" and ")} to <code>.env</code>, then restart. Keys stay on this machine.
              </p>
            )}
            {status?.client_error && <p className="notice">{status.client_error.message} {status.client_error.hint}</p>}

            <nav className="tabs" role="tablist">
              <button className={`tab ${tab === "best" ? "current" : ""}`} onClick={() => setTab("best")}>
                Best venue
              </button>
              <button className={`tab ${tab === "arb" ? "current" : ""}`} onClick={() => setTab("arb")}>
                Arbitrage
              </button>
            </nav>

            {/* Best venue sends nothing, so the paper account (and Reset) shows with Arbitrage only. */}
            {tab === "best" ? (
              <BestVenue />
            ) : (
              <>
                <PaperAccount />
                <Arbitrage mode={mode} />
              </>
            )}
          </div>
        </main>
      </div>
    </>
  );
}
