# Repo hygiene: CI, migrations, a read-only SQL role, TypeScript strict, MCP environment

**Date:** 2026-09-24
**Status:** Draft
**Purpose:** Make the checks that gate every merge run without anyone remembering them, make schema changes recorded and repeatable, take the SQL tool off the owner role, turn on TypeScript strict mode, and stop handing every secret in the environment to the two MCP subprocesses. Fifth of the five specs from `docs/notes/2026-09-24-codebase-review.md`; independent of the other four and safe to execute in any order relative to them.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| CI host | GitHub Actions on `paradigmbrian/triathlon-agent`, one workflow, Postgres 16 as a service container (chosen 2026-09-24). | The remote is GitHub; the db-marked tests only run against a reachable Postgres, and a CI run without one would silently skip about 40 test modules. |
| Migration tracking | A `tri migrate` command in tri-core with a `schema_migrations` table; no new dependency (chosen 2026-09-24). | Five SQL files, one athlete, two databases. dbmate would add a binary for a loop that fits in 60 lines. |
| SQL tool role | A `tri_reader` role with SELECT only; the tool connects with `TRI_READONLY_DATABASE_URL`, derived from `DATABASE_URL` when unset (chosen 2026-09-24). | The lexical check plus `BEGIN READ ONLY` holds for writes, but the owner role can still call `pg_terminate_backend` on the checkpointer's connection. A role is a boundary; a regex is not. |
| Lexical check | Kept as a second layer. | It rejects multi-statement input before it reaches the server and gives a better error than the role's permission denied. |
| TypeScript | `"strict": true` in `tsconfig.app.json` and `tsconfig.node.json`, fixed until `tsc -b` is clean. | Every `| null` in the generated `types.ts` is unenforced today. |
| MCP environment | The subprocess gets `PATH`, `HOME`, `TMPDIR`, `LANG`, `LC_ALL` (when set) plus `ServerSpec.env`, nothing else. | Garmin needs `HOME` for `~/.garminconnect`, both need `PATH` for `uvx`; nothing needs `ANTHROPIC_API_KEY`, `DATABASE_URL` or the LangSmith key. |
| `scripts/setup_checkpointer.py` | Folded into `tri migrate` as the last step, keyed on the checkpointer's own tables. | A third DDL path beside `migrations/` and the README loop is the kind of thing this spec exists to remove. |

## 2. Feasibility, verified 2026-09-24

- No `.github/` directory, no Makefile, no shell scripts. The README's "Test and lint" block (`README.md:131-139`) is the only statement of the check set: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, plus `npm --prefix web run lint|test|test:e2e` (`README.md:89-92`).
- `tri` (`packages/tri-core/src/tri_core/cli.py`) has one command, `sync`. `migrations/*.sql` are applied by the README's psql loop to both databases; no tracking table exists; each file uses `create table if not exists`. `scripts/setup_checkpointer.py <url>` creates the LangGraph checkpointer and Store tables separately (README step 6).
- The `db` fixture (`packages/tri-core/src/tri_core/testing/fixtures.py:14-25`) connects to `Settings().test_database_url` and skips on `psycopg.OperationalError`; it assumes migrations are applied. Package conftests probe single tables with `to_regclass` to skip when a later migration is missing (`tri-wellness/tests/conftest.py:18-23`, `tri-coach/tests/conftest.py:19-23,36-40`). `pytest.mark.db` is metadata only.
- `docker-compose.yml` creates one role, `tri_analyze`, owner of `tri_analyze`; `tri_analyze_test` is created by hand.
- `make_query_tool(url)` (`packages/tri-core/src/tri_core/db/sql_tool.py:131-148`) is called at eight production sites, every one with `Settings.database_url` or a `deps.db_url` that traces back to it. `run_readonly_query` (`:99-128`) opens a fresh connection per query with `conn.read_only = True` and a `set local statement_timeout`.
- `Settings` (`packages/tri-core/src/tri_core/config.py:11-16`) has `database_url` and `test_database_url`; no read-only URL.
- `mcp/client.py:54-64` and `mcp/live_tools.py:30-36` build the child environment as `{**os.environ, **spec.env}`. `mcp/README.md:37-39` says why: `uvx` needs `PATH` and `HOME`. `ServerSpec.env` (`mcp/servers.py:30-65`) sets `GARMIN_ENABLED_TOOLS`, `GARMIN_MCP_CALL_TIMEOUT`, optional `GARMIN_EMAIL`/`GARMIN_PASSWORD`, optional `TP_AUTH_COOKIE`. TrainingPeaks reads its cookie from the macOS Keychain when the env var is unset.
- `web/tsconfig.app.json` and `web/tsconfig.node.json` set no `strict`; the app project includes `src` and `tests`. `npm run build` is `tsc -b && vite build`. Vitest is configured in `vite.config.ts` (12 files under `web/tests`); Playwright's `smoke.spec.ts` starts `npm run build && npm run preview` and needs a Chromium install. `web/package.json` has no `engines` field; `web/package-lock.json` exists.
- mypy `files` covers `src` only; tests are not type-checked. Ruff has no `[tool.ruff.format]` block (defaults apply).

## 3. Layout

```
.github/workflows/ci.yml                       NEW
migrations/006_schema_migrations.sql           NEW: the tracking table
migrations/007_reader_role.sql                 NEW: tri_reader role and grants
packages/tri-core/src/tri_core/db/migrate.py   NEW: apply_migrations, pending, MigrationError
packages/tri-core/src/tri_core/cli.py          adds `tri migrate [--test] [--dry-run]`
packages/tri-core/src/tri_core/config.py       adds tri_readonly_database_url
packages/tri-core/src/tri_core/db/sql_tool.py  make_query_tool takes the read-only URL (callers)
packages/tri-core/src/tri_core/mcp/env.py      NEW: child_env(spec)
packages/tri-core/src/tri_core/mcp/{client.py,live_tools.py}   use child_env
packages/tri-core/tests/{test_migrate.py,test_mcp_env.py}      NEW; test_sql_tool.py gains role cases
scripts/setup_checkpointer.py                  deleted (its DDL moves to migrate.py's last step)
web/tsconfig.app.json, web/tsconfig.node.json  "strict": true
web/src/**                                     whatever tsc -b reports
README.md, packages/tri-core/src/tri_core/db/README.md, .env.example   updated
```

## 4. Interfaces

### 4.1 `tri_core.db.migrate`

```python
@dataclass(frozen=True)
class Migration:
    version: int          # leading integer of the filename, 1..
    name: str             # filename without extension
    path: Path
    sha256: str           # of the file's bytes

class MigrationError(RuntimeError): ...

def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]: ...
def applied(conn: Conn) -> dict[int, str]: ...            # version -> sha256, {} when the table is missing
def pending(conn: Conn, migrations: list[Migration]) -> list[Migration]: ...
def apply_migrations(url: str, *, dry_run: bool = False, log: Callable[[str], None] = print) -> list[Migration]: ...
```

`apply_migrations` opens one connection, creates `schema_migrations` if missing (the DDL is inline, so migration 006 is a no-op on a database that ran `tri migrate` first and a record on one migrated by hand), then for each pending migration in version order runs the file inside one transaction and inserts `(version, name, sha256, applied_at)`. An applied version whose stored sha differs from the file raises `MigrationError` naming the file: edited history is refused, not silently re-run. After the SQL files it ensures the LangGraph checkpointer and Store tables the way `scripts/setup_checkpointer.py` does today (`PostgresSaver.setup()` and `PostgresStore.setup()`, both idempotent). `dry_run` prints what would run and touches nothing.

### 4.2 `tri migrate`

```
tri migrate [--test] [--dry-run]
```

Targets `settings.database_url`, or `settings.test_database_url` with `--test`. Prints one line per migration applied, `up to date` when none, exits 1 on `MigrationError` with the message. Running it twice is a no-op.

### 4.3 Settings

| Env var | Field | Default |
|---|---|---|
| `TRI_READONLY_DATABASE_URL` | `tri_readonly_database_url: str \| None = None` | resolved by `readonly_url(settings)`: the field when set, else `database_url` with the user and password replaced by `tri_reader` / `tri_reader` |

`readonly_url` lives in `tri_core.config` and is what every `make_query_tool` caller passes. The password default matches migration 007; the athlete overrides both together to change it.

### 4.4 SQL tool

`make_query_tool(url, extra_doc="")` is unchanged in signature; every call site passes `readonly_url(settings)` (CLIs) or a new `deps.readonly_db_url` (planning, nutrition, coach deps gain the field, set from `readonly_url` in their `make_deps`). `run_readonly_query` keeps `conn.read_only = True`, the timeout and `validate_select`. A permission error from the role (`psycopg.errors.InsufficientPrivilege`) is returned as `{"error": "rejected: not permitted for the read-only role"}` like the other rejections.

### 4.5 `tri_core.mcp.env.child_env`

```python
PASSTHROUGH = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")

def child_env(spec: ServerSpec) -> dict[str, str]:
    """The subprocess environment: the passthrough keys that are set, then spec.env on top."""
```

`McpToolClient.__aenter__` and `live_tools._connection` call it instead of building the dict inline.

### 4.6 CI workflow

`.github/workflows/ci.yml`, on push to `main` and on pull requests:

- `python` job: `ubuntu-latest`, service `postgres:16` with user/password/db `tri_analyze` on port 5432, `astral-sh/setup-uv`, `uv sync`, then `uv run tri migrate` and `uv run tri migrate --test` with `DATABASE_URL`/`TEST_DATABASE_URL` pointing at the service (the test database is created with one `psql -c "create database tri_analyze_test"` step first), then the four checks in the definition-of-done order: `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest -q`, `uv run mypy`. `LANGSMITH_TRACING=false` is set explicitly. No secrets are needed: nothing in the suite calls Anthropic or the MCP servers without `--live`.
- `web` job: `actions/setup-node` with Node 22 and npm cache keyed on `web/package-lock.json`, `npm ci`, `npm run lint`, `npm run build`, `npm test`. Playwright is not run in CI (it stubs every route today and needs a browser install; it stays a local command).
- Both jobs must pass; branch protection on `main` is Brian's to set in the GitHub UI and is out of this spec's code.

The db-marked tests must run in CI, not skip: the `python` job ends with a step that fails if pytest's summary reports more skips than the six known ones (`uv run pytest -q -rs | tee` and a grep on the count), so a broken service container is visible.

## 5. Behaviour

### 5.1 Migrations

1. `discover` reads `migrations/*.sql`, requires each filename to start with a distinct integer, and sorts by it. 006 and 007 are ordinary files in that sequence.
2. On a database migrated by hand up to 005, the first `tri migrate` creates `schema_migrations`, and records 001 to 005 as applied without re-running them: `apply_migrations` detects the hand-applied state by `to_regclass` of one table per file (a small table in `migrate.py`: `workouts` for 001, `training_goals` for 002, `plan_weeks.targets` column check for 003, `nutrition_targets` for 004, `lab_panels` for 005) and inserts the rows with the current file sha. Files after 005 are never back-filled; they run.
3. Every later file runs inside its own transaction; a failing statement rolls that file back, leaves earlier ones recorded, and exits 1.
4. The README's psql loop is replaced by `uv run tri migrate && uv run tri migrate --test`. The `db/README.md` "applied by hand" paragraph is rewritten; the read-only rule there stays.
5. Package conftests keep their `to_regclass` probes; they are cheap and still the right skip when a developer forgets `--test`.

### 5.2 The reader role

`007_reader_role.sql`:

```sql
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'tri_reader') then
    create role tri_reader login password 'tri_reader' nosuperuser nocreatedb nocreaterole noinherit;
  end if;
end $$;
revoke all on schema public from tri_reader;
grant usage on schema public to tri_reader;
grant select on all tables in schema public to tri_reader;
alter default privileges for role tri_analyze in schema public grant select on tables to tri_reader;
alter role tri_reader set default_transaction_read_only = on;
alter role tri_reader set statement_timeout = '5s';
```

`pg_signal_backend` is not granted, so `pg_terminate_backend` and `pg_cancel_backend` on another role's backend fail with permission denied. Tables created later inherit SELECT through the default privileges, so migrations after 007 need nothing extra. The role is created in both databases by the same file.

### 5.3 MCP environment

The child gets the five passthrough keys when set and `spec.env`. `ANTHROPIC_API_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL`, `LANGSMITH_*`, `TRI_*`, `GARMIN_*` and `TP_*` from the shell are absent unless `spec.env` sets them. Keychain access for the TrainingPeaks cookie needs no environment variable; the recorded MCP fixtures and the `--live` tests are the check that both servers still start.

### 5.4 TypeScript strict

`"strict": true` goes into both tsconfigs. `tsc -b` errors are fixed in source, never with `!` non-null assertions or `any` (the plan lists each file it touches). The generated `types.ts` is regenerated with `npm run types` only if the Python side changed, which this spec does not require.

## 6. Errors

- `tri migrate` on an unreachable database prints the psycopg error and exits 1 before touching anything.
- A sha mismatch exits 1 with `migrations/00N_x.sql was edited after it was applied (recorded <sha8>, file <sha8>)`.
- The SQL tool on a database without 007 fails to connect as `tri_reader`; the tool returns `{"error": "sql error: ..."}` as it does for any connection failure, and the README's setup order (migrate before first run) prevents it.
- A CI run whose Postgres service is down fails at the `tri migrate` step, not at a silent skip.

## 7. Testing

- `packages/tri-core/tests/test_migrate.py` (db-marked, on the rolled-back test connection where possible; the apply path uses a scratch schema created and dropped inside the test): `discover` ordering and duplicate-version rejection; first run on a hand-migrated database back-fills 001 to 005 and runs the rest; second run is a no-op; an edited applied file raises `MigrationError`; `dry_run` changes nothing.
- `test_cli.py` in tri-core: `tri migrate --dry-run` prints the pending list; exit 1 on `MigrationError` (stubbed).
- `test_sql_tool.py` gains: connecting as `tri_reader`, `select` works, `pg_terminate_backend(pg_backend_pid())` inside a SELECT returns the permission-denied rejection, an `insert` inside a CTE is rejected by the role and not only by the transaction flag. These are db-marked and skip until 007 is applied to the test database (a `to_regclass`-style probe on `pg_roles`).
- `test_mcp_env.py`: `child_env` includes `PATH` and `HOME`, excludes `ANTHROPIC_API_KEY` and `DATABASE_URL` when they are set in `os.environ`, and `spec.env` wins over a passthrough key.
- `test_config.py`: `readonly_url` derives the user swap and respects the explicit field.
- CI is tested by the first green run on the PR that adds it; the workflow file itself has no unit test.
- Web: `npm run build` passing under strict is the test; existing Vitest files must still pass.

## 8. Out of scope

- Type-aware ESLint rules and type-checking tests with mypy.
- Playwright in CI.
- Rotating the `tri_reader` password or moving secrets out of `.env`.
- Dependabot or lockfile update automation.
- A `tri ready` doctor command; `tri migrate --dry-run` covers the schema half of it.

## 9. Rollout

1. Plan 01: `migrate.py`, `tri migrate`, migrations 006 and 007, `readonly_url`, the SQL tool call sites, `child_env`, README and `.env.example` updates, `setup_checkpointer.py` deleted. Brian runs `uv run tri migrate && uv run tri migrate --test` after merge.
2. Plan 02: TypeScript strict and the resulting source fixes; `ci.yml`. The first PR with the workflow is the check that the service container and both `tri migrate` steps work.
