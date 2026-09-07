# tri_analyze Foundation and Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Python project, a local Postgres store, an MCP client wrapper, and the `tri-analyze sync` command that pulls TrainingPeaks and Garmin data into Postgres. This is spec milestones 1 and 2. The agent (milestones 3 and 4) is a separate plan written after this one lands.

**Architecture:** A uv-managed Python 3.12 package `tri_analyze`. Sync is deterministic ETL: it launches each MCP server as a subprocess over stdio, calls tools programmatically with the `mcp` Python SDK, parses the JSON text they return, and upserts into four Postgres tables. Parsers are pure functions over dicts so they test without a network; fetchers wrap parsers with date chunking; a runner sequences sources with per-source error isolation and watermarks.

**Tech Stack:** Python 3.12, uv, psycopg 3 (dict rows), pydantic-settings, typer, mcp 1.29 (via `langchain-mcp-adapters` pin), pytest + pytest-asyncio, ruff, mypy, Docker `postgres:16`.

**Spec:** `docs/superpowers/specs/2026-09-06-tri-analyze-design.md`

## Global Constraints

- Python `>=3.12,<3.13`. uv manages the venv. `uv run` prefixes every command.
- Pinned deps: `langchain==1.4.0`, `langchain-anthropic==1.7.1`, `langchain-mcp-adapters==0.3.2` (brings `mcp` 1.29.x), `psycopg[binary]==3.3.5`, `pydantic-settings>=2.6`, `typer>=0.15`, `rich>=13`.
- Pinned MCP servers: garmin_mcp `e8554bcd761a4494dc12a98461224bb3dcf1fbc5`, trainingpeaks-mcp `a412a84eb4f9c8f03e108a1f27beb053d83a207d`. Both launched with `uvx`.
- Postgres: `postgres:16` in Docker on host port **5435**, db `tri_analyze`, user `tri_analyze`, password `tri_analyze`. Test db `tri_analyze_test` on the same server.
- **Brian runs all DDL and all git commands.** The assistant writes migration files and prints commands. Every "Commit" step below is a command for Brian to run, not for the assistant to execute. Every integration test that needs a database must skip cleanly with a message when the database is unreachable.
- All timestamps in Postgres are `timestamptz` except `workouts.start_time_local`, which is a naive local `timestamp` because Garmin reports local time without an offset.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`.
- Every markdown file created under this project is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/tri-analyze-agent/<same relative path>`.

---

## File Structure

```
tri-analyze-agent/
  pyproject.toml
  docker-compose.yml
  .env.example
  .gitignore
  migrations/
    001_initial.sql
  scripts/
    spike_mcp.py                  # one-off: calls each tool we depend on, saves fixtures
  src/tri_analyze/
    __init__.py
    config.py                     # Settings (pydantic-settings), get_settings()
    cli.py                        # typer app: sync
    mcp/
      __init__.py
      servers.py                  # ServerSpec + garmin_spec()/trainingpeaks_spec()
      client.py                   # McpToolClient, McpToolError, parse_tool_text()
    db/
      __init__.py
      connection.py               # connect(url) -> psycopg Connection with dict rows
      models.py                   # AthleteProfileRow, WorkoutRow, DailyMetricsRow, SyncState
      repo.py                     # upsert_* and sync_state helpers
    sync/
      __init__.py
      dates.py                    # date_chunks()
      sports.py                   # normalize_tp_sport(), normalize_garmin_sport()
      trainingpeaks.py            # parse_* pure functions + fetch_trainingpeaks()
      garmin.py                   # parse_* pure functions + fetch_garmin()
      match.py                    # match_activities()
      runner.py                   # run_sync() -> SyncReport
  tests/
    conftest.py                   # db fixture (skips if unreachable), fake MCP session
    fixtures/mcp/                 # recorded by scripts/spike_mcp.py; committed after Brian scrubs them
    test_config.py
    test_db_connection.py
    test_mcp_client.py
    test_repo.py
    test_sync_dates.py
    test_sync_sports.py
    test_sync_trainingpeaks.py
    test_sync_garmin.py
    test_sync_match.py
    test_sync_runner.py
```

Responsibilities: `mcp/` knows how to talk to servers and nothing about training. `sync/*.py` parsers know the servers' JSON shapes and produce `db/models.py` rows. `db/repo.py` knows SQL. `runner.py` is the only place that knows the order of operations.

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/tri_analyze/__init__.py`, `src/tri_analyze/config.py`, `src/tri_analyze/mcp/__init__.py`, `src/tri_analyze/db/__init__.py`, `src/tri_analyze/sync/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `tri_analyze.config.Settings` (pydantic-settings model) and `tri_analyze.config.get_settings() -> Settings` (lru-cached). Fields listed in Step 3.

- [ ] **Step 1: Create the uv project and pyproject.toml**

Run: `cd /Users/brian/Development/paradigm/fitness_agents/tri-analyze-agent && uv init --python 3.12 --package --name tri-analyze --no-readme` then replace the generated `pyproject.toml` with:

```toml
[project]
name = "tri-analyze"
version = "0.1.0"
description = "Triathlon training analysis agent over Garmin + TrainingPeaks data"
requires-python = ">=3.12,<3.13"
dependencies = [
    "langchain==1.4.0",
    "langchain-anthropic==1.7.1",
    "langchain-mcp-adapters==0.3.2",
    "psycopg[binary]==3.3.5",
    "pydantic-settings>=2.6",
    "typer>=0.15",
    "rich>=13",
]

[project.scripts]
tri-analyze = "tri_analyze.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tri_analyze"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.13",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "db: needs a reachable Postgres (skips otherwise)",
    "live: talks to real MCP servers (opt-in with --live)",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["langchain_mcp_adapters.*", "mcp.*"]
ignore_missing_imports = true
```

Then run: `uv sync` and confirm `.venv` exists and `uv run python -c "import langchain, mcp, psycopg; print(mcp.__version__ if hasattr(mcp,'__version__') else 'ok')"` prints without error.

- [ ] **Step 2: Write .gitignore and .env.example**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
.mypy_cache/
.ruff_cache/
.pytest_cache/
dist/
```

`.env.example`:
```
# Anthropic (used by the agent, not by sync)
ANTHROPIC_API_KEY=

# Postgres (docker-compose.yml default)
DATABASE_URL=postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
TEST_DATABASE_URL=postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test

# Garmin: only needed to (re)authenticate; tokens live in ~/.garminconnect
GARMIN_EMAIL=
GARMIN_PASSWORD=

# TrainingPeaks: optional; leave blank if you ran `tp-mcp auth`
TP_AUTH_COOKIE=

# Pinned MCP server commits
GARMIN_MCP_REF=e8554bcd761a4494dc12a98461224bb3dcf1fbc5
TP_MCP_REF=a412a84eb4f9c8f03e108a1f27beb053d83a207d

# Agent model (used later)
TRI_MODEL=claude-opus-5

# LangSmith (optional, recommended while learning)
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=tri-analyze
```

- [ ] **Step 3: Write the failing config test**

`tests/test_config.py`:
```python
from tri_analyze.config import Settings


def test_defaults_when_env_empty(monkeypatch):
    for key in ("DATABASE_URL", "TEST_DATABASE_URL", "GARMIN_MCP_REF", "TP_MCP_REF", "TRI_MODEL"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql://tri_analyze:tri_analyze@localhost:5435/")
    assert s.database_url.endswith("/tri_analyze")
    assert s.test_database_url.endswith("/tri_analyze_test")
    assert s.garmin_mcp_ref == "e8554bcd761a4494dc12a98461224bb3dcf1fbc5"
    assert s.tp_mcp_ref == "a412a84eb4f9c8f03e108a1f27beb053d83a207d"
    assert s.tri_model == "claude-opus-5"
    assert s.anthropic_api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/x")
    monkeypatch.setenv("TRI_MODEL", "claude-sonnet-5")
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql://u:p@h:1/x"
    assert s.tri_model == "claude-sonnet-5"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.config'`

- [ ] **Step 5: Implement config.py and package inits**

`src/tri_analyze/__init__.py`: `"""tri_analyze: triathlon training analysis agent."""`
`src/tri_analyze/mcp/__init__.py`, `src/tri_analyze/db/__init__.py`, `src/tri_analyze/sync/__init__.py`, `tests/__init__.py`: empty.

`src/tri_analyze/config.py`:
```python
"""Application settings loaded from environment and .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze"
    test_database_url: str = "postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze_test"

    garmin_email: str | None = None
    garmin_password: str | None = None
    tp_auth_cookie: str | None = None

    garmin_mcp_ref: str = "e8554bcd761a4494dc12a98461224bb3dcf1fbc5"
    tp_mcp_ref: str = "a412a84eb4f9c8f03e108a1f27beb053d83a207d"

    tri_model: str = "claude-opus-5"

    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "tri-analyze"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

`tests/conftest.py` (initial; extended in Task 2):
```python
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", default=False, help="run tests that hit real MCP servers")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
```

- [ ] **Step 6: Run tests, lint, types**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: 2 passed; ruff clean (run `uv run ruff format .` if format check fails); mypy `Success`.

- [ ] **Step 7: Commit (Brian runs)**

```bash
git init 2>/dev/null; git add pyproject.toml uv.lock .gitignore .env.example src tests docs
git commit -m "feat: scaffold tri_analyze project with settings"
```

---

### Task 2: Postgres container, initial migration, connection helper

**Files:**
- Create: `docker-compose.yml`, `migrations/001_initial.sql`, `src/tri_analyze/db/connection.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_db_connection.py`

**Interfaces:**
- Produces: `tri_analyze.db.connection.connect(url: str) -> psycopg.Connection[dict[str, Any]]` (autocommit off, `dict_row` factory). `tests/conftest.py` fixture `db` yielding a connection to the test database inside a transaction that is rolled back after each test, skipping when unreachable.

- [ ] **Step 1: Write docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16
    container_name: tri-analyze-db
    ports:
      - "5435:5432"
    environment:
      POSTGRES_USER: tri_analyze
      POSTGRES_PASSWORD: tri_analyze
      POSTGRES_DB: tri_analyze
    volumes:
      - tri_analyze_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tri_analyze"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  tri_analyze_pgdata:
```

- [ ] **Step 2: Write migrations/001_initial.sql**

```sql
-- 001_initial.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists athlete_profile (
  id              int primary key default 1 check (id = 1),
  tp_athlete_id   text,
  ftp_watts       int,
  run_threshold_pace_sec_per_km  int,
  swim_css_sec_per_100m          int,
  lthr_bpm        int,
  max_hr_bpm      int,
  hr_zones        jsonb,
  power_zones     jsonb,
  pace_zones      jsonb,
  weight_kg       numeric(5,2),
  raw             jsonb not null,
  updated_at      timestamptz not null default now()
);

create table if not exists workouts (
  tp_workout_id       text primary key,
  workout_date        date not null,
  sport               text not null,
  sport_raw           text,
  title               text,
  description         text,
  completed           boolean not null default false,
  planned_duration_sec  int,
  planned_distance_m    numeric,
  planned_tss           numeric,
  planned_if            numeric,
  actual_duration_sec   int,
  actual_distance_m     numeric,
  actual_tss            numeric,
  actual_if             numeric,
  normalized_power    int,
  avg_power           int,
  avg_hr              int,
  avg_cadence         numeric,
  elevation_gain_m    numeric,
  calories            int,
  feeling             int,
  rpe                 int,
  comments            jsonb,
  structure           jsonb,
  garmin_activity_id  text unique,
  start_time_local    timestamp,
  raw                 jsonb not null,
  synced_at           timestamptz not null default now()
);
create index if not exists workouts_date_idx on workouts (workout_date);
create index if not exists workouts_sport_date_idx on workouts (sport, workout_date);

create table if not exists daily_metrics (
  metric_date       date primary key,
  sleep_seconds     int,
  sleep_score       int,
  hrv_overnight_avg int,
  resting_hr        int,
  body_battery_high int,
  body_battery_low  int,
  stress_avg        int,
  training_readiness int,
  garmin_raw        jsonb,
  ctl               numeric,
  atl               numeric,
  tsb               numeric,
  tss_day           numeric,
  tp_raw            jsonb,
  synced_at         timestamptz not null default now()
);

create table if not exists sync_state (
  source            text primary key,
  last_synced_date  date not null,
  last_run_at       timestamptz not null,
  last_status       text not null,
  last_error        text
);
```

Note: `daily_metrics.tss_day` was added relative to the spec's schema because `tp_get_fitness` returns per-day TSS alongside CTL/ATL/TSB and it is the single most useful trend column. Update spec §4.2 to include it (one line).

- [ ] **Step 3: Brian starts Postgres and applies the migration**

Print these for Brian to run; do not run them:

```bash
cd /Users/brian/Development/paradigm/fitness_agents/tri-analyze-agent
docker compose up -d
docker compose exec db pg_isready -U tri_analyze
docker compose exec db psql -U tri_analyze -c "create database tri_analyze_test;"
docker compose exec -T db psql -U tri_analyze -d tri_analyze < migrations/001_initial.sql
docker compose exec -T db psql -U tri_analyze -d tri_analyze_test < migrations/001_initial.sql
cp .env.example .env
```

Wait for confirmation before continuing.

- [ ] **Step 4: Write the failing connection test**

`tests/test_db_connection.py`:
```python
import pytest

pytestmark = pytest.mark.db


def test_tables_exist(db):
    rows = db.execute(
        "select table_name from information_schema.tables where table_schema='public' order by 1"
    ).fetchall()
    names = {r["table_name"] for r in rows}
    assert {"athlete_profile", "workouts", "daily_metrics", "sync_state"} <= names


def test_rows_are_dicts(db):
    row = db.execute("select 1 as one").fetchone()
    assert row == {"one": 1}
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_db_connection.py -v`
Expected: ERROR `fixture 'db' not found`

- [ ] **Step 6: Implement connection.py and the db fixture**

`src/tri_analyze/db/connection.py`:
```python
"""Postgres connection factory."""

from typing import Any

import psycopg
from psycopg.rows import dict_row


def connect(url: str) -> psycopg.Connection[dict[str, Any]]:
    """Open a connection with dict rows and autocommit off.

    Callers own commit/rollback. Use as a context manager.
    """
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)
```

Add to `tests/conftest.py` (imports go at the top of the file with the existing `import pytest`; the fixture goes below the hooks):
```python
from collections.abc import Iterator
from typing import Any

import psycopg

from tri_analyze.config import Settings
from tri_analyze.db.connection import connect


@pytest.fixture
def db() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Connection to the test database; every test runs in a rolled-back transaction."""
    url = Settings().test_database_url
    try:
        conn = connect(url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable at {url}: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

- [ ] **Step 7: Run tests, lint, types**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass (db tests skip with a clear message if the container is down; ask Brian to start it if so).

- [ ] **Step 8: Commit (Brian runs)**

```bash
git add docker-compose.yml migrations src/tri_analyze/db tests/conftest.py tests/test_db_connection.py
git commit -m "feat: postgres compose, initial schema, connection helper"
```

---

### Task 3: MCP client wrapper

**Files:**
- Create: `src/tri_analyze/mcp/servers.py`, `src/tri_analyze/mcp/client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Produces:
  - `ServerSpec` dataclass: `name: str`, `command: str`, `args: list[str]`, `env: dict[str, str]`.
  - `garmin_spec(settings: Settings) -> ServerSpec`, `trainingpeaks_spec(settings: Settings) -> ServerSpec`.
  - `class McpToolError(Exception)` with `.tool: str`, `.message: str`.
  - `parse_tool_text(tool: str, text: str) -> Any | None` pure: returns parsed JSON, `None` for Garmin's "No … found" empty convention, raises `McpToolError` for Garmin "Error …" strings, TP `{"isError": true}` dicts, or unparseable text.
  - `class McpToolClient` async context manager: `McpToolClient(spec)`; `await client.call_json(tool: str, args: dict[str, Any] | None = None) -> Any | None`; `await client.list_tool_names() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mcp_client.py`:
```python
import json
from types import SimpleNamespace

import pytest
from mcp.types import TextContent

from tri_analyze.config import Settings
from tri_analyze.mcp.client import McpToolClient, McpToolError, parse_tool_text
from tri_analyze.mcp.servers import garmin_spec, trainingpeaks_spec


def test_parse_json_object():
    assert parse_tool_text("t", json.dumps({"a": 1})) == {"a": 1}


def test_parse_garmin_empty_convention_returns_none():
    assert parse_tool_text("get_stats", "No stats found for 2026-01-01") is None


def test_parse_garmin_error_raises():
    with pytest.raises(McpToolError) as ei:
        parse_tool_text("get_stats", "Error retrieving stats: boom")
    assert ei.value.tool == "get_stats"
    assert "boom" in ei.value.message


def test_parse_tp_iserror_raises():
    payload = {"isError": True, "error_code": "AUTH_INVALID", "message": "Re-authenticate."}
    with pytest.raises(McpToolError) as ei:
        parse_tool_text("tp_get_workouts", json.dumps(payload))
    assert "AUTH_INVALID" in ei.value.message


def test_parse_garbage_raises():
    with pytest.raises(McpToolError):
        parse_tool_text("t", "not json at all")


def test_specs_use_pinned_refs():
    s = Settings(_env_file=None)
    g = garmin_spec(s)
    assert g.command == "uvx"
    assert any(s.garmin_mcp_ref in a for a in g.args)
    assert "GARMIN_ENABLED_TOOLS" in g.env
    t = trainingpeaks_spec(s)
    assert any(s.tp_mcp_ref in a for a in t.args)
    assert t.args[-2:] == ["tp-mcp", "serve"]


def test_tp_cookie_passed_through_env():
    s = Settings(_env_file=None, tp_auth_cookie="abc")
    assert trainingpeaks_spec(s).env["TP_AUTH_COOKIE"] == "abc"


class _FakeSession:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return SimpleNamespace(content=[TextContent(type="text", text=self.text)], isError=False)


async def test_call_json_uses_session_and_parses():
    client = McpToolClient.__new__(McpToolClient)
    client._session = _FakeSession(json.dumps({"ok": True}))  # type: ignore[attr-defined]
    out = await client.call_json("tp_get_profile", {"x": 1})
    assert out == {"ok": True}
    assert client._session.calls == [("tp_get_profile", {"x": 1})]  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.mcp.client'`

- [ ] **Step 3: Implement servers.py**

```python
"""Launch specifications for the two MCP servers."""

from dataclasses import dataclass, field

from tri_analyze.config import Settings

GARMIN_REPO = "https://github.com/Taxuspt/garmin_mcp"
TP_REPO = "https://github.com/JamsusMaximus/trainingpeaks-mcp"

# Only these Garmin tools get registered by the server (keeps the tool list small).
GARMIN_ENABLED_TOOLS = [
    "get_stats",
    "get_sleep_summary_range",
    "get_hrv_data",
    "get_training_readiness",
    "get_activities_by_date",
    "get_activity",
    "get_activity_splits",
]


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)


def garmin_spec(settings: Settings) -> ServerSpec:
    env = {
        "GARMIN_ENABLED_TOOLS": ",".join(GARMIN_ENABLED_TOOLS),
        "GARMIN_MCP_CALL_TIMEOUT": "90",
    }
    if settings.garmin_email:
        env["GARMIN_EMAIL"] = settings.garmin_email
    if settings.garmin_password:
        env["GARMIN_PASSWORD"] = settings.garmin_password
    return ServerSpec(
        name="garmin",
        command="uvx",
        args=["--python", "3.12", "--from", f"git+{GARMIN_REPO}@{settings.garmin_mcp_ref}", "garmin-mcp"],
        env=env,
    )


def trainingpeaks_spec(settings: Settings) -> ServerSpec:
    env: dict[str, str] = {}
    if settings.tp_auth_cookie:
        env["TP_AUTH_COOKIE"] = settings.tp_auth_cookie
    return ServerSpec(
        name="trainingpeaks",
        command="uvx",
        args=["--from", f"git+{TP_REPO}@{settings.tp_mcp_ref}", "tp-mcp", "serve"],
        env=env,
    )
```

- [ ] **Step 4: Implement client.py**

```python
"""Programmatic MCP client: launch a stdio server, call tools, parse JSON results."""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from tri_analyze.mcp.servers import ServerSpec


class McpToolError(Exception):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"{tool}: {message}")
        self.tool = tool
        self.message = message


def parse_tool_text(tool: str, text: str) -> Any | None:
    """Turn a tool's text result into data.

    Conventions observed in the two servers' source:
    - TrainingPeaks: always JSON; failures are {"isError": true, "error_code", "message"}.
    - Garmin: JSON on success; "No ... found ..." plain text when empty; "Error ..." on failure.
    """
    stripped = text.strip()
    if stripped.startswith("No "):
        return None
    if stripped.startswith("Error"):
        raise McpToolError(tool, stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise McpToolError(tool, f"non-JSON result: {stripped[:200]!r}") from exc
    if isinstance(data, dict) and data.get("isError"):
        code = data.get("error_code", "ERROR")
        raise McpToolError(tool, f"{code}: {data.get('message', '')}")
    return data


class McpToolClient:
    """Async context manager owning one server subprocess and one session."""

    def __init__(self, spec: ServerSpec) -> None:
        self.spec = spec
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> McpToolClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=self.spec.command,
            args=self.spec.args,
            env={**os.environ, **self.spec.env},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def list_tool_names(self) -> list[str]:
        assert self._session is not None, "use inside 'async with'"
        result = await self._session.list_tools()
        return [t.name for t in result.tools]

    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None:
        assert self._session is not None, "use inside 'async with'"
        result = await self._session.call_tool(tool, args or {})
        texts = [c.text for c in result.content if isinstance(c, TextContent)]
        if not texts:
            raise McpToolError(tool, "no text content in result")
        if getattr(result, "isError", False):
            raise McpToolError(tool, texts[0])
        return parse_tool_text(tool, "\n".join(texts))
```

- [ ] **Step 5: Run tests, lint, types**

Run: `uv run pytest tests/test_mcp_client.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: 8 passed, clean.

- [ ] **Step 6: Commit (Brian runs)**

```bash
git add src/tri_analyze/mcp tests/test_mcp_client.py
git commit -m "feat: MCP stdio client wrapper with result parsing"
```

---

### Task 4: MCP spike script and recorded fixtures

**Files:**
- Create: `scripts/spike_mcp.py`, `tests/fixtures/mcp/.gitkeep`
- Test: `tests/test_mcp_client.py` (append one live test)

**Interfaces:**
- Consumes: `McpToolClient`, `garmin_spec`, `trainingpeaks_spec`.
- Produces: JSON files under `tests/fixtures/mcp/` named `<tool>.json`, each `{"args": {...}, "result": <parsed>}`. Later parser tests load these when present.

- [ ] **Step 1: Brian authenticates both servers (one-time)**

Print for Brian; wait for confirmation:

```bash
# Garmin: tokens already exist in ~/.garminconnect. Verify they still work:
uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@e8554bcd761a4494dc12a98461224bb3dcf1fbc5 garmin-mcp-auth

# TrainingPeaks: log into app.trainingpeaks.com in Chrome first, then:
uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@a412a84eb4f9c8f03e108a1f27beb053d83a207d tp-mcp auth --from-browser chrome
uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@a412a84eb4f9c8f03e108a1f27beb053d83a207d tp-mcp auth-status
```

- [ ] **Step 2: Write scripts/spike_mcp.py**

```python
"""One-off spike: call every tool the sync depends on and save fixtures.

Run:  uv run python scripts/spike_mcp.py [--days 14]
Writes tests/fixtures/mcp/<tool>.json. Review each file before committing:
scrub anything you consider private (names, emails). Numbers are fine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tri_analyze.config import get_settings
from tri_analyze.mcp.client import McpToolClient, McpToolError
from tri_analyze.mcp.servers import garmin_spec, trainingpeaks_spec

OUT = Path("tests/fixtures/mcp")


async def record(client: McpToolClient, tool: str, args: dict[str, Any], suffix: str = "") -> Any:
    name = f"{tool}{suffix}"
    try:
        result = await client.call_json(tool, args)
        status = "ok" if result is not None else "empty"
    except McpToolError as exc:
        result = {"__error__": str(exc)}
        status = "ERROR"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps({"args": args, "result": result}, indent=2, default=str))
    size = len(json.dumps(result, default=str))
    print(f"{status:5} {name:40} {size:>8} bytes")
    return result


async def main(days: int) -> None:
    settings = get_settings()
    end = date.today()
    start = end - timedelta(days=days)
    s, e = start.isoformat(), end.isoformat()

    print("== TrainingPeaks")
    async with McpToolClient(trainingpeaks_spec(settings)) as tp:
        print("tools:", len(await tp.list_tool_names()))
        await record(tp, "tp_get_athlete_settings", {})
        workouts = await record(tp, "tp_get_workouts", {"start_date": s, "end_date": e, "workout_filter": "all"})
        first_completed = next((w for w in (workouts or {}).get("workouts", []) if w["type"] == "completed"), None)
        first_planned = next((w for w in (workouts or {}).get("workouts", []) if w["type"] == "planned"), None)
        if first_completed:
            await record(tp, "tp_get_workout", {"workout_id": first_completed["id"]}, "_completed")
        if first_planned:
            await record(tp, "tp_get_workout", {"workout_id": first_planned["id"]}, "_planned")
        await record(tp, "tp_get_fitness", {"start_date": s, "end_date": e})

    print("== Garmin")
    async with McpToolClient(garmin_spec(settings)) as g:
        print("tools:", await g.list_tool_names())
        await record(g, "get_stats", {"date": e})
        await record(g, "get_sleep_summary_range", {"start_date": (end - timedelta(days=3)).isoformat(), "end_date": e})
        await record(g, "get_hrv_data", {"date": e})
        await record(g, "get_training_readiness", {"date": e})
        acts = await record(g, "get_activities_by_date", {"start_date": s, "end_date": e, "page": 0, "page_size": 200})
        first = ((acts or {}).get("activities") or [None])[0]
        if first:
            await record(g, "get_activity", {"activity_id": first["id"]})
            await record(g, "get_activity_splits", {"activity_id": first["id"]})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    asyncio.run(main(ap.parse_args().days))
```

- [ ] **Step 3: Brian runs the spike and reviews fixtures**

Print for Brian:
```bash
uv run python scripts/spike_mcp.py --days 14
ls -la tests/fixtures/mcp/
```
Ask Brian to paste the console summary lines. Then read every fixture file and record, in the task notes, the answers to:
1. `tp_get_workouts[].duration_actual` and `duration_planned`: hours (e.g. `1.5`) or seconds? Expected hours.
2. `tp_get_workout.metrics.distance_actual_km`: km. `elevation_gain`: metres.
3. `tp_get_athlete_settings.settings` keys that hold FTP, threshold HR, threshold pace, zones, weight. Note the exact paths.
4. `get_activities_by_date[].start_time` format. Expected `"YYYY-MM-DD HH:MM:SS"` local.
5. Any tool that returned `ERROR`.

If any of these contradict the parser code in Tasks 6 and 7, adjust those parsers to the observed shape. That is the point of the spike.

- [ ] **Step 4: Add a live smoke test**

Append to `tests/test_mcp_client.py`:
```python
@pytest.mark.live
async def test_live_servers_expose_expected_tools():
    s = Settings()
    async with McpToolClient(trainingpeaks_spec(s)) as tp:
        names = await tp.list_tool_names()
        assert {"tp_get_athlete_settings", "tp_get_workouts", "tp_get_workout", "tp_get_fitness"} <= set(names)
    async with McpToolClient(garmin_spec(s)) as g:
        names = await g.list_tool_names()
        assert {"get_stats", "get_sleep_summary_range", "get_training_readiness", "get_activities_by_date"} <= set(names)
```

Run: `uv run pytest tests/test_mcp_client.py --live -v`
Expected: PASS (takes 10–30 s for uvx to warm both servers).

- [ ] **Step 5: Commit (Brian runs, after scrubbing fixtures)**

```bash
git add scripts/spike_mcp.py tests/fixtures/mcp tests/test_mcp_client.py
git commit -m "chore: MCP spike script and recorded fixtures"
```

---

### Task 5: Row models and repository upserts

**Files:**
- Create: `src/tri_analyze/db/models.py`, `src/tri_analyze/db/repo.py`
- Test: `tests/test_repo.py`

**Interfaces:**
- Produces (`db/models.py`, all `@dataclass(slots=True)`):
  - `AthleteProfileRow(tp_athlete_id: str | None, ftp_watts: int | None, run_threshold_pace_sec_per_km: int | None, swim_css_sec_per_100m: int | None, lthr_bpm: int | None, max_hr_bpm: int | None, hr_zones: Any, power_zones: Any, pace_zones: Any, weight_kg: float | None, raw: dict[str, Any])`
  - `WorkoutRow(tp_workout_id: str, workout_date: date, sport: str, sport_raw: str | None, title: str | None, description: str | None, completed: bool, planned_duration_sec: int | None, planned_distance_m: float | None, planned_tss: float | None, planned_if: float | None, actual_duration_sec: int | None, actual_distance_m: float | None, actual_tss: float | None, actual_if: float | None, normalized_power: int | None, avg_power: int | None, avg_hr: int | None, avg_cadence: float | None, elevation_gain_m: float | None, calories: int | None, feeling: int | None, rpe: int | None, comments: Any, structure: Any, raw: dict[str, Any])` — note: no `garmin_activity_id`/`start_time_local`; those are set by `set_garmin_match`.
  - `DailyMetricsRow(metric_date: date, sleep_seconds=None, sleep_score=None, hrv_overnight_avg=None, resting_hr=None, body_battery_high=None, body_battery_low=None, stress_avg=None, training_readiness=None, garmin_raw=None, ctl=None, atl=None, tsb=None, tss_day=None, tp_raw=None)` all optional with defaults so Garmin and TP can each fill half.
  - `SyncState(source: str, last_synced_date: date, last_run_at: datetime, last_status: str, last_error: str | None)`
- Produces (`db/repo.py`, all take `conn: psycopg.Connection[dict[str, Any]]` first):
  - `upsert_athlete_profile(conn, row) -> None`
  - `upsert_workouts(conn, rows: Iterable[WorkoutRow]) -> int`
  - `upsert_daily_metrics(conn, rows: Iterable[DailyMetricsRow]) -> int` — merges with `coalesce(excluded.x, daily_metrics.x)` so partial rows never null out existing columns.
  - `set_garmin_match(conn, tp_workout_id: str, garmin_activity_id: str, start_time_local: datetime) -> None`
  - `list_workouts_between(conn, start: date, end: date) -> list[dict[str, Any]]`
  - `get_sync_state(conn, source: str) -> SyncState | None`
  - `set_sync_state(conn, source: str, last_synced_date: date, status: str, error: str | None) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/test_repo.py`:
```python
from datetime import date, datetime

import pytest

from tri_analyze.db import repo
from tri_analyze.db.models import AthleteProfileRow, DailyMetricsRow, WorkoutRow

pytestmark = pytest.mark.db


def _workout(**over):
    base = dict(
        tp_workout_id="w1", workout_date=date(2026, 9, 1), sport="bike", sport_raw="Bike",
        title="Endurance", description=None, completed=True,
        planned_duration_sec=5400, planned_distance_m=None, planned_tss=80.0, planned_if=0.7,
        actual_duration_sec=5500, actual_distance_m=45000.0, actual_tss=84.2, actual_if=0.72,
        normalized_power=210, avg_power=200, avg_hr=140, avg_cadence=88.0, elevation_gain_m=300.0,
        calories=1200, feeling=7, rpe=5, comments=[], structure=None, raw={"id": "w1"},
    )
    base.update(over)
    return WorkoutRow(**base)


def test_upsert_workouts_is_idempotent(db):
    assert repo.upsert_workouts(db, [_workout()]) == 1
    assert repo.upsert_workouts(db, [_workout(title="Renamed")]) == 1
    rows = repo.list_workouts_between(db, date(2026, 8, 31), date(2026, 9, 2))
    assert len(rows) == 1
    assert rows[0]["title"] == "Renamed"
    assert rows[0]["completed"] is True


def test_set_garmin_match(db):
    repo.upsert_workouts(db, [_workout()])
    repo.set_garmin_match(db, "w1", "g123", datetime(2026, 9, 1, 6, 30))
    row = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert row["garmin_activity_id"] == "g123"
    assert row["start_time_local"] == datetime(2026, 9, 1, 6, 30)


def test_upsert_workouts_preserves_garmin_match(db):
    repo.upsert_workouts(db, [_workout()])
    repo.set_garmin_match(db, "w1", "g123", datetime(2026, 9, 1, 6, 30))
    repo.upsert_workouts(db, [_workout(title="Again")])
    row = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert row["garmin_activity_id"] == "g123"


def test_daily_metrics_merge_partial_rows(db):
    d = date(2026, 9, 1)
    repo.upsert_daily_metrics(db, [DailyMetricsRow(metric_date=d, sleep_seconds=25000, resting_hr=48)])
    repo.upsert_daily_metrics(db, [DailyMetricsRow(metric_date=d, ctl=60.5, atl=70.1, tsb=-9.6, tss_day=85)])
    row = db.execute("select * from daily_metrics where metric_date=%s", (d,)).fetchone()
    assert row["sleep_seconds"] == 25000
    assert row["resting_hr"] == 48
    assert float(row["ctl"]) == 60.5
    assert float(row["tss_day"]) == 85


def test_athlete_profile_single_row(db):
    repo.upsert_athlete_profile(db, AthleteProfileRow(
        tp_athlete_id="a1", ftp_watts=250, run_threshold_pace_sec_per_km=270, swim_css_sec_per_100m=95,
        lthr_bpm=165, max_hr_bpm=185, hr_zones=[{"z": 1}], power_zones=None, pace_zones=None,
        weight_kg=72.5, raw={"x": 1}))
    repo.upsert_athlete_profile(db, AthleteProfileRow(
        tp_athlete_id="a1", ftp_watts=255, run_threshold_pace_sec_per_km=None, swim_css_sec_per_100m=None,
        lthr_bpm=None, max_hr_bpm=None, hr_zones=None, power_zones=None, pace_zones=None,
        weight_kg=None, raw={"x": 2}))
    rows = db.execute("select * from athlete_profile").fetchall()
    assert len(rows) == 1
    assert rows[0]["ftp_watts"] == 255


def test_sync_state_roundtrip(db):
    assert repo.get_sync_state(db, "garmin") is None
    repo.set_sync_state(db, "garmin", date(2026, 9, 1), "ok", None)
    st = repo.get_sync_state(db, "garmin")
    assert st is not None and st.last_synced_date == date(2026, 9, 1) and st.last_status == "ok"
    repo.set_sync_state(db, "garmin", date(2026, 9, 2), "error", "boom")
    st = repo.get_sync_state(db, "garmin")
    assert st is not None and st.last_error == "boom" and st.last_synced_date == date(2026, 9, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.db.models'`

- [ ] **Step 3: Implement models.py**

```python
"""Row dataclasses shared by sync parsers and the repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class AthleteProfileRow:
    tp_athlete_id: str | None
    ftp_watts: int | None
    run_threshold_pace_sec_per_km: int | None
    swim_css_sec_per_100m: int | None
    lthr_bpm: int | None
    max_hr_bpm: int | None
    hr_zones: Any
    power_zones: Any
    pace_zones: Any
    weight_kg: float | None
    raw: dict[str, Any]


@dataclass(slots=True)
class WorkoutRow:
    tp_workout_id: str
    workout_date: date
    sport: str
    sport_raw: str | None
    title: str | None
    description: str | None
    completed: bool
    planned_duration_sec: int | None
    planned_distance_m: float | None
    planned_tss: float | None
    planned_if: float | None
    actual_duration_sec: int | None
    actual_distance_m: float | None
    actual_tss: float | None
    actual_if: float | None
    normalized_power: int | None
    avg_power: int | None
    avg_hr: int | None
    avg_cadence: float | None
    elevation_gain_m: float | None
    calories: int | None
    feeling: int | None
    rpe: int | None
    comments: Any
    structure: Any
    raw: dict[str, Any]


@dataclass(slots=True)
class DailyMetricsRow:
    metric_date: date
    sleep_seconds: int | None = None
    sleep_score: int | None = None
    hrv_overnight_avg: int | None = None
    resting_hr: int | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    stress_avg: int | None = None
    training_readiness: int | None = None
    garmin_raw: Any = None
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    tss_day: float | None = None
    tp_raw: Any = None


@dataclass(slots=True)
class SyncState:
    source: str
    last_synced_date: date
    last_run_at: datetime
    last_status: str
    last_error: str | None = field(default=None)
```

- [ ] **Step 4: Implement repo.py**

```python
"""SQL access. Every function takes an open connection; callers commit."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from tri_analyze.db.models import AthleteProfileRow, DailyMetricsRow, SyncState, WorkoutRow

Conn = psycopg.Connection[dict[str, Any]]

_JSON_COLS = {"raw", "hr_zones", "power_zones", "pace_zones", "comments", "structure", "garmin_raw", "tp_raw"}


def _params(row: Any) -> dict[str, Any]:
    d = asdict(row)
    for k in _JSON_COLS & d.keys():
        d[k] = Jsonb(d[k]) if d[k] is not None else None
    return d


def upsert_athlete_profile(conn: Conn, row: AthleteProfileRow) -> None:
    conn.execute(
        """
        insert into athlete_profile (id, tp_athlete_id, ftp_watts, run_threshold_pace_sec_per_km,
            swim_css_sec_per_100m, lthr_bpm, max_hr_bpm, hr_zones, power_zones, pace_zones, weight_kg, raw, updated_at)
        values (1, %(tp_athlete_id)s, %(ftp_watts)s, %(run_threshold_pace_sec_per_km)s,
            %(swim_css_sec_per_100m)s, %(lthr_bpm)s, %(max_hr_bpm)s, %(hr_zones)s, %(power_zones)s,
            %(pace_zones)s, %(weight_kg)s, %(raw)s, now())
        on conflict (id) do update set
            tp_athlete_id = excluded.tp_athlete_id,
            ftp_watts = excluded.ftp_watts,
            run_threshold_pace_sec_per_km = excluded.run_threshold_pace_sec_per_km,
            swim_css_sec_per_100m = excluded.swim_css_sec_per_100m,
            lthr_bpm = excluded.lthr_bpm,
            max_hr_bpm = excluded.max_hr_bpm,
            hr_zones = excluded.hr_zones,
            power_zones = excluded.power_zones,
            pace_zones = excluded.pace_zones,
            weight_kg = excluded.weight_kg,
            raw = excluded.raw,
            updated_at = now()
        """,
        _params(row),
    )


_WORKOUT_COLS = [
    "tp_workout_id", "workout_date", "sport", "sport_raw", "title", "description", "completed",
    "planned_duration_sec", "planned_distance_m", "planned_tss", "planned_if",
    "actual_duration_sec", "actual_distance_m", "actual_tss", "actual_if",
    "normalized_power", "avg_power", "avg_hr", "avg_cadence", "elevation_gain_m", "calories",
    "feeling", "rpe", "comments", "structure", "raw",
]


def upsert_workouts(conn: Conn, rows: Iterable[WorkoutRow]) -> int:
    cols = ", ".join(_WORKOUT_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _WORKOUT_COLS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _WORKOUT_COLS if c != "tp_workout_id")
    sql = (
        f"insert into workouts ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (tp_workout_id) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


_DAILY_COLS = [
    "metric_date", "sleep_seconds", "sleep_score", "hrv_overnight_avg", "resting_hr",
    "body_battery_high", "body_battery_low", "stress_avg", "training_readiness", "garmin_raw",
    "ctl", "atl", "tsb", "tss_day", "tp_raw",
]


def upsert_daily_metrics(conn: Conn, rows: Iterable[DailyMetricsRow]) -> int:
    cols = ", ".join(_DAILY_COLS)
    placeholders = ", ".join(f"%({c})s" for c in _DAILY_COLS)
    updates = ", ".join(
        f"{c} = coalesce(excluded.{c}, daily_metrics.{c})" for c in _DAILY_COLS if c != "metric_date"
    )
    sql = (
        f"insert into daily_metrics ({cols}, synced_at) values ({placeholders}, now()) "
        f"on conflict (metric_date) do update set {updates}, synced_at = now()"
    )
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(sql, _params(row))
            n += 1
    return n


def set_garmin_match(conn: Conn, tp_workout_id: str, garmin_activity_id: str, start_time_local: datetime) -> None:
    conn.execute(
        "update workouts set garmin_activity_id = %s, start_time_local = %s where tp_workout_id = %s",
        (garmin_activity_id, start_time_local, tp_workout_id),
    )


def list_workouts_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select * from workouts where workout_date between %s and %s order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def get_sync_state(conn: Conn, source: str) -> SyncState | None:
    row = conn.execute("select * from sync_state where source = %s", (source,)).fetchone()
    return SyncState(**row) if row else None


def set_sync_state(conn: Conn, source: str, last_synced_date: date, status: str, error: str | None) -> None:
    conn.execute(
        """
        insert into sync_state (source, last_synced_date, last_run_at, last_status, last_error)
        values (%s, %s, now(), %s, %s)
        on conflict (source) do update set
            last_synced_date = excluded.last_synced_date,
            last_run_at = now(),
            last_status = excluded.last_status,
            last_error = excluded.last_error
        """,
        (source, last_synced_date, status, error),
    )
```

- [ ] **Step 5: Run tests, lint, types**

Run: `uv run pytest tests/test_repo.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: 6 passed (or skipped with the unreachable message if the container is down; ask Brian to start it).

- [ ] **Step 6: Commit (Brian runs)**

```bash
git add src/tri_analyze/db tests/test_repo.py
git commit -m "feat: row models and idempotent repository upserts"
```

---

### Task 6: Date chunking and sport normalization helpers

**Files:**
- Create: `src/tri_analyze/sync/dates.py`, `src/tri_analyze/sync/sports.py`
- Test: `tests/test_sync_dates.py`, `tests/test_sync_sports.py`

**Interfaces:**
- Produces: `date_chunks(start: date, end: date, max_days: int = 90) -> list[tuple[date, date]]` inclusive ranges each spanning at most `max_days` days (end - start ≤ max_days), covering `[start, end]` with no gaps or overlaps.
- Produces: `normalize_tp_sport(label: str | None) -> str` and `normalize_garmin_sport(type_key: str | None) -> str`, both returning one of `swim | bike | run | brick | strength | race | rest | other`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_dates.py`:
```python
from datetime import date

from tri_analyze.sync.dates import date_chunks


def test_single_chunk_when_within_limit():
    assert date_chunks(date(2026, 1, 1), date(2026, 3, 1), 90) == [(date(2026, 1, 1), date(2026, 3, 1))]


def test_splits_into_contiguous_chunks():
    chunks = date_chunks(date(2026, 1, 1), date(2026, 12, 31), 90)
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 12, 31)
    for (s, e), (ns, _) in zip(chunks, chunks[1:], strict=False):
        assert (e - s).days <= 90
        assert (ns - e).days == 1


def test_same_day():
    assert date_chunks(date(2026, 5, 5), date(2026, 5, 5)) == [(date(2026, 5, 5), date(2026, 5, 5))]


def test_start_after_end_is_empty():
    assert date_chunks(date(2026, 5, 6), date(2026, 5, 5)) == []
```

`tests/test_sync_sports.py`:
```python
import pytest

from tri_analyze.sync.sports import normalize_garmin_sport, normalize_tp_sport


@pytest.mark.parametrize("label,expected", [
    ("Swim", "swim"), ("Bike", "bike"), ("MtnBike", "bike"), ("Run", "run"), ("Brick", "brick"),
    ("Strength", "strength"), ("Race", "race"), ("DayOff", "rest"), ("Crosstrain", "other"),
    ("Walk", "other"), (None, "other"), ("bike", "bike"),
])
def test_tp(label, expected):
    assert normalize_tp_sport(label) == expected


@pytest.mark.parametrize("key,expected", [
    ("running", "run"), ("trail_running", "run"), ("treadmill_running", "run"),
    ("cycling", "bike"), ("road_biking", "bike"), ("indoor_cycling", "bike"), ("virtual_ride", "bike"),
    ("lap_swimming", "swim"), ("open_water_swimming", "swim"),
    ("strength_training", "strength"), ("multi_sport", "brick"), ("triathlon", "brick"),
    ("yoga", "other"), (None, "other"),
])
def test_garmin(key, expected):
    assert normalize_garmin_sport(key) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_dates.py tests/test_sync_sports.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement dates.py and sports.py**

`src/tri_analyze/sync/dates.py`:
```python
"""Date range helpers for APIs with maximum window sizes."""

from datetime import date, timedelta


def date_chunks(start: date, end: date, max_days: int = 90) -> list[tuple[date, date]]:
    """Split [start, end] into inclusive, contiguous chunks with end - start <= max_days."""
    if start > end:
        return []
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks
```

`src/tri_analyze/sync/sports.py`:
```python
"""Map source-specific sport labels onto one small vocabulary."""

SPORTS = ("swim", "bike", "run", "brick", "strength", "race", "rest", "other")

_TP = {
    "swim": "swim",
    "bike": "bike",
    "mtnbike": "bike",
    "run": "run",
    "brick": "brick",
    "strength": "strength",
    "race": "race",
    "dayoff": "rest",
}


def normalize_tp_sport(label: str | None) -> str:
    if not label:
        return "other"
    return _TP.get(label.strip().lower(), "other")


def normalize_garmin_sport(type_key: str | None) -> str:
    if not type_key:
        return "other"
    k = type_key.lower()
    if "swim" in k:
        return "swim"
    if any(t in k for t in ("cycling", "biking", "ride", "bike")):
        return "bike"
    if "running" in k or k == "run":
        return "run"
    if "strength" in k:
        return "strength"
    if k in ("multi_sport", "triathlon", "duathlon"):
        return "brick"
    return "other"
```

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest tests/test_sync_dates.py tests/test_sync_sports.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass.

- [ ] **Step 5: Commit (Brian runs)**

```bash
git add src/tri_analyze/sync/dates.py src/tri_analyze/sync/sports.py tests/test_sync_dates.py tests/test_sync_sports.py
git commit -m "feat: date chunking and sport normalization"
```

---

### Task 7: TrainingPeaks parsers and fetcher

**Files:**
- Create: `src/tri_analyze/sync/trainingpeaks.py`
- Modify: `src/tri_analyze/sync/__init__.py` (add the `ToolCaller` protocol)
- Test: `tests/test_sync_trainingpeaks.py`

**Interfaces:**
- Consumes: `McpToolClient.call_json`, `date_chunks`, `normalize_tp_sport`, `WorkoutRow`, `AthleteProfileRow`, `DailyMetricsRow`.
- Produces:
  - `tri_analyze.sync.ToolCaller` Protocol: `async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None`. Any object with that method (real `McpToolClient` or a test fake) satisfies it.
  - `parse_athlete_settings(payload: dict) -> AthleteProfileRow` — `payload` is the `tp_get_athlete_settings` result (`{"settings": {...}}`).
  - `parse_workout_detail(payload: dict) -> WorkoutRow` — `payload` is the `tp_get_workout` result.
  - `parse_fitness(payload: dict) -> list[DailyMetricsRow]` — from `tp_get_fitness`; fills `ctl, atl, tsb, tss_day, tp_raw` only.
  - `@dataclass TPSnapshot(profile: AthleteProfileRow | None, workouts: list[WorkoutRow], fitness: list[DailyMetricsRow])`
  - `async fetch_trainingpeaks(client: McpToolClient, start: date, end: date, log: Callable[[str], None] = print) -> TPSnapshot`

Shapes (verified from server source; confirm units against the Task 4 fixtures):
- `tp_get_workouts` → `{"workouts": [{"id": str, "date": "YYYY-MM-DD", "title", "type": "planned"|"completed", "sport": "Bike", "duration_planned": hours|None, "duration_actual": hours|None, "distance_planned_km", "distance_actual_km", "tss_planned", "tss_actual", "description"}], "count": int}`
- `tp_get_workout` → `{"id", "date", "title", "sport", "workout_type", "description", "rpe", "feeling", "metrics": {"duration_planned": hours, "duration_actual": hours, "tss_planned", "tss_actual", "if_planned", "if_actual", "distance_planned_km", "distance_actual_km", "avg_power", "normalized_power", "avg_hr", "avg_cadence", "elevation_gain", "calories"}, "completed": bool|None, "structured_workout": ..., "workout_comments": [...]}`
- `tp_get_fitness` → `{"daily_data": [{"date", "tss", "ctl", "atl", "tsb"}], "current": {...}}`
- `tp_get_athlete_settings` → `{"settings": <raw TP settings dict>}`. The raw dict's exact keys are learned from the fixture in Task 4. The parser below reads the paths TP's own update tools use (`_select_group_index` in the server keys zone groups by `workoutTypeId` 1 swim / 2 bike / 3 run and reads `threshold`, `maximumHeartRate`, `restingHeartRate`, `zones[]`). If the fixture shows different top-level key names, adjust `_zone_groups` and `_weight` only.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_trainingpeaks.py`:
```python
import json
from datetime import date
from pathlib import Path

import pytest

from tri_analyze.sync.trainingpeaks import (
    TPSnapshot,
    fetch_trainingpeaks,
    parse_athlete_settings,
    parse_fitness,
    parse_workout_detail,
)

FIX = Path("tests/fixtures/mcp")

DETAIL = {
    "id": "123", "date": "2026-09-01", "title": "Z2 ride", "sport": "Bike", "workout_type": 2,
    "description": "Steady", "rpe": 5, "feeling": 7,
    "metrics": {
        "duration_planned": 1.5, "duration_actual": 1.55, "tss_planned": 80.0, "tss_actual": 84.2,
        "if_planned": 0.7, "if_actual": 0.72, "distance_planned_km": None, "distance_actual_km": 45.1,
        "avg_power": 200.4, "normalized_power": 210.0, "avg_hr": 140, "avg_cadence": 88.2,
        "elevation_gain": 300.0, "calories": 1200,
    },
    "completed": True, "structured_workout": {"steps": []}, "workout_comments": [{"comment": "felt good"}],
}


def test_parse_workout_detail_units():
    row = parse_workout_detail(DETAIL)
    assert row.tp_workout_id == "123"
    assert row.workout_date == date(2026, 9, 1)
    assert row.sport == "bike" and row.sport_raw == "Bike"
    assert row.planned_duration_sec == 5400
    assert row.actual_duration_sec == 5580
    assert row.actual_distance_m == 45100.0
    assert row.planned_distance_m is None
    assert row.avg_power == 200 and row.normalized_power == 210
    assert row.completed is True
    assert row.comments == [{"comment": "felt good"}]
    assert row.raw is DETAIL


def test_parse_workout_detail_planned_only():
    d = {**DETAIL, "completed": None, "metrics": {**DETAIL["metrics"], "duration_actual": None, "tss_actual": None}}
    row = parse_workout_detail(d)
    assert row.completed is False
    assert row.actual_duration_sec is None


def test_parse_fitness():
    rows = parse_fitness({"daily_data": [
        {"date": "2026-09-01", "tss": 85, "ctl": 60.5, "atl": 70.1, "tsb": -9.6},
        {"date": "2026-09-02", "tss": 0, "ctl": 59.1, "atl": 60.0, "tsb": -0.9},
    ]})
    assert [r.metric_date for r in rows] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert rows[0].ctl == 60.5 and rows[0].tss_day == 85
    assert rows[0].sleep_seconds is None


def test_parse_athlete_settings_minimal():
    payload = {"settings": {
        "athleteId": 42,
        "weight": 72.5,
        "powerZones": [{"workoutTypeId": 2, "threshold": 250, "zones": [{"label": "Z1", "minimum": 0, "maximum": 137}]}],
        "heartRateZones": [{"workoutTypeId": 3, "threshold": 165, "maximumHeartRate": 185, "restingHeartRate": 48, "zones": []}],
        "speedZones": [{"workoutTypeId": 3, "threshold": 3.7, "zones": []}, {"workoutTypeId": 1, "threshold": 1.05, "zones": []}],
    }}
    row = parse_athlete_settings(payload)
    assert row.tp_athlete_id == "42"
    assert row.ftp_watts == 250
    assert row.lthr_bpm == 165 and row.max_hr_bpm == 185
    assert row.weight_kg == 72.5
    assert row.run_threshold_pace_sec_per_km == 270      # 1000 m / 3.7 m/s
    assert row.swim_css_sec_per_100m == 95               # 100 m / 1.05 m/s
    assert row.power_zones[0]["workoutTypeId"] == 2
    assert row.raw == payload["settings"]


def test_parse_athlete_settings_empty():
    row = parse_athlete_settings({"settings": {}})
    assert row.ftp_watts is None and row.raw == {}


@pytest.mark.skipif(not (FIX / "tp_get_workout_completed.json").exists(), reason="fixture not recorded")
def test_parse_recorded_completed_workout():
    payload = json.loads((FIX / "tp_get_workout_completed.json").read_text())["result"]
    row = parse_workout_detail(payload)
    assert row.completed is True
    assert row.actual_duration_sec and 60 < row.actual_duration_sec < 12 * 3600


@pytest.mark.skipif(not (FIX / "tp_get_athlete_settings.json").exists(), reason="fixture not recorded")
def test_parse_recorded_settings():
    payload = json.loads((FIX / "tp_get_athlete_settings.json").read_text())["result"]
    row = parse_athlete_settings(payload)
    assert row.tp_athlete_id


class _FakeClient:
    """Answers call_json from a dict keyed by tool name; records calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def call_json(self, tool, args=None):
        self.calls.append((tool, args or {}))
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


async def test_fetch_trainingpeaks_chunks_and_details():
    listed = {
        "workouts": [
            {"id": "1", "date": "2026-01-05", "type": "completed", "sport": "Run"},
            {"id": "2", "date": "2026-02-05", "type": "planned", "sport": "Bike"},
        ]
    }
    client = _FakeClient({
        "tp_get_athlete_settings": {"settings": {"athleteId": 7}},
        "tp_get_workouts": listed,
        "tp_get_workout": lambda a: {**DETAIL, "id": a["workout_id"]},
        "tp_get_fitness": {"daily_data": [{"date": "2026-01-05", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5}]},
    })
    snap = await fetch_trainingpeaks(client, date(2026, 1, 1), date(2026, 6, 30), log=lambda m: None)
    assert isinstance(snap, TPSnapshot)
    assert snap.profile is not None and snap.profile.tp_athlete_id == "7"
    list_calls = [c for c in client.calls if c[0] == "tp_get_workouts"]
    assert len(list_calls) == 2                      # 181 days -> two ≤90-day chunks
    assert all((date.fromisoformat(c[1]["end_date"]) - date.fromisoformat(c[1]["start_date"])).days <= 90 for c in list_calls)
    detail_ids = sorted(c[1]["workout_id"] for c in client.calls if c[0] == "tp_get_workout")
    assert detail_ids == ["1", "2"]                  # de-duplicated across chunks
    assert {w.tp_workout_id for w in snap.workouts} == {"1", "2"}
    fit_calls = [c for c in client.calls if c[0] == "tp_get_fitness"]
    assert len(fit_calls) == 2
    assert snap.fitness[0].ctl == 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_trainingpeaks.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the ToolCaller protocol and trainingpeaks.py**

`src/tri_analyze/sync/__init__.py`:
```python
"""Sync package: fetch from MCP servers, parse, upsert."""

from typing import Any, Protocol


class ToolCaller(Protocol):
    async def call_json(self, tool: str, args: dict[str, Any] | None = None) -> Any | None: ...
```

`src/tri_analyze/sync/trainingpeaks.py`:
```python
"""TrainingPeaks: parse MCP tool payloads into rows, and fetch a date window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tri_analyze.db.models import AthleteProfileRow, DailyMetricsRow, WorkoutRow
from tri_analyze.sync import ToolCaller
from tri_analyze.sync.dates import date_chunks
from tri_analyze.sync.sports import normalize_tp_sport

TP_MAX_RANGE_DAYS = 90

# TP zone groups are keyed by workoutTypeId: 1 swim, 2 bike, 3 run (0 = default).
_SWIM, _BIKE, _RUN = 1, 2, 3


@dataclass
class TPSnapshot:
    profile: AthleteProfileRow | None
    workouts: list[WorkoutRow] = field(default_factory=list)
    fitness: list[DailyMetricsRow] = field(default_factory=list)


# ---------- pure parsers ----------


def _hours_to_sec(h: Any) -> int | None:
    return int(round(float(h) * 3600)) if h is not None else None


def _km_to_m(km: Any) -> float | None:
    return float(km) * 1000 if km is not None else None


def _int(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


def _float(v: Any) -> float | None:
    return float(v) if v is not None else None


def parse_workout_detail(payload: dict[str, Any]) -> WorkoutRow:
    m = payload.get("metrics") or {}
    completed = bool(payload.get("completed")) or m.get("duration_actual") is not None
    return WorkoutRow(
        tp_workout_id=str(payload["id"]),
        workout_date=date.fromisoformat(str(payload["date"])[:10]),
        sport=normalize_tp_sport(payload.get("sport")),
        sport_raw=payload.get("sport"),
        title=payload.get("title"),
        description=payload.get("description"),
        completed=completed,
        planned_duration_sec=_hours_to_sec(m.get("duration_planned")),
        planned_distance_m=_km_to_m(m.get("distance_planned_km")),
        planned_tss=_float(m.get("tss_planned")),
        planned_if=_float(m.get("if_planned")),
        actual_duration_sec=_hours_to_sec(m.get("duration_actual")),
        actual_distance_m=_km_to_m(m.get("distance_actual_km")),
        actual_tss=_float(m.get("tss_actual")),
        actual_if=_float(m.get("if_actual")),
        normalized_power=_int(m.get("normalized_power")),
        avg_power=_int(m.get("avg_power")),
        avg_hr=_int(m.get("avg_hr")),
        avg_cadence=_float(m.get("avg_cadence")),
        elevation_gain_m=_float(m.get("elevation_gain")),
        calories=_int(m.get("calories")),
        feeling=_int(payload.get("feeling")),
        rpe=_int(payload.get("rpe")),
        comments=payload.get("workout_comments"),
        structure=payload.get("structured_workout"),
        raw=payload,
    )


def parse_fitness(payload: dict[str, Any]) -> list[DailyMetricsRow]:
    rows: list[DailyMetricsRow] = []
    for d in payload.get("daily_data") or []:
        if not d.get("date"):
            continue
        rows.append(
            DailyMetricsRow(
                metric_date=date.fromisoformat(d["date"]),
                ctl=_float(d.get("ctl")),
                atl=_float(d.get("atl")),
                tsb=_float(d.get("tsb")),
                tss_day=_float(d.get("tss")),
                tp_raw=d,
            )
        )
    return rows


def _zone_groups(settings: dict[str, Any], key: str) -> list[dict[str, Any]]:
    groups = settings.get(key)
    return [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else []


def _group_for(groups: list[dict[str, Any]], wtid: int) -> dict[str, Any] | None:
    for g in groups:
        if g.get("workoutTypeId") == wtid:
            return g
    return None


def _pace_from_speed(mps: Any, metres: float) -> int | None:
    try:
        v = float(mps)
    except (TypeError, ValueError):
        return None
    return int(round(metres / v)) if v > 0 else None


def parse_athlete_settings(payload: dict[str, Any]) -> AthleteProfileRow:
    s = payload.get("settings") or {}
    power = _zone_groups(s, "powerZones")
    hr = _zone_groups(s, "heartRateZones")
    speed = _zone_groups(s, "speedZones")
    bike_power = _group_for(power, _BIKE) or (power[0] if power else None)
    run_hr = _group_for(hr, _RUN) or _group_for(hr, _BIKE) or (hr[0] if hr else None)
    run_speed = _group_for(speed, _RUN)
    swim_speed = _group_for(speed, _SWIM)
    athlete_id = s.get("athleteId")
    return AthleteProfileRow(
        tp_athlete_id=str(athlete_id) if athlete_id is not None else None,
        ftp_watts=_int(bike_power.get("threshold")) if bike_power else None,
        run_threshold_pace_sec_per_km=_pace_from_speed(run_speed.get("threshold"), 1000) if run_speed else None,
        swim_css_sec_per_100m=_pace_from_speed(swim_speed.get("threshold"), 100) if swim_speed else None,
        lthr_bpm=_int(run_hr.get("threshold")) if run_hr else None,
        max_hr_bpm=_int(run_hr.get("maximumHeartRate")) if run_hr else None,
        hr_zones=hr or None,
        power_zones=power or None,
        pace_zones=speed or None,
        weight_kg=_float(s.get("weight")),
        raw=s,
    )


# ---------- fetch ----------


async def fetch_trainingpeaks(
    client: ToolCaller,
    start: date,
    end: date,
    log: Callable[[str], None] = print,
) -> TPSnapshot:
    settings_payload = await client.call_json("tp_get_athlete_settings", {})
    profile = parse_athlete_settings(settings_payload) if isinstance(settings_payload, dict) else None
    log("trainingpeaks: athlete settings fetched")

    ids: dict[str, None] = {}
    fitness: list[DailyMetricsRow] = []
    for s, e in date_chunks(start, end, TP_MAX_RANGE_DAYS):
        listed = await client.call_json(
            "tp_get_workouts", {"start_date": s.isoformat(), "end_date": e.isoformat(), "workout_filter": "all"}
        )
        for w in (listed or {}).get("workouts", []):
            ids.setdefault(str(w["id"]), None)
        fit = await client.call_json("tp_get_fitness", {"start_date": s.isoformat(), "end_date": e.isoformat()})
        if isinstance(fit, dict):
            fitness.extend(parse_fitness(fit))
        log(f"trainingpeaks: {s} to {e}: {len(ids)} workouts so far, {len(fitness)} fitness days")

    workouts: list[WorkoutRow] = []
    for i, wid in enumerate(ids, 1):
        detail = await client.call_json("tp_get_workout", {"workout_id": wid})
        if isinstance(detail, dict):
            workouts.append(parse_workout_detail(detail))
        if i % 25 == 0:
            log(f"trainingpeaks: {i}/{len(ids)} workout details")
    log(f"trainingpeaks: {len(workouts)} workouts parsed")
    return TPSnapshot(profile=profile, workouts=workouts, fitness=fitness)
```

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest tests/test_sync_trainingpeaks.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass (the two recorded-fixture tests skip until Task 4 fixtures exist; if they exist and fail, fix the parser to the observed shape and note what changed).

- [ ] **Step 5: Commit (Brian runs)**

```bash
git add src/tri_analyze/sync/__init__.py src/tri_analyze/sync/trainingpeaks.py tests/test_sync_trainingpeaks.py
git commit -m "feat: TrainingPeaks parsers and chunked fetcher"
```

---

### Task 8: Garmin parsers and fetcher

**Files:**
- Create: `src/tri_analyze/sync/garmin.py`
- Test: `tests/test_sync_garmin.py`

**Interfaces:**
- Consumes: `tri_analyze.sync.ToolCaller` (Task 7), `date_chunks`, `normalize_garmin_sport`, `DailyMetricsRow`.
- Produces:
  - `@dataclass GarminActivity(id: str, type_key: str | None, sport: str, start_time_local: datetime, duration_sec: float | None, distance_m: float | None, avg_hr: int | None, name: str | None, raw: dict)`
  - `parse_sleep_range(payload: dict) -> dict[date, DailyMetricsRow]` filling `sleep_seconds, sleep_score, hrv_overnight_avg, resting_hr`.
  - `parse_stats(payload: dict) -> DailyMetricsRow` filling `metric_date, resting_hr, body_battery_high, body_battery_low, stress_avg`.
  - `parse_readiness(payload: list | dict) -> tuple[date, int] | None` (date, score) picking the entry with the highest `score` when several exist.
  - `parse_activity_list(payload: dict) -> list[GarminActivity]`
  - `merge_daily(*parts: dict[date, DailyMetricsRow]) -> list[DailyMetricsRow]` — later parts win for non-None fields; `garmin_raw` becomes `{"sleep": ..., "stats": ..., "readiness": ...}`.
  - `@dataclass GarminSnapshot(daily: list[DailyMetricsRow], activities: list[GarminActivity])`
  - `async fetch_garmin(client: ToolCaller, start: date, end: date, log=print) -> GarminSnapshot`

Shapes (from server source):
- `get_sleep_summary_range` → `{"start_date", "end_date", "nights": [{"date": "YYYY-MM-DD", "sleep_seconds", "sleep_score", "avg_overnight_hrv", "resting_heart_rate_bpm", ...}]}`. If the fixture shows a different list key than `nights`, the parser accepts any top-level list of dicts with a `date` key.
- `get_stats` → `{"date", "resting_heart_rate_bpm", "avg_stress_level", "body_battery_highest", "body_battery_lowest", ...}` (None-valued keys removed).
- `get_training_readiness` → list of `{"date", "score", "level", ...}`.
- `get_activities_by_date` → `{"count", "page", "has_more", "next_page"?, "activities": [{"id", "name", "type", "start_time": "YYYY-MM-DD HH:MM:SS", "distance_meters", "duration_seconds", "avg_hr_bpm", ...}]}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_garmin.py`:
```python
from datetime import date, datetime

from tri_analyze.sync.garmin import (
    GarminSnapshot,
    fetch_garmin,
    merge_daily,
    parse_activity_list,
    parse_readiness,
    parse_sleep_range,
    parse_stats,
)


def test_parse_sleep_range():
    out = parse_sleep_range({"nights": [
        {"date": "2026-09-01", "sleep_seconds": 25000, "sleep_score": 81, "avg_overnight_hrv": 52, "resting_heart_rate_bpm": 47},
        {"date": "2026-09-02", "sleep_seconds": 21000},
    ]})
    assert set(out) == {date(2026, 9, 1), date(2026, 9, 2)}
    r = out[date(2026, 9, 1)]
    assert (r.sleep_seconds, r.sleep_score, r.hrv_overnight_avg, r.resting_hr) == (25000, 81, 52, 47)
    assert out[date(2026, 9, 2)].sleep_score is None


def test_parse_sleep_range_tolerates_other_list_key():
    out = parse_sleep_range({"summaries": [{"date": "2026-09-01", "sleep_seconds": 1}]})
    assert out[date(2026, 9, 1)].sleep_seconds == 1


def test_parse_stats():
    r = parse_stats({"date": "2026-09-01", "resting_heart_rate_bpm": 46, "avg_stress_level": 31,
                     "body_battery_highest": 92, "body_battery_lowest": 20})
    assert r.metric_date == date(2026, 9, 1)
    assert (r.resting_hr, r.stress_avg, r.body_battery_high, r.body_battery_low) == (46, 31, 92, 20)


def test_parse_readiness_picks_highest_score():
    assert parse_readiness([{"date": "2026-09-01", "score": 55}, {"date": "2026-09-01", "score": 68}]) == (date(2026, 9, 1), 68)
    assert parse_readiness([]) is None
    assert parse_readiness({"date": "2026-09-01", "score": 70}) == (date(2026, 9, 1), 70)


def test_parse_activity_list():
    acts = parse_activity_list({"activities": [
        {"id": 111, "name": "Morning Ride", "type": "cycling", "start_time": "2026-09-01 06:12:00",
         "distance_meters": 45100.0, "duration_seconds": 5580.2, "avg_hr_bpm": 140},
        {"id": 112, "type": "lap_swimming", "start_time": "2026-09-02 05:30:00"},
    ]})
    assert acts[0].id == "111" and acts[0].sport == "bike"
    assert acts[0].start_time_local == datetime(2026, 9, 1, 6, 12)
    assert acts[0].duration_sec == 5580.2
    assert acts[1].sport == "swim" and acts[1].distance_m is None


def test_merge_daily_later_wins_and_raw_collects():
    from tri_analyze.db.models import DailyMetricsRow
    d = date(2026, 9, 1)
    sleep = {d: DailyMetricsRow(metric_date=d, sleep_seconds=100, resting_hr=50, garmin_raw={"sleep": {"a": 1}})}
    stats = {d: DailyMetricsRow(metric_date=d, resting_hr=48, stress_avg=30, garmin_raw={"stats": {"b": 2}})}
    rows = merge_daily(sleep, stats)
    assert len(rows) == 1
    r = rows[0]
    assert r.sleep_seconds == 100 and r.resting_hr == 48 and r.stress_avg == 30
    assert r.garmin_raw == {"sleep": {"a": 1}, "stats": {"b": 2}}


class _FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    async def call_json(self, tool, args=None):
        self.calls.append((tool, args or {}))
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


async def test_fetch_garmin_paginates_and_walks_days():
    pages = {
        0: {"activities": [{"id": 1, "type": "running", "start_time": "2026-09-01 07:00:00"}], "has_more": True, "next_page": 1},
        1: {"activities": [{"id": 2, "type": "cycling", "start_time": "2026-09-02 07:00:00"}], "has_more": False},
    }
    client = _FakeClient({
        "get_sleep_summary_range": lambda a: {"nights": [{"date": a["start_date"], "sleep_seconds": 1}]},
        "get_stats": lambda a: {"date": a["date"], "resting_heart_rate_bpm": 50},
        "get_training_readiness": lambda a: [{"date": a["date"], "score": 60}],
        "get_activities_by_date": lambda a: pages[a["page"]],
    })
    snap = await fetch_garmin(client, date(2026, 9, 1), date(2026, 9, 3), log=lambda m: None)
    assert isinstance(snap, GarminSnapshot)
    assert [a.id for a in snap.activities] == ["1", "2"]
    assert len([c for c in client.calls if c[0] == "get_stats"]) == 3
    assert len([c for c in client.calls if c[0] == "get_training_readiness"]) == 3
    by_date = {r.metric_date: r for r in snap.daily}
    assert by_date[date(2026, 9, 2)].resting_hr == 50
    assert by_date[date(2026, 9, 2)].training_readiness == 60


async def test_fetch_garmin_tolerates_empty_days():
    client = _FakeClient({
        "get_sleep_summary_range": None,
        "get_stats": None,
        "get_training_readiness": None,
        "get_activities_by_date": {"activities": [], "has_more": False},
    })
    snap = await fetch_garmin(client, date(2026, 9, 1), date(2026, 9, 1), log=lambda m: None)
    assert snap.daily == [] and snap.activities == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_garmin.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement garmin.py**

```python
"""Garmin: parse MCP tool payloads into rows, and fetch a date window."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from typing import Any

from tri_analyze.db.models import DailyMetricsRow
from tri_analyze.sync import ToolCaller
from tri_analyze.sync.dates import date_chunks
from tri_analyze.sync.sports import normalize_garmin_sport

SLEEP_MAX_NIGHTS = 90
ACTIVITY_PAGE_SIZE = 200


@dataclass
class GarminActivity:
    id: str
    type_key: str | None
    sport: str
    start_time_local: datetime
    duration_sec: float | None
    distance_m: float | None
    avg_hr: int | None
    name: str | None
    raw: dict[str, Any]


@dataclass
class GarminSnapshot:
    daily: list[DailyMetricsRow] = field(default_factory=list)
    activities: list[GarminActivity] = field(default_factory=list)


# ---------- pure parsers ----------


def _int(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


def _float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _date(v: Any) -> date:
    return date.fromisoformat(str(v)[:10])


def parse_sleep_range(payload: dict[str, Any]) -> dict[date, DailyMetricsRow]:
    nights: list[dict[str, Any]] = []
    for v in payload.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "date" in v[0]:
            nights = v
            break
    out: dict[date, DailyMetricsRow] = {}
    for n in nights:
        d = _date(n["date"])
        out[d] = DailyMetricsRow(
            metric_date=d,
            sleep_seconds=_int(n.get("sleep_seconds")),
            sleep_score=_int(n.get("sleep_score")),
            hrv_overnight_avg=_int(n.get("avg_overnight_hrv")),
            resting_hr=_int(n.get("resting_heart_rate_bpm")),
            garmin_raw={"sleep": n},
        )
    return out


def parse_stats(payload: dict[str, Any]) -> DailyMetricsRow:
    return DailyMetricsRow(
        metric_date=_date(payload["date"]),
        resting_hr=_int(payload.get("resting_heart_rate_bpm")),
        body_battery_high=_int(payload.get("body_battery_highest")),
        body_battery_low=_int(payload.get("body_battery_lowest")),
        stress_avg=_int(payload.get("avg_stress_level")),
        garmin_raw={"stats": payload},
    )


def parse_readiness(payload: Any) -> tuple[date, int] | None:
    entries = payload if isinstance(payload, list) else [payload] if isinstance(payload, dict) else []
    scored = [e for e in entries if isinstance(e, dict) and e.get("score") is not None and e.get("date")]
    if not scored:
        return None
    best = max(scored, key=lambda e: float(e["score"]))
    return _date(best["date"]), int(round(float(best["score"])))


def parse_activity_list(payload: dict[str, Any]) -> list[GarminActivity]:
    out: list[GarminActivity] = []
    for a in payload.get("activities") or []:
        if a.get("id") is None or not a.get("start_time"):
            continue
        out.append(
            GarminActivity(
                id=str(a["id"]),
                type_key=a.get("type"),
                sport=normalize_garmin_sport(a.get("type")),
                start_time_local=datetime.fromisoformat(str(a["start_time"]).replace(" ", "T")),
                duration_sec=_float(a.get("duration_seconds")),
                distance_m=_float(a.get("distance_meters")),
                avg_hr=_int(a.get("avg_hr_bpm")),
                name=a.get("name"),
                raw=a,
            )
        )
    return out


def merge_daily(*parts: dict[date, DailyMetricsRow]) -> list[DailyMetricsRow]:
    merged: dict[date, DailyMetricsRow] = {}
    for part in parts:
        for d, row in part.items():
            cur = merged.get(d)
            if cur is None:
                merged[d] = DailyMetricsRow(**{f.name: getattr(row, f.name) for f in fields(row)})
                merged[d].garmin_raw = dict(row.garmin_raw or {})
                continue
            for f in fields(row):
                if f.name in ("metric_date", "garmin_raw"):
                    continue
                v = getattr(row, f.name)
                if v is not None:
                    setattr(cur, f.name, v)
            cur.garmin_raw = {**(cur.garmin_raw or {}), **(row.garmin_raw or {})}
    return [merged[d] for d in sorted(merged)]


# ---------- fetch ----------


async def fetch_garmin(
    client: ToolCaller,
    start: date,
    end: date,
    log: Callable[[str], None] = print,
) -> GarminSnapshot:
    sleep: dict[date, DailyMetricsRow] = {}
    for s, e in date_chunks(start, end, SLEEP_MAX_NIGHTS - 1):
        payload = await client.call_json(
            "get_sleep_summary_range", {"start_date": s.isoformat(), "end_date": e.isoformat()}
        )
        if isinstance(payload, dict):
            sleep.update(parse_sleep_range(payload))
    log(f"garmin: {len(sleep)} nights of sleep")

    stats: dict[date, DailyMetricsRow] = {}
    readiness: dict[date, DailyMetricsRow] = {}
    day = start
    n_days = (end - start).days + 1
    while day <= end:
        ds = day.isoformat()
        st = await client.call_json("get_stats", {"date": ds})
        if isinstance(st, dict) and st.get("date"):
            stats[day] = parse_stats(st)
        rd = await client.call_json("get_training_readiness", {"date": ds})
        parsed = parse_readiness(rd)
        if parsed:
            readiness[day] = DailyMetricsRow(metric_date=day, training_readiness=parsed[1], garmin_raw={"readiness": rd})
        if (day - start).days % 10 == 9:
            log(f"garmin: {(day - start).days + 1}/{n_days} days of stats/readiness")
        day += timedelta(days=1)
    daily = merge_daily(sleep, stats, readiness)
    log(f"garmin: {len(daily)} daily rows")

    activities: list[GarminActivity] = []
    page = 0
    while True:
        payload = await client.call_json(
            "get_activities_by_date",
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "page": page, "page_size": ACTIVITY_PAGE_SIZE},
        )
        if not isinstance(payload, dict):
            break
        activities.extend(parse_activity_list(payload))
        if not payload.get("has_more"):
            break
        page = int(payload.get("next_page", page + 1))
    log(f"garmin: {len(activities)} activities")
    return GarminSnapshot(daily=daily, activities=activities)
```

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest tests/test_sync_garmin.py tests/test_sync_trainingpeaks.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass. If the Task 4 fixture for `get_sleep_summary_range` shows a different date key than `date`, adjust `parse_sleep_range` and add a fixture-backed test mirroring Task 7's pattern.

- [ ] **Step 5: Commit (Brian runs)**

```bash
git add src/tri_analyze/sync/garmin.py tests/test_sync_garmin.py
git commit -m "feat: Garmin parsers and day-walking fetcher"
```

---

### Task 9: Match Garmin activities to TrainingPeaks workouts

**Files:**
- Create: `src/tri_analyze/sync/match.py`
- Test: `tests/test_sync_match.py`

**Interfaces:**
- Consumes: `GarminActivity`, workout dicts from `repo.list_workouts_between` (keys `tp_workout_id, workout_date, sport, actual_duration_sec, completed, garmin_activity_id`).
- Produces: `match_activities(workouts: list[dict[str, Any]], activities: list[GarminActivity], tolerance_sec: int = 120) -> list[tuple[str, GarminActivity]]` — pairs `(tp_workout_id, activity)`. Rules: same `workout_date` as `activity.start_time_local.date()`, same `sport` (or workout sport `brick` matching any Garmin sport), workout must be `completed`, pick the unmatched workout whose `actual_duration_sec` is closest to `activity.duration_sec` and within `tolerance_sec`; if the workout has no duration, allow the match only when it is the sole candidate that day. Each workout and activity matched at most once. Workouts that already have a `garmin_activity_id` are skipped.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_match.py`:
```python
from datetime import date, datetime

from tri_analyze.sync.garmin import GarminActivity
from tri_analyze.sync.match import match_activities


def _act(id, sport, day, dur, hour=7):
    return GarminActivity(id=id, type_key=None, sport=sport, start_time_local=datetime(2026, 9, day, hour),
                          duration_sec=dur, distance_m=None, avg_hr=None, name=None, raw={})


def _wo(id, sport, day, dur, completed=True, gid=None):
    return {"tp_workout_id": id, "workout_date": date(2026, 9, day), "sport": sport,
            "actual_duration_sec": dur, "completed": completed, "garmin_activity_id": gid}


def test_matches_by_date_sport_and_closest_duration():
    workouts = [_wo("w1", "bike", 1, 5400), _wo("w2", "bike", 1, 3600), _wo("w3", "run", 1, 3600)]
    acts = [_act("g1", "bike", 1, 3650.0), _act("g2", "run", 1, 3590.0), _act("g3", "bike", 1, 5390.0)]
    pairs = dict(match_activities(workouts, acts))
    assert pairs == {"w2": acts[0], "w3": acts[1], "w1": acts[2]}


def test_respects_tolerance():
    assert match_activities([_wo("w1", "bike", 1, 5400)], [_act("g1", "bike", 1, 3000.0)]) == []


def test_skips_planned_and_already_matched():
    workouts = [_wo("w1", "bike", 1, 5400, completed=False), _wo("w2", "bike", 1, 5400, gid="old")]
    assert match_activities(workouts, [_act("g1", "bike", 1, 5400.0)]) == []


def test_no_duration_matches_only_sole_candidate():
    a = _act("g1", "run", 2, 2400.0)
    assert match_activities([_wo("w1", "run", 2, None)], [a]) == [("w1", a)]
    two = [_wo("w1", "run", 2, None), _wo("w2", "run", 2, None)]
    assert match_activities(two, [a]) == []


def test_brick_matches_any_sport_once():
    a1, a2 = _act("g1", "bike", 3, 3600.0), _act("g2", "run", 3, 1200.0, hour=8)
    pairs = match_activities([_wo("w1", "brick", 3, 4800)], [a1, a2], tolerance_sec=100000)
    assert len(pairs) == 1 and pairs[0][0] == "w1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_match.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement match.py**

```python
"""Pair Garmin activities with TrainingPeaks workouts on the same day."""

from __future__ import annotations

from typing import Any

from tri_analyze.sync.garmin import GarminActivity


def _sport_ok(workout_sport: str, activity_sport: str) -> bool:
    return workout_sport == "brick" or workout_sport == activity_sport


def match_activities(
    workouts: list[dict[str, Any]],
    activities: list[GarminActivity],
    tolerance_sec: int = 120,
) -> list[tuple[str, GarminActivity]]:
    candidates = [w for w in workouts if w.get("completed") and not w.get("garmin_activity_id")]
    used_workouts: set[str] = set()
    pairs: list[tuple[str, GarminActivity]] = []

    for act in sorted(activities, key=lambda a: a.start_time_local):
        day = act.start_time_local.date()
        same_day = [
            w for w in candidates
            if w["workout_date"] == day and w["tp_workout_id"] not in used_workouts and _sport_ok(w["sport"], act.sport)
        ]
        if not same_day:
            continue
        with_dur = [w for w in same_day if w.get("actual_duration_sec") is not None and act.duration_sec is not None]
        chosen: dict[str, Any] | None = None
        if with_dur:
            best = min(with_dur, key=lambda w: abs(float(w["actual_duration_sec"]) - float(act.duration_sec or 0)))
            if abs(float(best["actual_duration_sec"]) - float(act.duration_sec or 0)) <= tolerance_sec:
                chosen = best
        elif len(same_day) == 1:
            chosen = same_day[0]
        if chosen is not None:
            used_workouts.add(chosen["tp_workout_id"])
            pairs.append((chosen["tp_workout_id"], act))
    return pairs
```

- [ ] **Step 4: Run tests, lint, types**

Run: `uv run pytest tests/test_sync_match.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: 5 passed, clean.

- [ ] **Step 5: Commit (Brian runs)**

```bash
git add src/tri_analyze/sync/match.py tests/test_sync_match.py
git commit -m "feat: match Garmin activities to TP workouts"
```

---

### Task 10: Sync runner and CLI

**Files:**
- Create: `src/tri_analyze/sync/runner.py`, `src/tri_analyze/cli.py`
- Test: `tests/test_sync_runner.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass SourceResult(source: str, status: str, rows: int, error: str | None)`
  - `@dataclass SyncReport(results: list[SourceResult])` with property `ok: bool`.
  - `resolve_window(state: SyncState | None, since: date | None, full: bool, today: date, first_run_days: int, overlap_days: int = 3) -> tuple[date, date]` pure.
  - `async run_sync(settings: Settings, *, since: date | None = None, sources: tuple[str, ...] = ("trainingpeaks", "garmin"), full: bool = False, log=print, open_tp=None, open_garmin=None) -> SyncReport`. `open_tp`/`open_garmin` are factories returning an async context manager yielding a `ToolCaller`; defaults build `McpToolClient` from the specs. Tests inject fakes.
  - CLI: `tri-analyze sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]`.

Constants: `TP_FIRST_RUN_DAYS = 365`, `GARMIN_FIRST_RUN_DAYS = 60`, `OVERLAP_DAYS = 3`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync_runner.py`:
```python
from contextlib import asynccontextmanager
from datetime import date, datetime

import pytest

from tri_analyze.config import Settings
from tri_analyze.db import repo
from tri_analyze.db.models import SyncState
from tri_analyze.sync.runner import GARMIN_FIRST_RUN_DAYS, TP_FIRST_RUN_DAYS, resolve_window, run_sync

TODAY = date(2026, 9, 6)


def test_resolve_window_first_run():
    assert resolve_window(None, None, False, TODAY, TP_FIRST_RUN_DAYS) == (date(2025, 9, 6), TODAY)
    assert resolve_window(None, None, False, TODAY, GARMIN_FIRST_RUN_DAYS) == (date(2026, 7, 8), TODAY)


def test_resolve_window_incremental_with_overlap():
    st = SyncState("garmin", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    assert resolve_window(st, None, False, TODAY, 60) == (date(2026, 8, 29), TODAY)


def test_resolve_window_since_and_full_override():
    st = SyncState("garmin", date(2026, 9, 1), datetime(2026, 9, 1), "ok", None)
    assert resolve_window(st, date(2026, 6, 1), False, TODAY, 60) == (date(2026, 6, 1), TODAY)
    assert resolve_window(st, None, True, TODAY, 60) == (date(2026, 7, 8), TODAY)


class _Fake:
    def __init__(self, answers, fail=False):
        self.answers = answers
        self.fail = fail

    async def call_json(self, tool, args=None):
        if self.fail:
            raise RuntimeError("server down")
        a = self.answers[tool]
        return a(args or {}) if callable(a) else a


def _tp_answers():
    detail = {"id": "w1", "date": "2026-09-01", "sport": "Bike", "metrics": {"duration_actual": 1.0, "tss_actual": 50}, "completed": True}
    return {
        "tp_get_athlete_settings": {"settings": {"athleteId": 9}},
        "tp_get_workouts": {"workouts": [{"id": "w1", "date": "2026-09-01", "type": "completed", "sport": "Bike"}]},
        "tp_get_workout": detail,
        "tp_get_fitness": {"daily_data": [{"date": "2026-09-01", "tss": 50, "ctl": 40, "atl": 45, "tsb": -5}]},
    }


def _garmin_answers():
    return {
        "get_sleep_summary_range": {"nights": [{"date": "2026-09-01", "sleep_seconds": 27000}]},
        "get_stats": lambda a: {"date": a["date"], "resting_heart_rate_bpm": 49},
        "get_training_readiness": lambda a: [{"date": a["date"], "score": 71}],
        "get_activities_by_date": {"activities": [{"id": 555, "type": "cycling", "start_time": "2026-09-01 06:00:00", "duration_seconds": 3610.0}], "has_more": False},
    }


def _factory(fake):
    @asynccontextmanager
    async def _open():
        yield fake
    return _open


@pytest.mark.db
async def test_run_sync_end_to_end(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    # keep everything in the test transaction: make the runner use our connection
    monkeypatch.setattr("tri_analyze.sync.runner.connect", lambda url: _NoClose(db))

    report = await run_sync(
        settings, since=date(2026, 8, 30), log=lambda m: None,
        open_tp=_factory(_Fake(_tp_answers())), open_garmin=_factory(_Fake(_garmin_answers())),
    )
    assert report.ok, report
    statuses = {r.source: r.status for r in report.results}
    assert statuses == {"trainingpeaks": "ok", "garmin": "ok"}

    w = repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))[0]
    assert w["garmin_activity_id"] == "555"
    assert w["start_time_local"] == datetime(2026, 9, 1, 6, 0)
    dm = db.execute("select * from daily_metrics where metric_date = %s", (date(2026, 9, 1),)).fetchone()
    assert dm["sleep_seconds"] == 27000 and dm["training_readiness"] == 71 and float(dm["ctl"]) == 40
    assert repo.get_sync_state(db, "garmin").last_status == "ok"
    assert db.execute("select ftp_watts, tp_athlete_id from athlete_profile").fetchone()["tp_athlete_id"] == "9"


@pytest.mark.db
async def test_run_sync_isolates_source_failure(db, monkeypatch):
    settings = Settings(_env_file=None)
    settings.database_url = settings.test_database_url
    monkeypatch.setattr("tri_analyze.sync.runner.connect", lambda url: _NoClose(db))

    report = await run_sync(
        settings, since=date(2026, 8, 30), log=lambda m: None,
        open_tp=_factory(_Fake(_tp_answers())), open_garmin=_factory(_Fake({}, fail=True)),
    )
    assert not report.ok
    statuses = {r.source: r.status for r in report.results}
    assert statuses == {"trainingpeaks": "ok", "garmin": "error"}
    assert repo.list_workouts_between(db, date(2026, 9, 1), date(2026, 9, 1))
    st = repo.get_sync_state(db, "garmin")
    assert st.last_status == "error" and "server down" in (st.last_error or "")


class _NoClose:
    """Wraps the test connection so runner's `with connect(...)` and commit() don't end the test transaction."""

    def __init__(self, conn):
        self._c = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        pass

    def rollback(self):
        pass

    def __getattr__(self, name):
        return getattr(self._c, name)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tri_analyze.sync.runner'`

- [ ] **Step 3: Implement runner.py**

```python
"""Sequence the sources, isolate failures, record watermarks."""

from __future__ import annotations

import traceback
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from tri_analyze.config import Settings
from tri_analyze.db import repo
from tri_analyze.db.connection import connect
from tri_analyze.db.models import SyncState
from tri_analyze.mcp.client import McpToolClient
from tri_analyze.mcp.servers import garmin_spec, trainingpeaks_spec
from tri_analyze.sync import ToolCaller
from tri_analyze.sync.garmin import fetch_garmin
from tri_analyze.sync.match import match_activities
from tri_analyze.sync.trainingpeaks import fetch_trainingpeaks

TP_FIRST_RUN_DAYS = 365
GARMIN_FIRST_RUN_DAYS = 60
OVERLAP_DAYS = 3

Opener = Callable[[], AbstractAsyncContextManager[ToolCaller]]


@dataclass
class SourceResult:
    source: str
    status: str
    rows: int = 0
    error: str | None = None


@dataclass
class SyncReport:
    results: list[SourceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.status == "ok" for r in self.results)


def resolve_window(
    state: SyncState | None,
    since: date | None,
    full: bool,
    today: date,
    first_run_days: int,
    overlap_days: int = OVERLAP_DAYS,
) -> tuple[date, date]:
    if since is not None:
        return since, today
    if full or state is None:
        return today - timedelta(days=first_run_days), today
    return state.last_synced_date - timedelta(days=overlap_days), today


def _default_opener(spec_fn: Callable[[Settings], Any], settings: Settings) -> Opener:
    @asynccontextmanager
    async def _open() -> AsyncIterator[ToolCaller]:
        async with McpToolClient(spec_fn(settings)) as client:
            yield client

    return _open


async def _sync_trainingpeaks(conn: Any, opener: Opener, start: date, end: date, log: Callable[[str], None]) -> int:
    async with opener() as client:
        snap = await fetch_trainingpeaks(client, start, end, log=log)
    rows = 0
    if snap.profile is not None:
        repo.upsert_athlete_profile(conn, snap.profile)
        rows += 1
    rows += repo.upsert_workouts(conn, snap.workouts)
    rows += repo.upsert_daily_metrics(conn, snap.fitness)
    return rows


async def _sync_garmin(conn: Any, opener: Opener, start: date, end: date, log: Callable[[str], None]) -> int:
    async with opener() as client:
        snap = await fetch_garmin(client, start, end, log=log)
    rows = repo.upsert_daily_metrics(conn, snap.daily)
    workouts = repo.list_workouts_between(conn, start, end)
    pairs = match_activities(workouts, snap.activities)
    for tp_id, act in pairs:
        repo.set_garmin_match(conn, tp_id, act.id, act.start_time_local)
    log(f"garmin: matched {len(pairs)} of {len(snap.activities)} activities to TP workouts")
    return rows + len(pairs)


async def run_sync(
    settings: Settings,
    *,
    since: date | None = None,
    sources: tuple[str, ...] = ("trainingpeaks", "garmin"),
    full: bool = False,
    log: Callable[[str], None] = print,
    open_tp: Opener | None = None,
    open_garmin: Opener | None = None,
) -> SyncReport:
    today = date.today()
    open_tp = open_tp or _default_opener(trainingpeaks_spec, settings)
    open_garmin = open_garmin or _default_opener(garmin_spec, settings)
    plan: list[tuple[str, int, Opener, Any]] = [
        ("trainingpeaks", TP_FIRST_RUN_DAYS, open_tp, _sync_trainingpeaks),
        ("garmin", GARMIN_FIRST_RUN_DAYS, open_garmin, _sync_garmin),
    ]
    report = SyncReport()
    with connect(settings.database_url) as conn:
        for source, first_run_days, opener, fn in plan:
            if source not in sources:
                continue
            state = repo.get_sync_state(conn, source)
            start, end = resolve_window(state, since, full, today, first_run_days)
            log(f"== {source}: {start} to {end}")
            try:
                rows = await fn(conn, opener, start, end, log)
                repo.set_sync_state(conn, source, end, "ok", None)
                conn.commit()
                report.results.append(SourceResult(source, "ok", rows))
                log(f"== {source}: ok, {rows} rows")
            except Exception as exc:  # per-source isolation is the point
                conn.rollback()
                err = f"{type(exc).__name__}: {exc}"
                log(f"== {source}: ERROR {err}\n{traceback.format_exc()}")
                last = state.last_synced_date if state else start
                repo.set_sync_state(conn, source, last, "error", err[:2000])
                conn.commit()
                report.results.append(SourceResult(source, "error", 0, err))
    return report
```

- [ ] **Step 4: Implement cli.py**

```python
"""Command-line entry points."""

from __future__ import annotations

import asyncio
from datetime import date

import typer
from rich.console import Console

from tri_analyze.config import get_settings
from tri_analyze.sync.runner import run_sync

app = typer.Typer(help="Triathlon training analysis agent", no_args_is_help=True)
console = Console()


@app.command()
def sync(
    since: str | None = typer.Option(None, help="Start date YYYY-MM-DD (overrides watermark)"),
    source: str = typer.Option("all", help="trainingpeaks | garmin | all"),
    full: bool = typer.Option(False, help="Ignore watermark; use each source's first-run window"),
) -> None:
    """Pull TrainingPeaks and Garmin data into Postgres."""
    sources = ("trainingpeaks", "garmin") if source == "all" else (source,)
    since_date = date.fromisoformat(since) if since else None
    report = asyncio.run(
        run_sync(
            get_settings(),
            since=since_date,
            sources=sources,
            full=full,
            log=lambda m: console.print(m, markup=False, highlight=False),
        )
    )
    for r in report.results:
        style = "green" if r.status == "ok" else "red"
        console.print(f"[{style}]{r.source}: {r.status} ({r.rows} rows){' ' + r.error if r.error else ''}[/{style}]")
    raise typer.Exit(code=0 if report.ok else 1)


if __name__ == "__main__":
    app()
```

- [ ] **Step 5: Run tests, lint, types**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: all pass. mypy may need `# type: ignore[arg-type]` on the `plan` tuple's callable slot; prefer typing `fn` as `Callable[[Any, Opener, date, date, Callable[[str], None]], Awaitable[int]]` instead of ignoring.

- [ ] **Step 6: First real sync (Brian runs, assistant watches output)**

```bash
uv run tri-analyze sync --since 2026-08-01
```
Expected: both sources print progress and end `ok`. Then verify:
```bash
docker compose exec db psql -U tri_analyze -d tri_analyze -c "select sport, count(*), sum(actual_tss)::int as tss from workouts group by 1 order by 2 desc;"
docker compose exec db psql -U tri_analyze -d tri_analyze -c "select metric_date, sleep_score, hrv_overnight_avg, resting_hr, training_readiness, ctl, atl, tsb from daily_metrics order by 1 desc limit 7;"
docker compose exec db psql -U tri_analyze -d tri_analyze -c "select count(*) filter (where garmin_activity_id is not null) as matched, count(*) filter (where completed) as completed from workouts;"
```
If the matched count is far below completed, inspect a few unmatched rows and tune `match_activities` (tolerance or sport mapping) with a new unit test capturing the case.

Then run the incremental path and confirm it is fast and idempotent:
```bash
uv run tri-analyze sync
```

- [ ] **Step 7: Commit (Brian runs)**

```bash
git add src/tri_analyze/sync/runner.py src/tri_analyze/cli.py tests/test_sync_runner.py
git commit -m "feat: sync runner with watermarks and tri-analyze sync CLI"
```

---

### Task 11: Full history backfill and README

**Files:**
- Create: `README.md`
- Modify: `docs/superpowers/specs/2026-09-06-tri-analyze-design.md` (add `tss_day` to §4.2 schema)

- [ ] **Step 1: Brian runs the full backfill**

```bash
uv run tri-analyze sync --full
```
Expected: TP walks 365 days (five 90-day chunks, then one detail call per workout; a few minutes). Garmin walks 60 days (about 120 calls; a few minutes). Both `ok`. If Garmin rate-limits (`Garmin rate limit hit`), wait 10 minutes and rerun `uv run tri-analyze sync --source garmin`; the watermark resumes with overlap.

- [ ] **Step 2: Write README.md**

```markdown
# tri_analyze

Triathlon training analysis agent (LangChain) over Garmin Connect and TrainingPeaks data.

## Setup

1. `uv sync`
2. `docker compose up -d` then apply `migrations/*.sql` to `tri_analyze` and `tri_analyze_test` (see plan Task 2).
3. `cp .env.example .env` and fill in keys.
4. Authenticate the MCP servers once:
   - Garmin: `uvx --python 3.12 --from git+https://github.com/Taxuspt/garmin_mcp@<ref> garmin-mcp-auth`
   - TrainingPeaks: `uvx --from git+https://github.com/JamsusMaximus/trainingpeaks-mcp@<ref> tp-mcp auth --from-browser chrome`
   (`<ref>` values are in `.env.example`.)

## Commands

- `uv run tri-analyze sync [--since YYYY-MM-DD] [--source trainingpeaks|garmin|all] [--full]`
- `uv run pytest` (add `--live` to hit real servers; `db`-marked tests skip when Postgres is down)

## Layout

See `docs/superpowers/specs/2026-09-06-tri-analyze-design.md`.
```

- [ ] **Step 3: Add `tss_day` to spec §4.2 and mirror docs to the vault**

Insert `  tss_day           numeric,` after the `tsb` line in the spec's `daily_metrics` block, then:
```bash
mkdir -p /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/tri-analyze-agent/docs/superpowers/{specs,plans}
cp README.md /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/tri-analyze-agent/readme.md
cp docs/superpowers/specs/*.md /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/tri-analyze-agent/docs/superpowers/specs/
cp docs/superpowers/plans/*.md /Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/tri-analyze-agent/docs/superpowers/plans/
```

- [ ] **Step 4: Commit (Brian runs)**

```bash
git add README.md docs
git commit -m "docs: README and spec schema update"
```

---

## What the next plan covers

Milestones 3 and 4 from the spec: `create_agent` over `ChatAnthropic("claude-opus-5")` with `query_training_db`, the athlete-context system prompt, the streaming REPL, then `langchain-mcp-adapters` live tools with an allow-list. It will be written once this plan is executed, because the SQL tool's description embeds the real schema and example rows, and the live-tool allow-list depends on which Garmin detail tools proved useful in the recorded fixtures.
