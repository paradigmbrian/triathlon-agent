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

`./setup.sh` does steps 1 and 2 and creates `.env` from the example (step 3): it needs uv
and a running Docker, and is safe to re-run (`tri migrate` skips what it already applied).
Steps 3 (the API key), 4 and 5 stay manual. The steps it automates:

1. Python 3.12 via uv, from the repository root: `uv sync` (installs every package editable
   and their console scripts into one `.venv`).
2. Postgres (Docker, host port 5435): `docker compose up -d`, create the test database once, then
   migrate both:
   ```bash
   docker compose exec db psql -U tri_analyze -c "create database tri_analyze_test;"
   uv run tri migrate && uv run tri migrate --test
   ```
   `tri migrate` applies `migrations/*.sql` in order, records each in `schema_migrations`,
   refuses a file edited after it was applied, and creates LangGraph's checkpoint and store
   tables. `--dry-run` prints what would run.
3. `cp .env.example .env`, then fill in `ANTHROPIC_API_KEY` (from console.anthropic.com).
   Optional but recommended while learning: `LANGSMITH_TRACING=true` and
   `LANGSMITH_API_KEY` (free at smith.langchain.com) to see every prompt and tool call.
4. Authenticate the MCP servers once (`<ref>` values are in `.env.example`):
   ```bash
   uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@<ref> garmin-mcp-auth
   # log into app.trainingpeaks.com in Chrome first, then:
   uvx --from 'tp-mcp[browser] @ git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<ref>' tp-mcp auth --from-browser chrome
   uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<ref> tp-mcp auth-status
   ```
5. First sync: `uv run tri sync --full` (a year of TrainingPeaks, 60 days of Garmin).

## Run

```bash
uv run tri sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]
uv run tri migrate [--test] [--dry-run]
uv run tri-analyze chat [--no-live]     # --no-live binds only the database tool
uv run tri-analyze eval [--recreate-dataset] [--cases A,B] [--failed-from F] [--rescore F]   # LangSmith feedback eval; see Evals and cost
uv run tri-planning chat [--no-live]    # plan; every TrainingPeaks write is approved first
uv run tri-planning check-in [--yes] [--no-sync] [--no-live]   # sync, review last 7 days, propose; exit 3 when paused, 1 on a model error, a week or note not proposed for violations, or a change --yes skipped for violations
uv run tri-planning reset [--yes]       # abandon goal and plan, clear the thread
uv run tri-wellness ingest <file.pdf|csv> [--kind pdf|export] [--drawn-on YYYY-MM-DD]   # extract, review, store a lab panel
uv run tri-wellness report [--panel ID] [--out path.md]   # interpret a stored panel; saved to lab_reports
uv run tri-wellness chat                                   # ask about panels and reports
uv run tri-wellness panels                                 # list stored panels
uv run tri-wellness eval [--recreate-dataset] [--cases A,B] [--failed-from F] [--rescore F]  # LangSmith report evaluators
uv run tri-coach chat [--no-live]       # the front door: one conversation over the analyst, wellness, planning and nutrition
uv run tri-coach check-in [--yes] [--no-sync] [--no-live]   # sync, weekly checklist over plan and nutrition; exit 3 when paused, 1 on a model error, a week or note not proposed for violations, or a change --yes skipped for violations
uv run tri-coach eval [--recreate-dataset] [--cases A,B] [--failed-from F] [--rescore F]     # LangSmith routing eval
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

### Evals and cost

Every `eval` run calls Claude on the target's model and, where the package has one, on the judge.
A full run costs about $1 (2026-09-24: nine runs for about $9.50). Each run ends with a usage
line, and writes the same figures to the `usage` key of its `.evals/` file:

```text
usage: analyst 400k in / 40k out (cache read 300k) $1.65 · judge 96k in / 8.0k out $0.68 · total $2.33
```

There are cheaper ways to check a change before the full run that gates it:

```bash
uv run tri-analyze eval --rescore .evals/<file>.jsonl      # judge change: re-score saved answers; no analyst calls, always local
uv run tri-analyze eval --failed-from .evals/<file>.jsonl  # re-run only what failed or errored
uv run tri-analyze eval --cases last_z2_ride,brick_sunday  # re-run named cases
TRI_MODEL_JUDGE=claude-sonnet-5 uv run tri-analyze eval --rescore .evals/<file>.jsonl  # iteration only: a cheaper judge
```

The same flags work on every package's `eval`. A subset's experiment name ends in `-subset`, and
its header reads `N of M examples (subset)`; it is never a gate. `--rescore` with `--failed-from`
on the same file re-judges only the failures. Plans estimate a run from the latest `.evals/`
file's `usage.total_cost` (see `CLAUDE.md`).

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

CI (`.github/workflows/ci.yml`) runs the same checks on every push to `main` and every pull
request: a Postgres 16 service, `tri migrate` on both databases, `ruff format --check`, `ruff
check`, `pytest` (failing if anything but a `--live` test skips), `mypy`, and in `web/` `npm run
lint`, `npm run build` (strict TypeScript) and `npm test`. Playwright stays local. Branch
protection on `main` is set in the GitHub UI.

## Layout

```
pyproject.toml          workspace root: members, shared ruff/mypy/pytest config
conftest.py             pytest options and the shared `db` fixture plugin
migrations/             001_initial.sql (sync tables), 002_planning.sql and 003_rename_skeleton_to_targets.sql (planning tables), 004_nutrition.sql (nutrition tables), 005_wellness.sql (lab tables), 006_fixes.sql (2026-09-24 correctness fixes), 007_data_layer.sql (tombstones, garmin_activities, change status), 008_guardrails.sql (plan_weeks.violations for a refused week), 009_schema_migrations.sql (the tri migrate record), 010_reader_role.sql (the SQL tool's tri_reader role)
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

