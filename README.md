# tri-analyze-agent

A triathlon training analysis agent built with LangChain. It syncs your Garmin Connect and
TrainingPeaks data into a local Postgres store, then lets you chat with an analyst that
reviews completed sessions and finds trends, pulling lap-level detail live from the servers
when it needs to.

Two commands: `tri-analyze sync` (deterministic ETL, no LLM) and `tri-analyze chat` (the
agent REPL). One athlete, personal use. Repo: github.com/paradigmbrian/tri-analyze-agent. The Python package is `tri_analyze` and the CLI is `tri-analyze`.

## How it fits together

```
 Garmin MCP server ──┐                        ┌──► Postgres ◄── query_training_db (read-only)
                     ├── tri-analyze sync ────┤                        │
 TrainingPeaks MCP ──┘   (MCP client, ETL)    └──► sync_state          │
                                                                       ▼
 Garmin MCP server ──┐                                        tri-analyze chat
 TrainingPeaks MCP ──┴── live tools (allow-listed) ─────────► LangChain agent on Claude
                                                              streams to your terminal
```

Deeper context lives next to the code:

- [`src/tri_analyze/agent/README.md`](src/tri_analyze/agent/README.md): how the LangChain
  agent works, module by module, one question traced end to end, and which knobs to turn.
- [`src/tri_analyze/sync/README.md`](src/tri_analyze/sync/README.md): the ETL, what each
  source provides, matching, windows and watermarks.
- [`src/tri_analyze/db/README.md`](src/tri_analyze/db/README.md): the four tables, upsert
  semantics, conventions, the read-only rule.
- [`src/tri_analyze/mcp/README.md`](src/tri_analyze/mcp/README.md): the two MCP servers,
  auth, result conventions, the allow-list.
- [`docs/superpowers/specs/`](docs/superpowers/specs/): the approved design.
  [`docs/superpowers/plans/`](docs/superpowers/plans/): the implementation plans that built it.

## Setup

1. Python 3.12 via uv: `uv sync`
2. Postgres (Docker, host port 5435): `docker compose up -d`, then apply the migrations to
   both databases:
   ```bash
   docker compose exec db psql -U tri_analyze -c "create database tri_analyze_test;"
   docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/001_initial.sql
   docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/001_initial.sql
   ```
3. `cp .env.example .env`, then fill in `ANTHROPIC_API_KEY` (from console.anthropic.com).
   Optional but recommended while learning: `LANGSMITH_TRACING=true` and
   `LANGSMITH_API_KEY` (free at smith.langchain.com) to see every prompt and tool call.
4. Authenticate the MCP servers once (`<ref>` values are in `.env.example`):
   ```bash
   uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@<ref> garmin-mcp-auth
   # log into app.trainingpeaks.com in Chrome first, then:
   uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<ref> tp-mcp auth --from-browser chrome
   ```
5. First sync: `uv run tri-analyze sync --full` (a year of TrainingPeaks, 60 days of Garmin).

## Run

```bash
uv run tri-analyze sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]
uv run tri-analyze chat [--no-live]     # --no-live binds only the database tool
```

In chat: `/tools` lists bound tools, `/prompt` prints the system prompt, `/sync` refreshes
data and context without losing the conversation, `/quit` exits. Every tool call prints as
`→ name(args)` and every result as `← name: N chars`.

Incremental syncs resume from a per-source watermark with a 3-day overlap; rerunning is
always safe.

## Test and lint

```bash
uv run pytest                 # unit + db tests; db tests skip if Postgres is down
uv run pytest --live          # also starts the real MCP servers
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run python scripts/spike_mcp.py   # re-record tests/fixtures/mcp/ (scrub before committing)
```

## Status

- Milestones 1–2 (2026-09-06): scaffold, schema, MCP client, sync with watermarks.
- Milestones 3–4 (2026-09-06): LangChain agent with the SQL tool, athlete-context prompt,
  streaming REPL, and live MCP tools.
- Milestone 5 (planned, separate spec): LangGraph refactor with typed state, persistent
  checkpointing, `weekly-review` command, charts.
