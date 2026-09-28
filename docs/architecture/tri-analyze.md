# tri-analyze

[Architecture index](README.md) · [Package README](../../packages/tri-analyze/README.md)

One read-only agent that answers training questions. Its prompt is rebuilt before every model call from the athlete's profile, zones, recent load and workouts. It can only read: SQL as `tri_reader` and five allow-listed MCP getters.

![tri-analyze](diagrams/tri-analyze.svg)

- **Hosts.** `tri-analyze chat` runs it on thread `analyze`. The coach's `ask_analyst` builds a fresh one on a throwaway thread for each question. The eval target runs it against a seeded database.
- **Agent.** `build_agent` calls `build_chat_agent` with `Role.ANALYST` (opus-5, medium effort). Middleware runs `analyst_prompt` (prompt v3) first, then `claude_fallback`, then prompt caching.
- **Context.** `load_athlete_context` reads `athlete_profile`, 7 days of `daily_metrics` and workouts from 7 days either side of today. The prompt names today with its weekday, the Monday each nearby week starts on, thresholds, and power, heart-rate and pace zones from TrainingPeaks.
- **Tools.** `query_training_db` runs as `tri_reader`. The live reads are `get_activity`, `get_activity_splits`, `get_training_readiness` and `get_hrv_data` from Garmin, and `tp_get_workout` from TrainingPeaks. Everything else stays behind the sync.

## Evals

`tri-analyze eval --eval-db URL` seeds a history starting 2026-06-01 into a database that isn't the athlete's. It refuses a database holding rows it didn't write, and it checks that `tri_reader` can read the seed. It runs 12 cases with real SQL and stubbed live tools, then scores them with three code checks (`uses_sql`, `pulls_splits`, `states_window`) and judge v2 (`grounded`, plus `feedback_quality` on session cases). The seed is truncated at the end.
