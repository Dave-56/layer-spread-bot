"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type Anthropic from "@anthropic-ai/sdk";
import type { ChatEvent, Funnel } from "@/lib/agent";
import { ndjson, type BestResult, type MatchView } from "@/lib/engine";
import { FunnelResult } from "./Arbitrage";
import { CompareTable, MatchLine, verdictLine } from "./BestVenue";

// The optional side panel: ask in plain English. It uses the same engine as the tabs and only reads.

type Block =
  | { kind: "text"; text: string }
  | { kind: "matches"; matches: MatchView[] }
  | { kind: "best"; best: BestResult & { match?: MatchView } }
  | { kind: "funnel"; funnel: Funnel }
  | { kind: "error"; message: string };

interface Turn {
  question: string;
  blocks: Block[];
  status: string | null;
  done: boolean;
}

const SUGGESTIONS = [
  "Any NFL gap that's still money after fees?",
  "Where is 100 YES on the first match cheaper after fees?",
  "Why do most gaps get dropped?",
];

export default function Chat({ mode, onClose }: { mode: "paper" | "live"; onClose: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const history = useRef<Anthropic.MessageParam[]>([]);
  const end = useRef<HTMLDivElement>(null);

  // Braces matter: newer browsers return a Promise from smooth scrolling.
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const update = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === all.length - 1 ? fn(t) : t)));

  function apply(e: ChatEvent) {
    if (e.type === "history") {
      history.current = e.messages;
      return;
    }
    update((t) => {
      const blocks = [...t.blocks];
      const last = blocks[blocks.length - 1];
      if (e.type === "text") {
        if (last?.kind === "text") blocks[blocks.length - 1] = { kind: "text", text: last.text + e.delta };
        else blocks.push({ kind: "text", text: e.delta });
        return { ...t, blocks, status: null };
      }
      if (e.type === "status") return { ...t, status: e.label };
      if (e.type === "matches") blocks.push({ kind: "matches", matches: e.matches });
      if (e.type === "best") blocks.push({ kind: "best", best: e.best });
      if (e.type === "funnel") blocks.push({ kind: "funnel", funnel: e.funnel });
      if (e.type === "error") blocks.push({ kind: "error", message: e.message });
      return { ...t, blocks, status: e.type === "error" ? null : "Writing it up" };
    });
  }

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setInput("");
    setTurns((all) => [...all, { question, blocks: [], status: "Reading your question", done: false }]);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: [...history.current, { role: "user", content: question }] }),
      });
      if (!res.ok || !res.body) {
        const failed = (await res.json().catch(() => null)) as { error?: string } | null;
        throw new Error(failed?.error ?? `The server answered ${res.status}`);
      }
      for await (const e of ndjson<ChatEvent>(res.body)) apply(e);
    } catch (err) {
      apply({ type: "error", message: err instanceof Error ? err.message : "Something went wrong" });
    }
    update((t) => ({ ...t, status: null, done: true }));
    setBusy(false);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(input);
  }

  return (
    <aside className="chat">
      <div className="chat-head">
        Ask in plain English
        <button className="btn quiet" onClick={onClose} aria-label="Close chat">
          Close
        </button>
      </div>
      <div className="chat-feed">
        {turns.length === 0 && (
          <div className="chips">
            <p className="small muted" style={{ margin: "0 0 6px" }}>
              Uses the same engine as the tabs, with your own LLM key. It reads only; orders go through the tabs.
            </p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip" onClick={() => ask(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="turn">
            <div className="you">{t.question}</div>
            <div className="answer">
              {t.blocks.map((b, j) => (
                <BlockView key={j} block={b} mode={mode} />
              ))}
              {t.status && !t.done && (
                <div className="status">
                  <span className="dot" /> {t.status}…
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          rows={2}
          value={input}
          placeholder="Ask about a market, a size, a gap…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) submit(e);
          }}
        />
        <button className="btn" type="submit" disabled={busy || !input.trim()}>
          Ask
        </button>
      </form>
    </aside>
  );
}

function BlockView({ block, mode }: { block: Block; mode: "paper" | "live" }) {
  if (block.kind === "text") return <Markdown text={block.text} />;
  if (block.kind === "error") return <p className="error">{block.message}</p>;
  if (block.kind === "matches")
    return (
      <div className="box">
        {block.matches.slice(0, 8).map((m) => (
          <div key={m.id} style={{ marginBottom: 6 }}>
            <b>{m.outcome ?? m.title}</b>
            <MatchLine m={m} />
          </div>
        ))}
      </div>
    );
  if (block.kind === "best") {
    const b = block.best;
    if (!b.ok || !b.why) return <p className="error">{b.error?.message}</p>;
    return (
      <div className="box">
        {b.match && <MatchLine m={b.match} />}
        <CompareTable why={b.why} />
        <div className="small">{verdictLine(b.why)}</div>
      </div>
    );
  }
  return <FunnelResult f={{ ...block.funnel, done: true }} size={100} mode={mode} />;
}

// Just enough Markdown for short answers: paragraphs, "- " bullets and **bold**.
function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) out.push(<ul key={out.length}>{bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}</ul>);
    bullets = [];
  };
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (/^[-*•] /.test(t)) bullets.push(t.slice(2));
    else {
      flush();
      if (t) out.push(<p key={out.length}>{inline(t)}</p>);
    }
  }
  flush();
  return <>{out}</>;
}

function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  );
}
