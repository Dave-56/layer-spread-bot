"use client";

import { useEffect, useState } from "react";
import Arbitrage from "@/components/Arbitrage";
import BestVenue from "@/components/BestVenue";
import Chat from "@/components/Chat";
import type { Status } from "@/lib/engine";

type Tab = "best" | "arb";

// Owner-approved wording (see the PR body). Change it only with the owner's OK.
const INTRO =
  "With uselayer, your trading bot keeps its own strategy and gains two abilities: it buys every trade on whichever venue is cheapest after fees, and it catches cross-venue price gaps that are real money after fees, rules and depth, while skipping the fake ones.";

export default function Page() {
  const [tab, setTab] = useState<Tab>("best");
  const [chat, setChat] = useState(false);
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
          Spread <span className="brand-tag">an example bot on uselayer</span>
        </div>
        <div className="header-actions">
          <span>Kalshi · Polymarket US</span>
          <span className={`mode ${mode === "live" ? "live" : ""}`} title={mode === "live" ? "Orders are real, with your own keys" : "Real books, fake money"}>
            {mode === "live" ? "LIVE" : "Paper"}
          </span>
          <button className="btn quiet" onClick={() => setChat((c) => !c)}>
            {chat ? "Hide chat" : "Chat"}
          </button>
        </div>
      </header>

      <div className={`layout ${chat ? "with-chat" : ""}`}>
        <main className="main">
          <div className="page">
            <p className="intro">{INTRO}</p>

            {down && (
              <p className="notice">
                The engine isn&apos;t answering on 127.0.0.1:8765. Start everything with <code>npm run dev</code>.
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

            {tab === "best" ? <BestVenue mode={mode} /> : <Arbitrage mode={mode} />}

            <p className="small muted" style={{ marginTop: 40 }}>
              Runs on your machine. Layer finds which markets are the same bet; prices, books, fees and orders run in the{" "}
              <a href="https://github.com/Dave-56/uselayer-sdk">uselayer</a> SDK with your own keys
              {status ? ` (v${status.sdk_version})` : ""}.
            </p>
          </div>
        </main>
        {chat && <Chat mode={mode} onClose={() => setChat(false)} />}
      </div>
    </>
  );
}
