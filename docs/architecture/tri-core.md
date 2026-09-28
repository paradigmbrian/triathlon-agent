# tri-core

[Architecture index](README.md) · [Package README](../../packages/tri-core/README.md) · [Harness](harness.md)

The shared library. It has no agent of its own. It holds the harness, model routing, the database and MCP layers, sync and the eval tail every package's runner ends in. Every other package depends on it; it depends on no other package.

![tri-core](diagrams/tri-core.svg)

- **harness.** `make_subagent` and `build_chat_agent` are the only builders of a `create_agent` loop. Middleware runs in a fixed order: the caller's own, then `claude_fallback`, then prompt caching last. [harness.md](harness.md) covers the other modules.
- **llm.** `resolve` takes `TRI_MODEL_<ROLE>`, else `TRI_MODEL`, else the role's `DEFAULTS` entry. Only retryable errors fall back along opus-5 → opus-4-8 → sonnet-5. The three carriers are `claude_fallback`, `structured()` and `streaming()`. The defaults: `analyst` on opus-5 at medium effort, `nutrition_fuel` on sonnet-5, every other role on opus-5; `lab_extract` and `lab_report` get 32k output tokens.
- **db.** `recorded_write` commits a `pending` row, makes the MCP call, then marks the row `applied`. A definitive rejection marks it `failed`; any other error leaves it pending and raises `OutcomeUnknown`. `query_training_db` runs as `tri_reader`: one `SELECT` or `WITH` in a read-only transaction, 5 s timeout, at most 200 rows and 8,000 characters.
- **mcp.** Both servers launch through `uvx` from git at a pinned ref. `child_env` passes only `PATH`, `HOME`, `TMPDIR`, `LANG` and `LC_ALL`, so the servers never see the API key or a database URL. Sync uses `McpToolClient`; agents get allow-listed tools from `open_live_servers`; `apply` writes through `ToolsCaller` on the same sessions.
- **sync.** TrainingPeaks fills `athlete_profile`, `workouts` and `daily_metrics`. Garmin fills `daily_metrics` and `garmin_activities`, and `match_activities` links each activity to its workout. A `sync_state` watermark per source re-reads a 3-day overlap. One source failing does not stop the other.
- **evals.** `eval_select` turns `--cases`, `--failed-from` and `--rescore` into a selection. Each package's `evals/run.py` ends in `finish_run`, which logs pass rates, failed checks, token usage and estimated cost, and writes `.evals/<experiment>.jsonl`.

## Postgres tables

| Migration | Tables |
|---|---|
| 001 | `athlete_profile`, `daily_metrics`, `sync_state`, `workouts` |
| 002 | `training_goals`, `training_plans`, `plan_weeks`, `plan_changes` |
| 004 | `nutrition_targets`, `fuel_plans`, `nutrition_changes` |
| 005 | `lab_panels`, `lab_results`, `lab_reports` |
| 007 | `garmin_activities` |
| 009 | `schema_migrations` |
| 010 | the `tri_reader` role and its grants |

Migrations 003, 006 and 008 alter existing tables. `tri migrate` also creates LangGraph's checkpoint and store tables.

## Commands

```
uv run tri sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]
uv run tri migrate [--test] [--dry-run]
```
