# tri_analyze

Triathlon training analysis agent (LangChain) over Garmin Connect and TrainingPeaks data.

## Setup

1. `uv sync`
2. `docker compose up -d`, then apply `migrations/*.sql` to both `tri_analyze` and `tri_analyze_test`:
   ```bash
   docker compose exec db psql -U tri_analyze -c "create database tri_analyze_test;"
   docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/001_initial.sql
   docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/001_initial.sql
   ```
3. `cp .env.example .env` and fill in keys.
4. Authenticate the MCP servers once (`<ref>` values are in `.env.example`):
   - Garmin: `uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@<ref> garmin-mcp-auth`
   - TrainingPeaks: `uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<ref> tp-mcp auth --from-browser chrome`

## Commands

- `uv run tri-analyze sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]`
- `uv run pytest` (add `--live` to hit real servers; `db`-marked tests skip when Postgres is down)
- `uv run python scripts/spike_mcp.py` re-records `tests/fixtures/mcp/` (scrub before committing)

## Layout

See `docs/superpowers/specs/2026-09-06-tri-analyze-design.md`.
