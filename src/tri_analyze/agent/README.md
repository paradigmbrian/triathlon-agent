# `agent/`: the LangChain part

How the agent works, module by module, and why it is built this way. Update this when the
agent's architecture changes. See also: [`../sync/README.md`](../sync/README.md),
[`../db/README.md`](../db/README.md), [`../mcp/README.md`](../mcp/README.md).

## The mental model

A LangChain agent is three things: a chat model, a list of tools, and a loop.

1. The model receives the conversation plus a description of every tool.
2. It replies either with text or with a structured request: "call this tool with these
   arguments."
3. LangChain runs the tool, appends the result to the conversation, and calls the model again.
4. The loop ends when the model replies with text and no tool call.

Everything in this directory is either a tool, prompt material the model reads, or plumbing
around that loop.

## Modules

```
agent/
  sql_tool.py     query_training_db: the agent's main tool, read-only by construction
  prompt.py       Athlete context + system prompt rendering + feedback rules
  agent.py        make_model (ChatAnthropic) + build_agent (create_agent graph)
  live_tools.py   MCP server tools bound as LangChain tools over persistent sessions
  repl.py         Streaming terminal loop; prints every tool call
```

`cli.py` (one level up) wires these together for `tri-analyze chat`.

### `sql_tool.py`: the tool is a function plus a docstring

A LangChain tool is a typed Python function wrapped with `@tool`. LangChain turns the
signature into a JSON schema and sends the docstring to the model as the tool's description.
That description, plus `SCHEMA_DOC`, is the model's **only** knowledge of the database. When
the model writes wrong SQL, the fix is almost always in `SCHEMA_DOC` (add a column note, add
an example query), not in code.

Safety is layered so no single check has to be perfect:

- `validate_select` rejects anything that is not one `SELECT`/`WITH` statement.
- `run_readonly_query` opens its own connection with `read_only=True`, so Postgres itself
  refuses writes, including an `INSERT` hidden inside a CTE. A statement timeout (5 s) and a
  row cap (200) bound cost.
- SQL errors come back as `{"error": ...}` text, never as exceptions. The model reads the
  error and retries with better SQL. That retry is the agent loop doing its job.

### `prompt.py`: the system prompt is rendered from data

`load_athlete_context` reads thresholds, the last seven days of load and recovery, and the
workouts one week either side of today. `render_system_prompt` turns that into text and
appends `FEEDBACK_RULES`, which encode what a good session review covers (planned vs actual,
execution quality, load context, athlete comments, concrete takeaways) and the rule "compute
with SQL, not in your head."

Two properties matter:

- **Rendered once per session.** The model has FTP, LTHR, current TSB in view for every
  answer without a tool call.
- **Deterministic.** Same data, same bytes. Anthropic's prompt cache matches on an exact
  prefix, so a stable system prompt plus a stable tool list means every turn after the first
  reads the prefix from cache at a fraction of the cost.

`/sync` in the REPL re-renders this prompt (fresh context) while keeping conversation memory.

### `agent.py`: `create_agent` builds a graph

`make_model` wraps Claude in `ChatAnthropic`, LangChain's adapter over the Anthropic SDK. No
`thinking` parameter is passed; adaptive thinking is the model default on Claude Opus 5.

`build_agent` calls `create_agent(model, tools, system_prompt=..., middleware=[...],
checkpointer=...)`. The result is a LangGraph: a state machine with a `model` node and a
`tools` node and an edge that loops while tool calls exist. Two arguments carry most of the
meaning:

- **Checkpointer** (`InMemorySaver`). State is stored per `thread_id`. Each REPL turn sends
  only the new human message; LangGraph loads the prior messages from the saver. That is what
  makes it a conversation instead of independent calls. Threads are isolated from each other.
- **Middleware** (`AnthropicPromptCachingMiddleware`). Wraps each model call and adds
  Anthropic's `cache_control` marker so the system prompt and tool schemas get cached.
  `unsupported_model_behavior="ignore"` lets the same graph run on the scripted test model.

### `repl.py`: streaming shows the loop

`run_turn` calls `agent.astream(..., stream_mode=["messages", "updates"])`.

- `messages` events are token chunks as the model generates. These print inline.
- `updates` events fire when a graph node finishes. A finished `model` node carries any tool
  calls the model requested, printed as `→ name(args)`. A finished `tools` node carries the
  `ToolMessage`, printed as `← name: N chars`.

So the arrow lines in the terminal are literally the graph's node transitions. Anthropic API
errors (rate limit, status, connection) are caught per turn and printed; the loop continues.

### `live_tools.py`: MCP tools become LangChain tools

`langchain-mcp-adapters` does the conversion. `MultiServerMCPClient.session(name)` launches a
server over stdio and keeps the session open; `load_mcp_tools(session)` fetches the server's
tool list and turns each JSON schema into a `BaseTool`. From the model's point of view a Garmin
tool and `query_training_db` are the same kind of thing.

`filter_tools` applies `../mcp/allowlist.py`. The servers expose about 190 tools between them.
Binding all of them would inflate every request and give the model more wrong choices, so the
agent sees five: Garmin `get_activity`, `get_activity_splits`, `get_training_readiness`,
`get_hrv_data`, and TrainingPeaks `tp_get_workout`. Sessions live inside an `AsyncExitStack`
for the whole chat, so a tool call is a fast round-trip rather than a `uvx` relaunch. A server
that fails to start is logged and skipped; the chat still opens with the tools that did bind.

### `tests/fakes.py`: testing an LLM app without an LLM

`ScriptedChatModel` is a `BaseChatModel` that replays a list of `AIMessage`s you hand it, for
both `invoke` and `stream`. Tests prove the tool loop, memory, thread isolation, and the
stream printer deterministically and for free. The real model is only involved in `chat`.

## One question, end to end

> "Give me feedback on my last completed ride. Pull the laps."

1. REPL sends a `HumanMessage` into the graph on thread `repl`.
2. Model node: reads the system prompt and the tool schemas, emits a `query_training_db` call
   to find the ride and its `garmin_activity_id`.
3. Tools node: runs the SQL on a read-only connection, appends the JSON as a `ToolMessage`.
4. Model node: emits `get_activity_splits(activity_id=...)`.
5. Tools node: the MCP session forwards the call to the Garmin server process; laps come back.
6. Model node: writes the review following `FEEDBACK_RULES`, no further tool calls.
7. The loop exits; the saver stores all six messages under the thread for the next turn.

With `LANGSMITH_TRACING=true`, every hop is recorded with the exact prompt, tool schema JSON,
and token counts (look for `cache_read_input_tokens` on the second turn).

## Design decisions and why

| Decision | Why |
|---|---|
| One flexible read-only SQL tool instead of many narrow query tools | The model composes its own questions. Safety comes from the connection mode, not from limiting what it can ask. |
| System prompt rendered from data, not fetched via tools | Cheaper and faster; the model always has thresholds and current load in view. |
| Raw MCP tools with an allow-list, not hand-written wrappers | Less code, and it is the real LangChain-plus-MCP integration rather than a facade. |
| Tool binding order is fixed (SQL, Garmin, TP) | The tool list is part of the cached prompt prefix; reordering invalidates the cache. |
| In-memory checkpointer | Enough for a REPL session. A Postgres checkpointer is a one-line swap for milestone 5. |
| Async REPL | MCP sessions are async and must stay open across turns. |

## Knobs you will actually turn

- **The model writes bad SQL:** edit `SCHEMA_DOC` in `sql_tool.py`. Add a column note or an
  example query shaped like the question that failed.
- **Feedback is vague or misses something:** edit `FEEDBACK_RULES` in `prompt.py`.
- **The model ignores a live tool or picks the wrong one:** edit `_tools_block` in
  `prompt.py` (how the tools are described) or `../mcp/allowlist.py` (which are bound).
- **Model or cost:** `TRI_MODEL` in `.env`; `MAX_TOKENS` in `agent.py`.
- **How much context the prompt carries:** the date windows in `load_athlete_context`.
