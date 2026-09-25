#!/usr/bin/env bash
# One-command local setup: Python env, Postgres container, both databases migrated, LangGraph
# checkpoint/store tables, and a .env to fill in. Safe to re-run: each migration is skipped when
# its probe (a table or column it creates) is already present.
#
# Interim until the hygiene spec's `tri migrate` lands; then the migration loop below becomes
# `uv run tri migrate && uv run tri migrate --test`.
#
#   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

USER_=tri_analyze
DATABASES=(tri_analyze tri_analyze_test)
URL_BASE="postgresql://tri_analyze:tri_analyze@localhost:5435"

step() { printf '\n== %s\n' "$*"; }
psql_in() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$USER_" "$@"; }
query() { psql_in -d "$1" -tAc "$2"; }

# What each migration creates; present means applied. A new migration needs a line here.
probe() {
  case "$1" in
    001_initial.sql) echo "select to_regclass('public.workouts') is not null" ;;
    002_planning.sql) echo "select to_regclass('public.training_goals') is not null" ;;
    003_rename_skeleton_to_targets.sql)
      echo "select exists (select 1 from information_schema.columns
            where table_name = 'training_plans' and column_name = 'targets')" ;;
    004_nutrition.sql) echo "select to_regclass('public.nutrition_targets') is not null" ;;
    005_wellness.sql) echo "select to_regclass('public.lab_panels') is not null" ;;
    006_fixes.sql)
      echo "select exists (select 1 from information_schema.columns
            where table_name = 'lab_results' and column_name = 'bound')" ;;
    007_data_layer.sql) echo "select to_regclass('public.garmin_activities') is not null" ;;
    *) return 1 ;;
  esac
}

command -v uv >/dev/null || { echo "uv not found: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }

step "Python environment (uv sync)"
uv sync

step "Postgres container (localhost:5435, container tri-analyze-db)"
docker compose up -d db
for _ in $(seq 1 30); do
  docker compose exec -T db pg_isready -U "$USER_" >/dev/null 2>&1 && break
  sleep 1
done
docker compose exec -T db pg_isready -U "$USER_" >/dev/null || { echo "Postgres not ready" >&2; exit 1; }

if [[ "$(query postgres "select 1 from pg_database where datname = 'tri_analyze_test'")" != 1 ]]; then
  step "Creating database tri_analyze_test"
  psql_in -d postgres -c "create database tri_analyze_test"
fi

for db in "${DATABASES[@]}"; do
  step "Migrations: $db"
  for f in migrations/*.sql; do
    name=$(basename "$f")
    if ! sql=$(probe "$name"); then
      echo "no probe for $name: add one to probe() in setup.sh before running it" >&2
      exit 1
    fi
    if [[ "$(query "$db" "$sql")" == t ]]; then
      echo "  $name: already applied"
    else
      echo "  $name: applying"
      psql_in -d "$db" -1 -q < "$f"
    fi
  done
  step "Checkpoint and store tables: $db"
  uv run python scripts/setup_checkpointer.py "$URL_BASE/$db"
done

if [[ ! -f .env ]]; then
  cp .env.example .env
  step "Created .env from .env.example: fill in ANTHROPIC_API_KEY"
fi

step "Done. MCP server auth and the first sync are manual (README Setup, steps 4-5)."
