"use client";

import { useCallback, useEffect, useState } from "react";
import { errorText, VENUE_NAME } from "@/lib/engine";
import { cents, count, money, side } from "./format";

// The bot's own fake account: what's open, money at risk against the budget, and a reset.

export interface Account {
  mode: "paper" | "live";
  store: string;
  budget: number;
  at_risk: number;
  open_orders: number;
  positions: { venue: string; market: string; side: string; contracts: number; avg_price: number; cost: number }[];
}

/** Tell the account panel to refresh (after any order). */
export const traded = () => window.dispatchEvent(new Event("spread:traded"));

export async function fetchAccount(): Promise<Account> {
  const r = await fetch("/engine/paper/account");
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(errorText(body, r.status));
  return body as Account;
}

export default function PaperAccount() {
  const [acct, setAcct] = useState<Account | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetchAccount().then(setAcct).catch(() => setAcct(null));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener("spread:traded", load);
    return () => window.removeEventListener("spread:traded", load);
  }, [load]);

  async function reset() {
    setBusy(true);
    const r = await fetch("/engine/paper/reset", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
    if (r.ok) setAcct((await r.json()) as Account);
    setBusy(false);
    window.dispatchEvent(new Event("spread:reset"));
  }

  // An empty paper account says nothing worth reading: it appears once there's a trade.
  if (!acct) return null;
  const paper = acct.mode === "paper";
  if (paper && !acct.positions.length && !acct.open_orders) return null;
  return (
    <div className="account small">
      <span>
        <b>{paper ? "Paper account" : "Live account"}</b>: {money(acct.at_risk)} of your {money(acct.budget)} limit in use ·{" "}
        {acct.positions.length} open trade{acct.positions.length === 1 ? "" : "s"}
        {acct.open_orders ? ` · ${acct.open_orders} orders waiting` : ""}
      </span>
      {acct.positions.length > 0 && (
        <button className="link" onClick={() => setOpen((o) => !o)}>
          {open ? "hide" : "show"}
        </button>
      )}
      {paper && (acct.positions.length > 0 || acct.open_orders > 0) && (
        <button className="btn quiet" onClick={reset} disabled={busy}>
          {busy ? "Resetting…" : "Reset"}
        </button>
      )}
      {open && (
        <table className="t" style={{ marginTop: 8 }}>
          <tbody>
            {acct.positions.map((p) => (
              <tr key={`${p.venue}:${p.market}:${p.side}`}>
                <td>
                  {VENUE_NAME[p.venue] ?? p.venue} · <span className="mono">{p.market}</span>
                </td>
                <td className="num">
                  {count(p.contracts)} {side(p.side)} at {cents(p.avg_price)}
                </td>
                <td className="num">{money(p.cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
