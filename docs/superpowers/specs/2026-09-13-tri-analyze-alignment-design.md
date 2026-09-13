# tri-analyze alignment — the analyst in line with the other agents (package `tri_analyze`)

**Date:** 2026-09-13
**Status:** Approved design, pending implementation plan
**Purpose:** Bring `tri-analyze`, the first agent built and the only one without a current spec, in line with `tri-planning`, `tri-nutrition`, `tri-wellness` and `tri-coach` in layout, settings, LangChain, LangGraph and LangSmith use, testing and documentation. Fix the defects found in review. Add a LangSmith evaluation of the analyst's prompt. Behavior for the athlete does not change except where a defect is fixed.

Supersedes, for the agent, `2026-09-06-tri-analyze-design.md`. That spec describes the pre-workspace single package (`tri-analyze sync`, the ETL, the data layer), which now lives in `tri-core`; it stays as history with its Status line updated.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | `tri-analyze` only, plus the import and call-site changes `tri-coach` needs. | Hoisting the helpers duplicated across packages (`TurnPrinter`, `run_turn`, `chat_loop`, `make_model`, `seed_workouts`, `pass_rates`) into `tri-core` conflicts with tri-core's "no LLM code" charter and is a separate spec. |
| Agent shape | Keep `create_agent` (model and tools loop). No `StateGraph`. | The analyst is read-only question answering with no review gate, phases or writes; `tri-coach` runs it as an agent-as-tool. Same shape as `tri-wellness` chat. |
| Layout | Flat, like the siblings: `config.py`, `llm.py`, `agent.py`, `repo.py`, `prompts/`, `tools/`, `repl.py`, `testing.py`, `evals/`. The `agent/` sub-package is removed. | Consistency is the point of this work; `tri-wellness` is the closest precedent. |
| System prompt | Rendered by `@dynamic_prompt` middleware from the athlete data passed as runtime context (`context_schema=AthleteContext`) and the names of the bound tools (`request.tools`). | `/sync` refreshes the prompt without rebuilding the agent, which removes the `_Proxy` in `cli.py`. Callers supply data, not rendered text. |
| Conversation memory | `InMemorySaver`, as today. | The siblings that persist threads in Postgres do so for interrupts and multi-step workflow state; the analyst has neither. Persistence would grow token cost across long threads and carry answers computed from older synced data. `tri-coach` uses a throwaway thread per question regardless. |
| Evaluation | `tri-analyze eval`: code checks over the tool calls and the answer, plus an LLM judge, over stub tools with canned results. | Measures both behavior (SQL for trends, splits for intervals, a stated window) and feedback quality, with no database or MCP servers. Same pattern as the `tri-coach` routing eval. |
| Documentation | `agent/README.md` merges into `packages/tri-analyze/README.md` in the siblings' shape. | One README per package, as every sibling; the walkthrough content is kept and updated. |
| Weekly review | Not in this spec. | It overlaps `tri-planning check-in` and `tri-coach check-in`; its role needs its own design. |

## 2. Feasibility, verified 2026-09-13

Installed: langchain 1.4.0, langchain-core 1.6.2, langchain-anthropic 1.7.1, langsmith 0.12.2.

- `langchain.agents.middleware.dynamic_prompt` wraps a function of `ModelRequest`; `ModelRequest` carries `runtime`, `state`, `tools`, `system_message`. `create_agent` accepts `context_schema`.
- Probe: an agent built with `middleware=[<dynamic_prompt>, AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")]`, `context_schema` a dataclass and an `InMemorySaver`. Two turns on one thread, the first via `ainvoke(..., context=Ctx("before"))`, the second via `astream(..., context=Ctx("after"), stream_mode=["messages", "updates"])`. The model received system prompts `ctx=before` then `ctx=after`; the thread held `["1", "a", "2", "b"]`. The system prompt is not stored in the checkpoint, so a new context replaces it on the next model call.
- Probe: `create_agent(...).with_config({"tags": ["analyst"], "metadata": {"analyst_prompt_version": "1"}})` returns a `CompiledStateGraph`. With a per-call `tags: ["chat"]`, a callback saw tags `analyst` and `chat` and the metadata on every model run, for both `ainvoke` and `astream`; `aget_state` returned the thread.
- `tri_core.db.sql_tool.make_query_tool(url)` opens no connection at construction, so the eval's stub can take the real tool's description (docstring plus `SCHEMA_DOC`).
- A langsmith evaluator may return `{"results": [EvaluationResult, ...]}` (`EvaluationResults`), so one judge call can score two keys.
- `tri-coach` binds two extra tools into the analyst (`graph/deps.py` `analyst_tools_for`): `read_body_composition(days: int = 28)` and `read_intake_vs_targets(days: int = 7)`, from `tri-nutrition`.

## 3. Defects fixed

1. `agent/prompt.py:60` tells the model to run `tri-analyze sync`; the command is `tri sync`.
2. `agent/README.md` links `../sync/README.md`, `../db/README.md`, `../mcp/README.md`, which moved to `tri-core`.
3. Under `tri-coach`, `read_body_composition` and `read_intake_vs_targets` are bound but the prompt's tool block describes only the five standalone tools.
4. The LangSmith project is never set by the package; it is correct only because the shared `.env` carries `LANGSMITH_PROJECT=tri_analyze`.
5. `tri-analyze chat` with the database down ends in a traceback.

## 4. Package layout

```
packages/tri-analyze/
  pyproject.toml          adds langsmith>=0.12,<1
  README.md               the siblings' shape (§10)
  src/tri_analyze/
    __init__.py
    config.py             AnalyzeSettings(Settings): tri_analyze_langsmith_project = "tri_analyze";
                          get_analyze_settings() (lru_cache)
    llm.py                MAX_TOKENS = 16000; make_model(settings) -> ChatAnthropic
    agent.py              analyst_prompt (@dynamic_prompt); build_agent(model, tools, checkpointer=None)
    repo.py               AthleteContext (dataclass); load_athlete_context(conn, today)
    prompts/
      __init__.py
      analyst.py          PROMPT_VERSION; FEEDBACK_RULES; TOOL_GUIDE; render_system_prompt(ctx, tool_names)
    tools/
      __init__.py
      live.py             open_live_tools(settings, log): unchanged apart from the move
    allowlist.py          unchanged
    repl.py               TurnPrinter, run_turn, chat_loop
    cli.py                chat, eval
    testing.py            athlete_context(**over), RecordingScriptedModel, seed_workouts, seed_daily_metrics
    evals/
      __init__.py
      cases.py            EvalCase, CASES, TODAY
      target.py           stub_tools(inputs), run_case, make_target
      evaluators.py       uses_sql, pulls_splits, states_window, make_judge
      run.py              DATASET_NAME, case_examples, ensure_dataset, pass_rates, render_pass_rates, run_eval
  tests/
    test_config.py  test_repo.py  test_prompt.py  test_agent.py  test_llm.py
    test_repl.py    test_cli.py   test_live_tools.py  test_evals.py
```

Removed: `src/tri_analyze/agent/` (`__init__.py`, `agent.py`, `live_tools.py`, `prompt.py`, `repl.py`, `README.md`).

## 5. Components

### 5.1 `repo.py`

`AthleteContext` keeps its fields: `today: date`, `profile: dict[str, Any] | None`, `recent_days: list[dict[str, Any]]`, `recent_workouts: list[dict[str, Any]]`. `load_athlete_context(conn, today)` keeps its three queries and windows: the profile row, `daily_metrics` from `today - 7 days` to `today`, `workouts` from `today - 7 days` to `today + 7 days` ordered by date and `tp_workout_id`.

### 5.2 `prompts/analyst.py`

- `PROMPT_VERSION = "1"`, with the siblings' comment: bump whenever the prompt text changes; names the eval experiment `analyst-v<N>`.
- `FEEDBACK_RULES`: unchanged text.
- `TOOL_GUIDE: dict[str, str]`, one line per tool name:
  - `query_training_db`: anything already synced (workouts, planned vs actual, weekly volume, CTL/ATL/TSB, sleep, HRV, readiness, thresholds and zones); prefer it over live tools for synced data.
  - `get_activity_splits`: lap and interval detail; `activity_id` is `workouts.garmin_activity_id`.
  - `get_activity`: a Garmin activity summary.
  - `get_training_readiness`, `get_hrv_data`: recovery for a date not yet synced, such as today.
  - `tp_get_workout`: the coach's structured plan and comments for one session.
  - `read_body_composition`: index-scale weight, body fat and muscle mass over the last `days` days.
  - `read_intake_vs_targets`: logged intake against the nutrition targets over the last `days` days.
- `render_system_prompt(ctx: AthleteContext, tool_names: list[str]) -> str`: the existing blocks in the existing order (role, today, thresholds, recent load, workouts, tools, rules). The tools block lists every bound name in bound order, then the guide line for each bound name that has one. When no tool other than `query_training_db` is bound it says so ("No live tools are bound this session; work from the database only."). The thresholds fallback reads "not available (run `tri sync`)". Output is a pure function of its arguments.

### 5.3 `agent.py`

```python
@dynamic_prompt
def analyst_prompt(request: ModelRequest) -> str:
    names = [t.name if isinstance(t, BaseTool) else str(t["name"]) for t in request.tools]
    return render_system_prompt(request.runtime.context, names)


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    agent = create_agent(
        model,
        list(tools),
        middleware=[analyst_prompt, AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        context_schema=AthleteContext,
        checkpointer=checkpointer or InMemorySaver(),
    )
    return agent.with_config(
        {"tags": ["analyst"], "metadata": {"analyst_prompt_version": PROMPT_VERSION}}
    )
```

The prompt middleware is listed first so the caching middleware marks the rendered system prompt. Every run must pass `context=`; a missing context is a programming error and is not defended against. Tool order is the order passed in (SQL, Garmin, TrainingPeaks, then any extras), which keeps the cached prefix stable.

### 5.4 `llm.py`, `config.py`, `tools/live.py`

`make_model` and `MAX_TOKENS` move unchanged. `AnalyzeSettings` adds only the LangSmith project. `open_live_tools(settings, log)` keeps its signature.

### 5.5 `repl.py`

- `TurnPrinter`: unchanged.
- `run_turn(agent, text, thread_id, out, *, context: AthleteContext, tags: list[str] | None = None) -> str`: streams with `stream_mode=["messages", "updates"]`, `context=context`, and `tags` in the run config when given. Catches `anthropic.RateLimitError`, `APIStatusError`, `APIConnectionError` as today, then any other `Exception`, printing `[the turn failed: <Type>: <message>]`. Returns the final text.
- `chat_loop(agent, *, read, out, context: Callable[[], AthleteContext], thread_id: str = "analyze", commands=None)`: calls `context()` before each turn and passes it to `run_turn` with `tags=["chat"]`. Banner, `/quit`, unknown command handling and EOF behavior are unchanged.

### 5.6 `cli.py`

Module top, in the siblings' order: `load_dotenv()`, then `os.environ["LANGSMITH_PROJECT"] = get_analyze_settings().tri_analyze_langsmith_project` before anything imports LangChain, then `app`, `console`, `THREAD_ID = "analyze"`, module-level `_out(s)` and `_read()`. Everything heavy is imported inside the commands.

`chat --no-live`:
1. `ANTHROPIC_API_KEY` missing: print the existing message, exit 2.
2. Open live tools unless `--no-live`; tools are `[make_query_tool(url), *live_tools]`.
3. Load `AthleteContext` for today; on `psycopg.OperationalError` print `database unreachable: <message>` and exit 2.
4. `agent = build_agent(make_model(settings), tools)`, built once for the session.
5. Commands: `/tools` (unchanged), `/prompt` renders `render_system_prompt(current, [t.name for t in tools])`, `/sync` runs `run_sync`, reloads the context into the holder the loop reads, and reports as today.

`eval [--prefix NAME] [--recreate-dataset]`: `LANGSMITH_API_KEY` missing, exit 2; `ANTHROPIC_API_KEY` missing, exit 2. Runs `run_eval(settings, make_model(settings), prefix=..., recreate=..., log=...)`. Exit 0 when every evaluator's pass rate is 1.0 and no example errored, otherwise 1.

### 5.7 `testing.py`

- `athlete_context(**over) -> AthleteContext`: the fixture the current `test_prompt.py` builds inline (today 2026-09-06, FTP 230, LTHR 180, run threshold 270 s/km, CSS 104 s/100 m, one day of metrics, one completed Z2 ride).
- `RecordingScriptedModel(ScriptedChatModel)`: keeps every message list received, for both `_generate` and `_stream`. A copy of the `tri-wellness` helper extended to streaming; `tri-analyze` does not depend on `tri-wellness`.
- `seed_workouts(conn, rows)`, `seed_daily_metrics(conn, rows)`: the `tri-wellness` helpers, copied.

## 6. Changes to `tri-coach`

- `tools/analyst.py`: imports `build_agent` from `tri_analyze.agent` and `load_athlete_context` from `tri_analyze.repo`. The `live` name list and the `render_system_prompt` call go. Each question runs `build_agent(model, tools, InMemorySaver())` then `ainvoke({"messages": [HumanMessage(question)]}, {"configurable": {"thread_id": ...}, "recursion_limit": ANALYST_RECURSION_LIMIT}, context=ctx)`. The tool's name, description and failure texts are unchanged.
- `context.py`: imports `load_athlete_context` from `tri_analyze.repo`.
- `allowlist.py`: unchanged (`tri_analyze.allowlist` stays).
- README and spec text naming `tri_analyze.agent.*` paths is updated where it exists.

Coach behavior is unchanged except that the analyst now receives guide lines for its two extra tools, and analyst runs under the coach carry the `analyst` tag and `analyst_prompt_version` metadata.

## 7. Evaluation

### 7.1 Cases (`evals/cases.py`)

`TODAY = date(2026, 9, 16)`, the date the `tri-coach` eval uses. `EvalCase` fields:

| Field | Meaning |
|---|---|
| `name` | unique id, also the LangSmith example metadata `case` |
| `question` | the athlete's message |
| `athlete` | an `AthleteContext` for `TODAY` |
| `live` | bind the five live tool stubs |
| `extra_tools` | names of coach-only tools to bind (`read_body_composition`, `read_intake_vs_targets`) |
| `tool_results` | `dict[str, list[str]]`: responses per tool name, served in call order, the last repeated |
| `kind` | `session`, `trend` or `readiness` |
| `requires_sql`, `requires_splits`, `expects_window` | flags for the code checks |

`inputs()` returns `{question, athlete (JSON-safe), live, extra_tools, tool_results}`; `outputs()` returns `{kind, requires_sql, requires_splits, expects_window}`.

Twelve cases:

- Session: last Z2 ride; a run interval session (requires splits); a missed session; a hard session with RPE 9 and athlete comments; a brick.
- Trend: weekly TSS over eight weeks; run volume month over month; sleep against HRV.
- Readiness: "should I go hard today?" with readiness and HRV stubs.
- Edge: a trend question whose SQL returns `[]` (the answer must say the data is missing); an interval question with `live` false (the answer must say splits are not available); a body-composition question with `read_body_composition` bound.

### 7.2 Target (`evals/target.py`)

- `stub_tools(inputs) -> list[BaseTool]`: `query_training_db(sql: str)` with the description of `make_query_tool("postgresql://unused/db")`; when `live`, `get_activity(activity_id)`, `get_activity_splits(activity_id)`, `get_training_readiness(date)`, `get_hrv_data(date)`, `tp_get_workout(workout_id)`; then each name in `extra_tools` (`read_body_composition(days: int = 28)`, `read_intake_vs_targets(days: int = 7)`). Live and extra stubs carry a one-line description. Every stub answers from `tool_results`, or `[]` when the case gives none. Order matches the real binding.
- `run_case(model, inputs)`: `build_agent(model, stub_tools(inputs))`, then `ainvoke` with the question, a fresh thread id, `recursion_limit` 30, `tags: ["eval"]`, and `context=` the case's `AthleteContext`. Returns `{"calls": [{name, args}], "answer": <last AI text without tool calls>}`. Exceptions propagate so LangSmith records the example as errored.
- `make_target(model)`: the async closure `aevaluate` calls.

### 7.3 Evaluators (`evals/evaluators.py`)

A check that does not apply to a case scores `None`, which the pass rate leaves out.

| Key | Applies when | Score 1 when |
|---|---|---|
| `uses_sql` | `requires_sql` | at least one `query_training_db` call |
| `pulls_splits` | `requires_splits` and the case is `live` | at least one `get_activity_splits` call |
| `states_window` | `expects_window` | the answer contains an ISO date, a month-and-day date, or a relative window ("last N days/weeks/months") |
| `grounded` | always (judge) | every number in the answer appears in the context or the tool results, and missing data is stated rather than guessed |
| `feedback_quality` | `kind == "session"` (judge) | all five `FEEDBACK_RULES` points are covered, athlete comments are used when present, one or two concrete takeaways, no generic encouragement |

`make_judge(model)`: `model.with_structured_output(FeedbackJudgement)`, one call per example over a prompt holding the case's rendered system prompt, the question, the tool results and the answer. Returns `{"results": [grounded, feedback_quality]}`. A judge call that raises scores both keys 0 with the error as the comment.

### 7.4 Runner (`evals/run.py`)

`DATASET_NAME = "tri_analyze_feedback"`. `ensure_dataset(client, recreate)` as in the siblings. `run_eval(settings, model, *, judge=True, prefix=None, recreate=False, log=print)` runs `aevaluate(make_target(model), data=DATASET_NAME, evaluators=[...], experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}", metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model}, client=client, max_concurrency=2)`. It logs the experiment name, the pass rate per key (`render_pass_rates`), and `N errored` when any row carries an error. It returns the rates and the error count. `pass_rates` and `render_pass_rates` are copies of the `tri-wellness` functions.

## 8. Error handling

| Failure | Behavior |
|---|---|
| Anthropic rate limit, status or connection error in a chat turn | Printed; the loop continues (unchanged). |
| Any other exception in a chat turn | `[the turn failed: Type: message]`; the loop continues; the thread keeps its last checkpoint. |
| Database unreachable at chat start | `database unreachable: ...`, exit 2. |
| `/sync` with errors | Reported as today; the context reloads from whatever was stored. |
| MCP server fails to start | Logged and skipped (unchanged). |
| Eval example raises | Recorded as errored in LangSmith; counted and printed; `eval` exits 1. |
| Judge call raises | `grounded` and `feedback_quality` score 0 with the error as the comment. |
| Missing API keys | Exit 2 with the variable named. |

## 9. Testing

Tests are async where they run an agent, and use `tri_core.testing` and `tri_analyze.testing`. `db` and `live` markers as in the workspace.

| File | Covers |
|---|---|
| `test_config.py` | defaults (`tri_analyze` project, inherited `database_url`); env override |
| `test_repo.py` (db) | `load_athlete_context`: windows 7 days back and 7 forward, upcoming workouts included, ordering, empty tables |
| `test_prompt.py` | existing assertions; done, planned and missed markers; the `tri sync` hint; guide lines only for bound tools, including the coach extras; an unbound guide entry is absent; an unknown bound tool is listed without a guide line; every allow-listed tool has a guide entry; the no-live sentence; determinism |
| `test_agent.py` | tool loop; memory across turns; thread isolation; the model sees the prompt rendered from the context; changing the context on one thread changes the prompt and keeps the history; tool order preserved; `analyst` tag and `analyst_prompt_version` reach the model run (callback spy) |
| `test_llm.py` | `make_model` reads model and `MAX_TOKENS` |
| `test_repl.py` | existing assertions; the context is passed on each turn and a changed holder is used next turn; a generic exception is printed and the loop continues; `chat` tag on turns |
| `test_cli.py` | `chat` exit 2 without the Anthropic key; `eval` exit 2 without either key; `eval` exit codes from rates and errors (`run_eval` stubbed); `LANGSMITH_PROJECT` set on import |
| `test_live_tools.py` | allow-lists are read-only; live: bound names equal the allow-lists; live: each live stub's argument names equal the real tool's schema properties |
| `test_evals.py` | cases valid (unique names, every kind covered, flags coherent, `inputs`/`outputs` shape, JSON-safe); stub names and order match the real binding and the stub `query_training_db` description equals the real one; target over `ScriptedChatModel` returns calls and answer; each code check on pass, fail and `None`; judge via `tool_call` structured output, including the raising path; `ensure_dataset` with a fake client; `pass_rates`, `render_pass_rates`, error counting |

`tri-coach`: the existing tests, including `test_evals.py`'s stub-versus-real `ask_analyst` description check, pass unchanged. One test is added: `ask_analyst` passes `context=` and the analyst model receives the prompt rendered from it.

Definition of done: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`, `uv build --package tri-analyze`, all from the workspace root.

## 10. Documentation

- `packages/tri-analyze/README.md`: intro with links to this spec and its plans; How it works (the model, tools and loop; `@dynamic_prompt` and runtime context; prompt caching); Commands; Layout; How a turn flows (one question end to end); Evaluation; Knobs; Design decisions (in-memory checkpointer and why; tools described by name; one SQL tool; fixed tool order). Content from `agent/README.md` carries over, updated.
- `agent/README.md`: deleted.
- Root `README.md`: the `tri-analyze` row reads `tri-analyze chat | eval`; the Run section adds `uv run tri-analyze eval [--recreate-dataset]`; the two links to `agent/README.md` point to the package README.
- `.env.example`: a `# tri-analyze` block with `TRI_ANALYZE_LANGSMITH_PROJECT=tri_analyze`.
- `2026-09-06-tri-analyze-design.md`: Status line only, marked superseded for the agent by this spec, with sync and data in `tri-core`.
- Obsidian (`/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/`): this spec and its plans are copied to `docs/superpowers/`; `packages/tri-analyze/readme.md`, root `readme.md` and the old spec's copy get the same edits; `packages/tri-analyze/src/tri_analyze/agent/readme.md` is removed.

## 11. Observability

- Project: `tri_analyze`, set by `cli.py` from `TRI_ANALYZE_LANGSMITH_PROJECT`.
- Tags: `analyst` on every analyst run (from `build_agent`); `chat` on REPL turns; `eval` on eval targets. Under `tri-coach` the analyst's runs appear in the `tri_coach` project with the `analyst` tag.
- Metadata: `analyst_prompt_version` on every analyst run; experiments carry `prompt_version` and `model`.

## 12. Milestones

1. **Alignment.** Layout, `config.py`, `llm.py`, `repo.py`, `prompts/analyst.py` with `TOOL_GUIDE` and the fixes, `agent.py` with `@dynamic_prompt` and run config, `repl.py`, `cli.py` chat, `testing.py`, the `tri-coach` changes, tests for all of it, README, root README, `.env.example`, old spec status, Obsidian copies.
2. **Evaluation.** `evals/`, `tri-analyze eval`, the live stub-schema test, `test_evals.py`, `test_cli.py` eval cases, the README Evaluation section, root README Run line.

## 13. Out of scope

- Moving shared helpers into `tri-core`.
- A weekly review command.
- A Postgres checkpointer for the analyst.
- Any `tri-coach` behavior, prompt or eval change beyond §6.
- Changes to `tri-core`'s `SCHEMA_DOC` or the allow-lists.
