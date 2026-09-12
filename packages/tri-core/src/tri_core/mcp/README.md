# `mcp/`: talking to the Garmin and TrainingPeaks MCP servers

Both data sources are third-party MCP servers run as local subprocesses over stdio. This
directory knows how to launch them, how to call their tools without an LLM, and which tools
the agent is allowed to call live. See also: [`../sync/README.md`](../sync/README.md),
[`../agent/README.md`](../agent/README.md).

## Modules

```
mcp/
  servers.py     ServerSpec + garmin_spec()/trainingpeaks_spec(): command, args, env
  client.py      McpToolClient (async ctx manager) + parse_tool_text(): programmatic calls
  live_tools.py  open_live_servers (tools per server) and open_live_tools (flattened); the
                 generic opener used by tri-analyze, tri-planning and tri-coach
  caller.py      ToolsCaller: a ToolCaller over adapter-bound tools, so one session serves both
                 the model (BaseTools) and call_json (the sync/apply path)
  (allowlist.py) GARMIN_LIVE_TOOLS / TP_LIVE_TOOLS: what an agent may call live; one per
                 agent package (tri_analyze, tri_planning)
```

## The servers

| | Garmin | TrainingPeaks |
|---|---|---|
| Repo | github.com/Taxuspt/garmin_mcp | github.com/JamsusMaximus/trainingpeaks-mcp |
| Pinned commit | `GARMIN_MCP_REF` in `.env` | `TP_MCP_REF` in `.env` |
| Launch | `uvx --python 3.12 --from git+<repo>@<ref> garmin-mcp` | `uvx --from git+<repo>@<ref> tp-mcp serve` |
| Auth | tokens in `~/.garminconnect` (from `garmin-mcp-auth`, MFA once, ~6 months) | cookie in macOS Keychain (from `tp-mcp auth --from-browser chrome`) or `TP_AUTH_COOKIE` |
| Tools exposed | ~110; we set `GARMIN_ENABLED_TOOLS` so only 7 register | ~85 |
| `mcp` SDK major | 1.x | 2.x |

The two servers pin incompatible `mcp` majors. That is fine: each runs in its own `uvx`
environment, and our client speaks the wire protocol. Our own project uses `mcp` 1.29 because
`langchain-mcp-adapters` pins `<2`.

`uvx` caches the build, so cold start is a couple of seconds; the Garmin server also logs in
on start. `ServerSpec.env` is merged over `os.environ` when launching, because `uvx` needs
`PATH` and `HOME` and the MCP SDK's default child environment is minimal.

## Two client paths

**Sync path (`client.py`).** `McpToolClient(spec)` is an async context manager that starts
the process, opens an MCP `ClientSession`, and exposes `call_json(tool, args)`. It exists so
the ETL can call tools deterministically with no model in the loop.

**Agent path (`live_tools.py`).** `langchain-mcp-adapters` opens its own session per server
and converts tools into LangChain `BaseTool`s. Same servers, same specs, different consumer.
Each agent package wraps `open_live_tools` with its own allow-lists. `open_live_servers` yields
the same tools grouped by server name (a dead server is absent), and `caller.ToolsCaller(tools)`
turns one server's list into a `ToolCaller`: `call_json` finds the tool by name, awaits it, joins
the adapter's text content blocks, and parses the text with `parse_tool_text`. That is how a
process that already holds a session for the model also serves the graph deps' `tp` and `garmin`
callers without a second subprocess (tri-coach).

## Result conventions (`parse_tool_text`)

MCP tool results are text meant for a model, so the client normalizes them:

- **TrainingPeaks** always returns JSON. Failures are `{"isError": true, "error_code": ...,
  "message": ...}` → raised as `McpToolError`.
- **Garmin** returns JSON on success, a plain string starting with `"No ... found"` when
  there is no data for that day → returned as `None`, and a string starting with `"Error"`
  on failure → `McpToolError`.
- Anything else unparseable → `McpToolError`.

These were verified from both servers' source, and the recorded fixtures in
`tests/fixtures/mcp/` are the ground truth for payload shapes. Re-record with
`uv run python scripts/spike_mcp.py` and scrub personal fields before committing.

## Tools we depend on

Sync: `tp_get_athlete_settings`, `tp_get_workouts` (90-day max range), `tp_get_workout`,
`tp_get_fitness`, `get_sleep_summary_range` (90-night max), `get_stats`,
`get_training_readiness`, `get_activities_by_date` (paginated, 200 per page).

Agent, live (allow-list): `get_activity`, `get_activity_splits`, `get_training_readiness`,
`get_hrv_data`, `tp_get_workout`. All read-only by name. Growing the agent's live
capabilities means adding a name here and, usually, a sentence in `agent/prompt.py` about
when to use it.

## When auth expires

- Garmin: the server prints "Garmin authentication expired. Re-run 'garmin-mcp-auth'". Run
  the auth command from the top-level README.
- TrainingPeaks: tools return `AUTH_INVALID`. Log into app.trainingpeaks.com in Chrome and
  rerun `tp-mcp auth --from-browser chrome`.

## Bumping a server version

Change the ref in `.env.example` and `config.py` defaults, rerun the spike, diff the fixtures,
run `uv run pytest --live`. Parser changes go in `sync/`; tool-name changes go in each
agent's `allowlist.py` and in `servers.py` (`GARMIN_ENABLED_TOOLS`).
