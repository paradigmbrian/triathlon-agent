# Architecture

The repo as of 2026-09-28 (main @ 9f4f048). This page is the whole repo; each package has its own page below, and [harness.md](harness.md) covers the layer every agent is built on: how a coach turn runs, how handoffs work, and which model each role uses.

The diagrams are SVG files in [`diagrams/`](diagrams/). They follow the reader's light or dark theme.

## The whole repo

![The whole repo](diagrams/repo.svg)

Read it top to bottom. Arrows point from a caller to what it depends on.

- **Hosts.** Every package has its own CLI and runs standalone. `tri-coach chat` and `check-in` run the coach in the terminal. The React app in `web/` reaches the same coach through tri-web. Each package's `eval` command runs that package's eval and writes its rows to `.evals/`.
- **tri-web** is a loopback-only FastAPI server. It opens one coach runtime and one lock, so a browser turn, a review, the check-in job and a reset never run the coach thread at the same time.
- **tri-coach** is the only package that pulls in other agent packages. It embeds the planning and nutrition graphs and consults them, and it calls the analyst and wellness agents as tools (`ask_analyst`, `ask_wellness`). Its `apply` node is the only place a coach run writes to TrainingPeaks or Garmin.
- **Domain packages** depend on tri-core and on nothing else. Each one also runs on its own, with its own review and apply where it writes.
- **tri-core** holds the harness, model routing (`tri_core.llm`), the database layer, the MCP sessions, `tri sync` and the eval tail every runner ends in.
- **Systems.** Postgres has two roles: the writer (`DATABASE_URL`) for sync, repositories and recorded writes, and the read-only `tri_reader` role every SQL tool runs as. Garmin and TrainingPeaks are MCP servers that run as stdio subprocesses through `uvx`. LangSmith is optional; `--local` runs evals without it.

tri-web imports `tri_planning` and `tri_nutrition` directly but declares only tri-core and tri-coach in its `pyproject.toml`. It works because tri-coach depends on both.

## Per package

| Package | Architecture | Package README |
|---|---|---|
| tri-core | [tri-core.md](tri-core.md) | [packages/tri-core](../../packages/tri-core/README.md) |
| tri-coach | [tri-coach.md](tri-coach.md) | [packages/tri-coach](../../packages/tri-coach/README.md) |
| tri-planning | [tri-planning.md](tri-planning.md) | [packages/tri-planning](../../packages/tri-planning/README.md) |
| tri-nutrition | [tri-nutrition.md](tri-nutrition.md) | [packages/tri-nutrition](../../packages/tri-nutrition/README.md) |
| tri-analyze | [tri-analyze.md](tri-analyze.md) | [packages/tri-analyze](../../packages/tri-analyze/README.md) |
| tri-wellness | [tri-wellness.md](tri-wellness.md) | [packages/tri-wellness](../../packages/tri-wellness/README.md) |
| tri-web | [tri-web.md](tri-web.md) | [packages/tri-web](../../packages/tri-web/README.md) |

The diagrams share one key:

| Shape | Means |
|---|---|
| Teal fill | an agent loop (`create_agent`, built by `tri_core.harness.agents`) |
| Teal outline | one model call (`structured()` or `streaming()`), or a read-only tool |
| Plain box | plain code, no model |
| Orange | a human gate (`interrupt()`) or the write path |
| Dashed grey | an outside system: Postgres, Garmin, TrainingPeaks, Anthropic, LangSmith |

Teal arrows are tool calls and handoffs; orange arrows are writes.

## Changed since the 2026-09-24 map

- **Data layer.** Garmin activities are stored and matched to workouts. Writes are recorded before they run (`tri_core.db.writes.recorded_write`). `tri migrate` tracks migrations in `schema_migrations`. SQL tools run as the read-only `tri_reader` role (migration 010).
- **Guardrails.** Weeks that fail the TSS validator are stored with their violations and not proposed. The coach has a consult budget of two per domain per turn. Held proposals survive a partial apply or a reject. Embedded sub-graphs run without a checkpointer.
- **Evaluators.** One shared pass-rate module. The judges grade grounding. The analyst eval runs real SQL against a seeded history and refuses the athlete's database.
- **Analyst grounding.** Prompt v3 adds weekdays, Monday week starts and TrainingPeaks zones to the context. Judge v2 checks that numbers can be reproduced from the evidence.
- **Eval cost.** Every run logs per-role tokens and estimated cost. `--rescore`, `--cases` and `--failed-from` rerun only what a change needs.
