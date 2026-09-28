# Optimizations: smaller tool output, skipped fuel calls, parallel sync, a cacheable coach, compact extraction, a non-blocking today view

**Date:** 2026-09-28
**Status:** Draft
**Purpose:** Cut tokens and wall-clock time where the 2026-09-24 codebase review found the largest waste, without changing what any agent decides. One of three round-two specs, alongside `2026-09-28-test-gaps-design.md` and `2026-09-28-features-design.md`; independent of both. Line numbers are `fix/eval-followups` @ 0c096ca.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Coach history | Trim to a token budget; never summarize (chosen 2026-09-28). | Deterministic, no extra model call; durable facts live in the memory tool. |
| Migrations | None. New state lives in existing jsonb (`fuel_plans.payload`). | Brian runs every migration; none is needed for this work. |
| SQL output | Cap each cell, not the query. No SQL parsing. | `select *` with `raw` fills the 8,000-character budget in one row. |
| Sync watermark | Keep the 3-day overlap. No `lastModified` watermark. | No TrainingPeaks payload in code, tests or fixtures shows the field. |
| Extraction model | Stays on its current role default. | A cheaper model waits for Brian's live PDF check (§8). |
| Plans | One plan, one branch, items in §9's order. | Every item is small and independent. |

## 2. Feasibility, verified 2026-09-28

- SQL: `run_readonly_query` (`tri_core/db/sql_tool.py:121-166`) serializes cells with `_json_safe` (`:111-118`) and keeps whole rows while the JSON stays under `MAX_CHARS = 8000` (`:93`, loop `:146-154`). Raw jsonb columns: `workouts.raw`, `athlete_profile.raw`, `daily_metrics.garmin_raw`/`tp_raw`, `garmin_activities.raw`, `lab_panels.raw_extract` and others.
- Fuel: the node calls `planner.session(...)` for every qualifying session in one sequential loop (`tri_nutrition/graph/nodes/fuel.py:163-196`) and upserts each result; `repo.upsert_fuel_plan` resets `written=false` on every call. `other` caffeine carries across sessions of one day (`:161-170`). `_needs_write` (`:62-63`) compares `note_text` only; nothing hashes the inputs. Payload is `SessionFuel.model_dump`, read back as `StoredFuelPlan` (`nutrition/models.py:198`).
- Sync: Garmin calls `get_stats` and `get_training_readiness` once per day, sequentially (`tri_core/sync/garmin.py:154-160`); TrainingPeaks fetches each workout's detail sequentially (`sync/trainingpeaks.py:188-189`). All calls go through one `McpToolClient` over one stdio `ClientSession` (`tri_core/mcp/client.py:49-89`). `OVERLAP_DAYS = 3` (`sync/runner.py:25`).
- Coach: every turn rebuilds the system prompt as `COACH_RULES` + `render_context(ctx)` + memory (`tri_coach/prompts/coach.py:93-100`, called from `graph/nodes/coach.py:54`) and passes it to `make_subagent` (`:62`). `AnthropicPromptCachingMiddleware` is last in every agent (`tri_core/harness/agents.py:38-59`), so the changing context block breaks the cached prefix at the system prompt. Nothing trims the thread.
- Extraction: `extract_structured` (`tri_wellness/labs/extract/structured.py:17-36`) asks for `ExtractedPanel` (`labs/models.py:167-172`), a list of `RawResult` objects whose seven keys repeat on every row (`:28-37`). `Role.LAB_EXTRACT` has a 32,000-token budget (`tri_core/llm.py:84`).
- Web: `build_today` is `async` but runs its synchronous psycopg queries on the event loop (`tri_web/today.py:203-211`). `GET /api/coach/thread` returns the whole history (`tri_web/thread.py:102-113`, route `routes/coach.py:45`); the frontend polls it every 2 s while busy (`web/src/components/chat/useTurnStream.ts:144-155`).
- `_effort_levels` builds a `ChatAnthropic` to read its profile on every call (`tri_core/llm.py:108-111`); `fallbacks_of` calls it per fallback model per model call (`:167`).

## 3. Layout

```
packages/tri-core/src/tri_core/db/sql_tool.py              cell cap, SCHEMA_DOC sentence
packages/tri-core/src/tri_core/sync/{garmin,trainingpeaks}.py   bounded gather
packages/tri-core/src/tri_core/harness/trim.py             NEW: trim_to_budget, TurnContextMiddleware
packages/tri-core/src/tri_core/llm.py                      cached _effort_levels
packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py   inputs_sha skip, per-day gather
packages/tri-coach/src/tri_coach/{prompts/coach.py,graph/nodes/coach.py}   rules-only system prompt
packages/tri-wellness/src/tri_wellness/labs/{models.py,extract/structured.py}   compact rows
packages/tri-web/src/tri_web/{today.py,thread.py,routes/coach.py}; web/src/{api,components/chat}
```

## 4. Interfaces

### 4.1 SQL cell cap
`CELL_MAX_CHARS = 1000`. After `_json_safe`, a string cell, or a list/dict cell whose JSON exceeds it, becomes `"[cut: N chars of <column>; select that column alone, filtered to one row]"`. Numbers, booleans and dates are never cut. When any cell is cut, `note` names the cut columns. `MAX_CHARS` and the row cap stay. `SCHEMA_DOC` gains one sentence: name the columns you need; never `select *` on a table with a `raw` column.

### 4.2 Fuel: skip unchanged sessions, run days in parallel
`inputs_sha(session, target, profile, library, fuel_log, other_caffeine_mg) -> str` is the sha256 of canonical JSON (`sort_keys=True`) of those inputs plus the fuel `PROMPT_VERSION`. It is stored as `payload["inputs_sha"]`. A session is skipped when its stored plan has the same `inputs_sha` and no violations: the node rebuilds `SessionFuel` from the stored payload, makes no model call and no upsert, and still counts its caffeine. Days run under `asyncio.Semaphore(FUEL_CONCURRENCY = 4)`; sessions inside a day stay sequential (caffeine). Results are collected per day and applied in `(day, session order)` order, so `changes`, `refused` and `unmatched` read the same as today.

### 4.3 Sync: bounded gather
`SYNC_CONCURRENCY = 4`. Garmin's per-day `get_stats` + `get_training_readiness` pairs and TrainingPeaks' `tp_get_workout` calls run through `gather` under a semaphore; results are reassembled in date/id order before parsing, and progress logging stays every 25. Precondition: the plan confirms, in Context7 (the `mcp` SDK) and with a test double that interleaves responses, that one `ClientSession` serves concurrent `call_tool` requests. If it does not, that source stays sequential and the plan says so.

### 4.4 Coach: a cacheable prefix and a bounded thread
- `render_system_prompt` returns `COACH_RULES` only. `TurnContextMiddleware(render: Callable[[], str])` appends the rendered context block and memory as a text block to the newest `HumanMessage` in the model request (not in graph state), so the checkpoint and web history never store it.
- `trim_to_budget(messages, *, high=80_000, low=50_000) -> list[BaseMessage]` runs in the same middleware before the model call. It counts tokens with langchain-core's approximate counter and drops whole turns (a turn starts at a `HumanMessage`, so tool calls and results are never split). It is stateless and stable: with `step = high - low`, it drops the oldest turns whose cumulative size first reaches `ceil((total - high) / step) * step`, so the cut point moves only once per 30k tokens of growth and the cached prefix holds in between. Nothing is dropped under `high`.
- Before building on it, the plan checks the installed langchain-core / langchain `AgentMiddleware.wrap_model_call` request API and `trim_messages` / `count_tokens_approximately` in Context7 (Brian's dependency rule), and uses the library function if it can express the stable cut.

### 4.5 Compact extraction rows
`ExtractedPanelCompact(drawn_on, lab_name, rows: list[list[str | None]])` with `EXTRACT_COLUMNS = ("name", "value", "unit", "ref_low", "ref_high", "flag", "page")` declared in the field description and the system prompt. `to_panel(compact) -> ExtractedPanel` converts rows to `RawResult`; a row of the wrong length is a validation error on the structured call, which keeps the existing retry. Everything downstream still sees `ExtractedPanel`.

### 4.6 Web
`build_today` runs its synchronous body through `asyncio.to_thread`. `GET /api/coach/thread?since=N` returns `messages[N:]` plus `total`. The frontend keeps the list, polls with `since=<held count>` while busy, and refetches in full when `total < N`. The default response (no `since`) is unchanged.

### 4.7 `_effort_levels`
Wrapped in `functools.cache` (the argument is a model id string).

## 5. Errors

- A cut cell is never an error; the note tells the model how to read it.
- A corrupt stored `inputs_sha` or payload means no skip: the session is planned as today.
- A gathered sync call that fails fails that source exactly as a sequential failure does: the per-source catch in `run_sync` records it and the other source still runs.
- If trimming would leave no `HumanMessage`, the newest turn is kept whole even over budget.

## 6. Testing

- SQL: a jsonb cell over 1,000 characters is replaced with the marker and named in `note`; numbers are untouched; the 8,000-character cap still applies after cutting.
- Fuel: unchanged inputs mean zero model calls (a scripted model with an empty script proves it) and no upsert; a changed profile field, fuel-log entry or prompt version re-plans; two days run concurrently while one day's caffeine still accumulates in order; output order is unchanged.
- Sync: a fake client that answers out of order still produces rows in date/id order; one failing call fails only its source; at most four calls are in flight.
- Coach: the system prompt is identical across two turns with different context; the context text reaches the model request and is absent from the checkpointed messages; `trim_to_budget` keeps tool pairs, keeps the same cut across calls until another step of growth, and keeps nothing under `high` out.
- Extraction: compact rows convert to the same `ExtractedPanel` as today's fixture; a short row fails validation.
- Web: `since` returns only new messages; `build_today` does not block a concurrent request (a slow fake connection plus a second request that completes first).
- `_effort_levels` builds one `ChatAnthropic` per model id.

## 7. Out of scope

- A `lastModified` watermark for TrainingPeaks, until a live payload shows the field.
- Moving extraction to Sonnet, until Brian runs `TRI_WELLNESS_LIVE_PDF` on the compact schema and on Sonnet.
- Summarizing the coach thread; paginating the web history beyond `since`; async psycopg.
- Parallel race-plan fuel calls (one per event).

## 8. Live checks for Brian

1. `uv run tri sync --since <60 days ago>` before and after item 3: same row counts, shorter time.
2. `TRI_WELLNESS_LIVE_PDF=<panel.pdf> uv run pytest packages/tri-wellness -m live --live` on the compact schema before item 5 merges; optionally again with `LAB_EXTRACT` on Sonnet.
3. Two chat turns on the web after item 4: LangSmith shows cache-read tokens on the second turn's first model call.

## 9. Rollout

One branch, `feat/optimizations`, in this order: `_effort_levels`, SQL cell cap, web, sync, fuel, coach, extraction. The fuel eval (`tri-nutrition eval`) and coach eval (`tri-coach eval`) run once after merge to show no pass-rate change; prompt versions do not bump, because no prompt text changes except the SQL sentence and the extraction column list.
