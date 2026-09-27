#!/usr/bin/env bash
# One-command local setup: Python env, Postgres container, both databases migrated (with
# LangGraph's checkpoint and store tables), and a .env to fill in. Safe to re-run: `tri migrate`
# records what it applied and skips it next time.
#
#   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

USER_=tri_analyze

step() { printf '\n== %s\n' "$*"; }
psql_in() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$USER_" "$@"; }

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

if [[ "$(psql_in -d postgres -tAc "select 1 from pg_database where datname = 'tri_analyze_test'")" != 1 ]]; then
  step "Creating database tri_analyze_test"
  psql_in -d postgres -c "create database tri_analyze_test"
fi

step "Migrations: tri_analyze and tri_analyze_test"
uv run tri migrate
uv run tri migrate --test

if [[ ! -f .env ]]; then
  cp .env.example .env
  step "Created .env from .env.example: fill in ANTHROPIC_API_KEY"
fi

step "Done. MCP server auth and the first sync are manual (README Setup, steps 4-5)."
