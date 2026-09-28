# tri-web

[Architecture index](README.md) · [Package README](../../packages/tri-web/README.md)

A loopback-only FastAPI server that hosts the coach for the React app in `web/`. Every coach turn, review resume, check-in and reset takes the same lock, so the browser and the check-in job never run the coach thread at the same time.

![tri-web](diagrams/tri-web.svg)

- **React app.** The Today page has the readiness, session, fuel and week cards, the chat, and the review gate. Settings covers memory, reset and readiness. `useTurnStream` and `useJobStream` read server-sent events with `fetch` and `readSse`, not `EventSource`.
- **Routes.** `/api/coach` handles turns and review resumes (both SSE), the review schema, validation and YAML, memory, reset, and the thread view. `/api/jobs` starts sync and check-in and streams their events. `/api/system/status` reports the live tools and readiness. `/api/today` builds the cards.
- **Runtime.** `open_runtime` mirrors the CLI: readiness check, MCP servers, checkpointer, store, deps, graph. It holds one coach graph on thread `coach` and one `asyncio.Lock`. A turn while the lock is held, or while a review is paused, gets a 409.
- **Jobs.** Jobs live in memory, each with a replayable transcript. `sync` runs `run_sync` without the lock. `checkin` holds the lock for its whole run.
- **Turn events.** `TurnEmitter` wraps the coach's `TurnPrinter` and emits `token`, `tool_call`, `tool_result`, `consult`, `report`, `interrupt`, `error` and `done`.
