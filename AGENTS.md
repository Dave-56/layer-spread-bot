<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## This repo

An example bot on the uselayer SDK. It runs only on the user's machine; nothing is hosted or deployed.

- Layer hosts matching only. Prices, books, fees, quotes and orders run in the SDK (`engine/`), with the user's own keys. Don't add TypeScript price or fee math, and don't call Layer's hosted price endpoints.
- Keys stay local: read from `.env`, never logged, returned by the engine, or sent to Layer.
- Paper mode is the default. Never run live mode or place a real-money order.
- Public copy never says "risk-free" or "best execution". Say "cheaper for this size, after fees".
- Pull requests: sessions never merge. Only the owner merges, when they say "merge #N".
