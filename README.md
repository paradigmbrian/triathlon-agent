# triathlon_agent

A uv workspace of LangChain/LangGraph agents over one athlete's Garmin Connect and
TrainingPeaks data, synced into a local Postgres store.

| Package | Module | Command | What it does |
|---|---|---|---|
| `packages/tri-core` | `tri_core` | `tri sync` | Settings, MCP client, Postgres store, the ETL, test helpers. No LLM code. |
| `packages/tri-analyze` | `tri_analyze` | `tri-analyze chat \| eval` | Analyst agent: feedback on completed sessions, trends. |
| `packages/tri-planning` | `tri_planning` | `tri-planning chat` | Planning agent: goal intake, periodized plan, approved writes to the TrainingPeaks calendar. |
| `packages/tri-nutrition` | `tri_nutrition` | `tri-nutrition chat \| today \| check-in \| eval` | Nutrition agent: profile intake, periodized daily targets and fueling plans, approved writes to Garmin Connect and TrainingPeaks. |
| `packages/tri-wellness` | `tri_wellness` | `tri-wellness ingest \| report \| chat \| panels \| eval` | Lab interpreter: PDF and export ingest with review, functional-range evaluation, written interpretation grounded in training data. |
| `packages/tri-coach` | `tri_coach` | `tri-coach chat \| check-in \| memory \| reset \| eval` | Head coach: answers through the analyst and the lab interpreter, briefs planning and nutrition, one review gate over both, approved writes only. |
| `packages/tri-web` | `tri_web` | `tri-web serve \| openapi` | Local web UI over the coach: FastAPI server streaming the coach graph on localhost; React app in `web/`. |

`tri-analyze`, `tri-planning`, `tri-nutrition` and `tri-wellness` depend on `tri-core` and on nothing else; `tri-coach` sits above them and depends on `tri-analyze`, `tri-planning`, `tri-nutrition` and `tri-wellness`.
Repo: github.com/paradigmbrian/triathlon-agent.

## How it fits together

```
 Garmin MCP server ──┐                        ┌──► Postgres ◄── query_training_db (read-only)
                     ├── tri sync ────────────┤                        │
 TrainingPeaks MCP ──┘   (tri-core ETL)       └──► sync_state          │
                                                                       ▼
 Garmin MCP server ──┐                                        tri-analyze chat
 TrainingPeaks MCP ──┴── live tools (allow-listed) ─────────► LangChain agent on Claude
                                                              streams to your terminal
```

Deeper context lives next to the code:

- [`packages/tri-analyze/README.md`](packages/tri-analyze/README.md):
  how the analyst agent works, module by module, one question traced end to end.
- [`packages/tri-core/src/tri_core/sync/README.md`](packages/tri-core/src/tri_core/sync/README.md):
  the ETL, what each source provides, matching, windows and watermarks.
- [`packages/tri-core/src/tri_core/db/README.md`](packages/tri-core/src/tri_core/db/README.md):
  the tables, upsert semantics, conventions, the read-only rule.
- [`packages/tri-core/src/tri_core/mcp/README.md`](packages/tri-core/src/tri_core/mcp/README.md):
  the two MCP servers, auth, result conventions, the allow-list.
- [`docs/superpowers/specs/`](docs/superpowers/specs/): the approved designs.
  [`docs/superpowers/plans/`](docs/superpowers/plans/): the implementation plans that built them.

## Setup

1. Python 3.12 via uv, from the repository root: `uv sync` (installs every package editable
   and their console scripts into one `.venv`).
2. Postgres (Docker, host port 5435): `docker compose up -d`, then apply the migrations to
   both databases:
   ```bash
   docker compose exec db psql -U tri_analyze -c "create database tri_analyze_test;"
   for f in migrations/*.sql; do
     docker compose exec -T db psql -U tri_analyze -d tri_analyze < "$f"
     docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < "$f"
   done
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
5. First sync: `uv run tri sync --full` (a year of TrainingPeaks, 60 days of Garmin).
6. Checkpoint and LangGraph store tables (once per database): `uv run python scripts/setup_checkpointer.py <url>`
   for both `tri_analyze` and `tri_analyze_test`.

## Run

```bash
uv run tri sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]
uv run tri-analyze chat [--no-live]     # --no-live binds only the database tool
uv run tri-analyze eval [--recreate-dataset]   # LangSmith feedback eval
uv run tri-planning chat [--no-live]    # plan; every TrainingPeaks write is approved first
uv run tri-planning check-in [--yes] [--no-sync] [--no-live]   # sync, review last 7 days, propose; exit 3 when paused, 1 on a model error or a week --yes skipped for violations
uv run tri-planning reset [--yes]       # abandon goal and plan, clear the thread
uv run tri-wellness ingest <file.pdf|csv> [--kind pdf|export] [--drawn-on YYYY-MM-DD]   # extract, review, store a lab panel
uv run tri-wellness report [--panel ID] [--out path.md]   # interpret a stored panel; saved to lab_reports
uv run tri-wellness chat                                   # ask about panels and reports
uv run tri-wellness panels                                 # list stored panels
uv run tri-wellness eval [--recreate-dataset]              # LangSmith report evaluators
uv run tri-coach chat [--no-live]       # the front door: one conversation over the analyst, wellness, planning and nutrition
uv run tri-coach check-in [--yes] [--no-sync] [--no-live]   # sync, weekly checklist over plan and nutrition; exit 3 when paused, 1 on a model error or a change --yes skipped for violations
uv run tri-coach eval [--recreate-dataset]                   # LangSmith routing eval
uv run tri-coach memory [--forget ID]   # the coach's athlete memory
uv run tri-coach reset [--yes] [--forget-memory]
uv run tri-web serve [--no-live] [--port 8321]   # the coach in the browser, same thread and memory as tri-coach chat
npm --prefix web install && npm --prefix web run build   # once: build the app that tri-web serve hosts
npm --prefix web run dev                                  # frontend work: Vite on :5173 proxying /api to :8321
npm --prefix web run lint && npm --prefix web run test && npm --prefix web run test:e2e
```

In chat: `/tools` lists bound tools, `/prompt` prints the system prompt, `/sync` refreshes
data and context without losing the conversation, `/quit` exits. Every tool call prints as
`→ name(args)` and every result as `← name: N chars`.

Incremental syncs resume from a per-source watermark with a 3-day overlap; rerunning is
always safe.

### First conversation

Start with the database tool only, so the first thing you judge is the SQL the model writes:

```
uv run tri-analyze chat --no-live
  /prompt
  How did my training go this week compared to plan?
  Show my weekly bike hours for the last 8 weeks.
  Which day this month had the worst sleep, and what did I do the next day?
  /quit
```

Then with live tools (startup takes 10 to 20 s while both MCP servers launch):

```
uv run tri-analyze chat
  Give me feedback on my last completed ride. Pull the laps.
  How ready am I to train today?
  What does my coach have planned for the next 3 days, and does the load look reasonable given my TSB?
  /quit
```

What to look for: wrong column names or units in the `→ query_training_db(...)` lines (fix in
`SCHEMA_DOC`), whether the model queries for `garmin_activity_id` before calling
`get_activity_splits`, and whether feedback follows the rules or drifts into generic
encouragement (fix in `FEEDBACK_RULES`). With LangSmith on, check `cache_read_input_tokens`
on the second turn is nonzero.

## Test and lint

```bash
uv run pytest                 # all packages; db tests skip if Postgres is down
uv run pytest --live          # also starts the real MCP servers
uv run pytest packages/tri-core   # one package
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/spike_mcp.py   # re-record packages/tri-core/tests/fixtures/mcp/ (scrub before committing)
```

## Layout

```
pyproject.toml          workspace root: members, shared ruff/mypy/pytest config
conftest.py             pytest options and the shared `db` fixture plugin
migrations/             001_initial.sql (sync tables), 002_planning.sql and 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables), 005_wellness.sql (lab tables), 006_fixes.sql (2026-09-24 correctness fixes)
packages/tri-core/      src/tri_core/{config,cli,mcp,db,sync,testing}
packages/tri-analyze/   src/tri_analyze/{config,cli,llm,agent,repo,repl,testing,allowlist,prompts,tools,evals}
packages/tri-planning/  src/tri_planning/{config,cli,repo,repl,testing,planning,graph,tools,prompts}
packages/tri-nutrition/ src/tri_nutrition/{config,cli,repo,repl,store,plan_loader,testing,nutrition,graph,tools,prompts,evals}
packages/tri-wellness/  src/tri_wellness/{config,cli,repo,repl,report,agent,testing,ranges,labs,graph,prompts,tools,evals}
packages/tri-web/       src/tri_web/{config,cli,app,runtime,events,thread,review,schemas,routes}
web/                    Vite + React app: src/{api,components,pages,lib}, tests/ (Vitest, Playwright e2e)
docs/superpowers/       specs and implementation plans
```

Module-level READMEs: `packages/tri-core/src/tri_core/{mcp,db,sync}/README.md`; each agent
package documents itself in its own `README.md`.

## Status

- Milestones 1–2 (2026-09-06): scaffold, schema, MCP client, sync with watermarks.
- Milestones 3–4 (2026-09-06): LangChain agent with the SQL tool, athlete-context prompt,
  streaming REPL, and live MCP tools.
- Workspace (2026-09-07): monorepo with tri-core extracted; tri-planning milestones tracked in
  `docs/superpowers/plans/2026-09-07-tri-planning-0*.md`.
- tri-planning milestones 2-4 (2026-09): targets, graph with review interrupt, adjust and
  check-in; design-prompt validator pass rate: not yet measured (run
  `uv run tri-planning eval` and record the `validator_pass` mean here).
- tri-wellness milestone 1 (2026-09-11): ranges table, registry, normalize, evaluate, training context, lab tables; tracked in docs/superpowers/plans/2026-09-11-tri-wellness-0*.md.
- tri-wellness milestone 2 (2026-09): PDF and export ingest with a checkpointed review; first real panel pending.
- tri-wellness milestone 3 (2026-09): report, chat and panels commands; LangSmith report evaluators (pass rates in the package README).
- tri-coach milestone 1 (2026-09-12): planning route node, embedded mode and `apply_changes` in
  planning and nutrition, nutrition regenerate entry, directed prompt sections, tri-core
  `open_live_servers` and `ToolsCaller`; tracked in
  `docs/superpowers/plans/2026-09-12-tri-coach-01-sub-package-preparation.md`. Coach v1 pending.
- tri-coach milestone 2 (2026-09): coach v1 (chat, memory, reset; handoffs, review, apply);
  tracked in `docs/superpowers/plans/2026-09-12-tri-coach-02-coach-v1.md`. Check-in and eval pending.
- tri-coach milestone 3 (2026-09): wellness consult (`ask_wellness`, lab line in the context, prompt v2);
  tracked in `docs/superpowers/plans/2026-09-13-tri-coach-03-wellness-consult.md`. Merged 2026-09-13.
- tri-coach milestone 4 (2026-09): check-in, the follow-on nutrition gate, prompt v3 and the routing eval;
  tracked in `docs/superpowers/plans/2026-09-13-tri-coach-04-checkin-and-follow-on.md`.
- tri-analyze alignment (2026-09): flat layout, settings and LangSmith project, prompt rendered per call
  from runtime context with a tool guide, chat hardening, coach passes the context; tracked in
  `docs/superpowers/plans/2026-09-13-tri-analyze-01-alignment.md`. Eval (2026-09): `tri-analyze eval`,
  twelve cases, three code checks and a judge; tracked in
  `docs/superpowers/plans/2026-09-13-tri-analyze-02-eval.md`.
- tri-web sub-project 1 (2026-09): server (`tri-web serve`), React shell, Today strip, coach chat with the review gate (schema form and YAML), sync and check-in jobs, memory and reset; tracked in `docs/superpowers/plans/2026-09-14-tri-web-0*.md`. Sub-projects 2 to 4 (progress, nutrition, labs) unspecced.
