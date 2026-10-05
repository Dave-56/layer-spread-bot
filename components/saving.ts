// Save prices: the words shown while a recording runs and after it ends. The engine counts the
// events and says how it ended; this only puts them into sentences.

import type { Recording } from "@/lib/engine";
import { count } from "./format";

/** 1,800 seconds → "30:00"; 3,725 → "1:02:05". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export const updates = (n: number) => `${count(n)} price ${n === 1 ? "update" : "updates"}`;

/** While it runs: "12:34 left · 1,234 price updates saved". */
export function savingLine(r: Pick<Recording, "events">, secondsLeft: number): string {
  return `${clock(secondsLeft)} left · ${updates(r.events)} saved`;
}

/** After it ends: what was saved and what to press next, or the engine's one sentence why not. */
export function savedLine(r: Pick<Recording, "state" | "events" | "error">): string | null {
  if (r.state === "recording") return null;
  if (r.state === "failed") return r.error;
  return `Saved ${updates(r.events)}. It's selected under Saved prices: press Replay.`;
}

/** The lengths offered, in minutes. */
export const LENGTHS = [
  { minutes: 5, label: "5 min" },
  { minutes: 15, label: "15 min" },
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 180, label: "3 hours" },
] as const;
