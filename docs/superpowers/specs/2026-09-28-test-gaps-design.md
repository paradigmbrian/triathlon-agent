# Test gaps: judges checked against labels, fallback through a real agent loop, a web e2e on the real backend

**Date:** 2026-09-28
**Status:** Draft
**Purpose:** Close the test gaps from `docs/notes/2026-09-24-codebase-review.md` that the round-one plans left open, so the eval baselines and the model-routing gate can be trusted. One of three round-two specs, alongside `2026-09-28-optimizations-design.md` and `2026-09-28-features-design.md`; independent of both. Line numbers are `fix/eval-followups` @ 0c096ca.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Calibration scope | The three LLM judges: analyst `FeedbackJudgement`, coach `BriefJudgement`, nutrition `FuelJudgement`. Wellness and planning have code evaluators only. | Every tuning decision rests on these three; nobody has measured them against a known answer. |
| Who labels | Claude drafts calibration labels, Brian confirms them in one pass (chosen 2026-09-28). | Brian's judgement is the ground truth; drafting from real outputs keeps his pass short. |
| Pass bar | Per judge, the verdict agrees with the label on at least 11 of 12 cases, and never passes a case labelled as a critical failure. | One disagreement is noise at this size; a false pass on an invented number is the exact failure the judges exist to catch. |
| Fallback test | A fake model that raises a chosen error, driven through a real `make_subagent` loop. | The middleware is tested only with a hand-built request (`tri-core/tests/test_llm.py:181-263`), never inside `create_agent`. |
| Web e2e | A test-only server entrypoint, not a flag on `tri-web serve`. | A production command that can swap in scripted models is a foot-gun. |
| Database for e2e | The test database through one connection that never commits. | Nothing persists between runs and nothing can reach the athlete's database. |

## 2. Feasibility, verified 2026-09-28

- Judges: `make_judge` (`tri_analyze/evals/evaluators.py:173`, schema `:109`, fields `grounded`, `covers_rules`, `uses_athlete_comments`, `concrete_takeaways`, `no_generic_encouragement`, `problems`); `make_brief_judge` (`tri_coach/evals/evaluators.py:92`, schema `:48`, fields `bounded`, `names_signal`, `names_lever`, `names_constraint`, `grounded`, `problems`); `make_fuel_judge` (`tri_nutrition/evals/evaluators.py:105`, schema `:53`, fields `respects_restrictions`, `only_library_products`, `problems`). Each is an `AsyncEvaluator(inputs, outputs)` on `Role.JUDGE`. All tests script the verdict with `ScriptedChatModel`.
- `--live` is registered in the root `conftest.py:25-37`; items marked `live` skip without it. CI allows only `needs --live` skips (`.github/workflows/ci.yml:51-58`).
- Bought-plan reject: `test_reject_on_a_bought_plan_ends_clean_and_the_next_message_reaches_adjust` (`tri-planning/tests/test_graph.py:131-161`) already covers the graph ending clean and `tp_apply_training_plan` never running. It does not check the database straight after the reject: that no plan row exists and that `tp_plan_applied_at` is still null (`tri_planning/repo.py:58,95`).
- Fallback: `ClaudeFallbackMiddleware` (`tri_core/llm.py:201-230`) calls the module-level `fallbacks_of(request.model)` (`:155-186`). `fallbacks_of` returns `[]` for anything that is not a `ChatAnthropic` built by `make_model`, so a test injects its fallback by monkeypatching `tri_core.llm.fallbacks_of`. `make_subagent` (`tri_core/harness/agents.py:42-61`) appends `claude_fallback` and caching. `ScriptedChatModel` (`tri_core/testing/fakes.py:15-62`) raises only `IndexError` when its script runs out.
- Web: `tests/conftest.py:40-74` (tri-web) builds a `Runtime` from `make_test_deps` with scripted models, `InMemorySaver`, `InMemoryStore` and a `NoCommit` connection (`tri_planning/testing.py:112`). `create_app` mounts `web/dist` when built (`tri_web/app.py:74-90`). `web/playwright.config.ts` runs `vite preview` and `tests/e2e/smoke.spec.ts` stubs every `/api` route. CI never runs Playwright.

## 3. Layout

```
packages/tri-{analyze,coach,nutrition}/src/*/evals/calibration.py   NEW: labelled cases
packages/tri-{analyze,coach,nutrition}/tests/test_calibration.py     NEW: live agreement test
packages/tri-core/src/tri_core/evals.py              agreement_table (NEW function)
packages/tri-core/src/tri_core/testing/fakes.py      RaisingChatModel (NEW)
packages/tri-core/tests/test_harness_agents.py       fallback through make_subagent
packages/tri-planning/tests/test_graph.py            repo-state assertions after reject
packages/tri-web/src/tri_web/e2e_server.py           NEW: test-only entrypoint
web/playwright.real.config.ts, web/tests/e2e-real/review.spec.ts    NEW
.github/workflows/ci.yml                             e2e job
```

## 4. Items

### 4.1 Judge calibration

A case is the judge's `inputs` and `outputs` exactly as the eval target produces them, plus the label:

```python
@dataclass(frozen=True)
class CalibrationCase:
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    expected: dict[str, bool]   # every boolean field of the judge's schema
    critical: bool              # a false pass here fails the test outright
    reason: str                 # one line: why the label is what it is
```

Cases drawn from a baseline run come from its local results file, `.evals/<experiment>.jsonl` (commit 5091b93). That file holds each example's inputs, outputs and judge comments. The LangSmith copy isn't used: the monthly trace limit dropped every trace of `analyst-v2-base-0c882dd5` on 2026-09-28.

Twelve cases per judge:
- **Analyst:** 4 clean answers from `analyst-v2-base`; 3 with derived numbers, two showing the arithmetic and one not; 2 with an invented number (critical); 1 stating missing data correctly; 2 missing a rule or ignoring an athlete comment.
- **Coach:** 4 clean briefs from `coach-v4-base`; 2 citing a number found only in a served answer, both grounded; 2 with an invented number, date or lab value (critical); 2 unbounded ("review the plan"); 2 missing signal, lever or constraint.
- **Fuel:** 4 clean notes from the latest `fuel-v4` experiment; 3 breaking a restriction, such as a vegan note naming whey or a gluten note naming oats (critical); 3 naming an off-library product (critical); 2 with plain food and water only, which must pass `only_library_products`.

The agreement test is marked `live`, skips without `ANTHROPIC_API_KEY`, and runs each judge on `make_model(settings, Role.JUDGE)`.
- `tri_core.evals.agreement_table(rows)` prints one line per case: the name, then each field as expected and got, marked `ok` or `MISMATCH`.
- It then prints per-field agreement as `grounded 11/12`.
- The test asserts the whole-case agreement bar from §1 and no false pass on a `critical` case.

Label review: the plan's first task writes the three `calibration.py` files. Every label is marked as drafted, and each `reason` says what Claude judged. Brian confirms or corrects each label before the test file is committed.

### 4.2 Bought-plan reject

In the existing test, straight after the reject and before the test inserts its own plan, assert two things. `repo.derive_phase(nocommit)` returns `("planning", gid, None)`, so no plan row was written. `repo.get_active_goal(nocommit).tp_plan_applied_at is None`. No new test.

### 4.3 Fallback through a real agent loop

- `RaisingChatModel(ScriptedChatModel)` allows a script entry to be an exception instance, which is raised in place of a message, from both `_generate` and `_stream`.
- The test scripts the primary as `[OverloadedError]` and a fallback `ScriptedChatModel` as `[tool_call("echo", …), AIMessage("done")]`, then monkeypatches `tri_core.llm.fallbacks_of` to return `[fallback]`.
- It runs `make_subagent(primary, [echo], "…").ainvoke(...)` and asserts four things: the final message is `done`, `echo` ran, the fallback took both calls, and the primary took one.
- A second test raises `BadRequestError` and asserts it propagates without the fallback being called.

### 4.4 Web e2e on the real backend

`tri_web/e2e_server.py` is run as `uv run python -m tri_web.e2e_server --port 4174`.
- It refuses to start unless `TEST_DATABASE_URL` is set and differs from `DATABASE_URL`.
- It opens one connection to the test database, wraps it in `NoCommit`, and builds the same `Runtime` as the tri-web conftest. Scripted coach and planning models run a fixed script: a streamed answer, then a planning consult that pauses on a review.
- It serves `create_app(rt)` with the built `web/dist`.
- Nothing is committed, so the connection's transaction rolls back when the process exits and every run starts clean. It lives under `src` so the test run can import it; it is not a console script.

`web/playwright.real.config.ts` has its own `webServer`: `npm run build && uv run --project .. python -m tri_web.e2e_server --port 4174`, with `reuseExistingServer: false`. `tests/e2e-real/review.spec.ts` is one test:
1. Type a message and see the streamed answer.
2. See the review gate, with the composer disabled and its hint shown.
3. Click Approve and see the report message. The gate then disappears.

`npm run test:e2e:real` runs it. The stubbed smoke spec stays as it is.

CI adds an `e2e` job:
1. Start the Postgres service, `uv sync --locked`, create the test database and run `uv run tri migrate --test`.
2. `npm ci`, then `npx playwright install --with-deps chromium`.
3. Run `npm run test:e2e` and `npm run test:e2e:real`.
4. Upload the Playwright report when the job fails.

## 5. Errors

- A calibration case whose `expected` lacks a boolean field of the judge's schema fails at import, through a `__post_init__` check.
- The e2e server exits 2, with a message, when the test database is unset, is the athlete's database, or is unreachable.
- `RaisingChatModel` raises `IndexError` when its script runs out, like `ScriptedChatModel`.

## 6. Testing

- Unit, not live:
  - `agreement_table` formats and counts correctly;
  - each `calibration.py` covers every boolean field, and its case mix matches §4.1;
  - `RaisingChatModel` raises and replays.
- Live: the three agreement tests, run by Brian with `uv run pytest -m live --live packages/tri-{analyze,coach,nutrition}/tests/test_calibration.py`.
- e2e: both Playwright configs pass locally and in CI.

## 7. Out of scope

Tuning any judge's prompt, which is a separate decision once the agreement numbers are in. More than twelve cases per judge. Code evaluators in wellness and planning. Real MCP servers in e2e. Multi-browser e2e.

## 8. Rollout

1. The calibration files land with drafted labels. Brian reviews and corrects them, and only then is `test_calibration.py` committed.
2. Brian runs the live agreement tests and records the three agreement tables in `docs/notes/`.
3. If a judge misses the bar, a follow-up spec decides between a judge prompt change and a model change. That comparison uses the calibration set, not the eval baselines.
4. The e2e job lands as required in CI once it has passed on `main` three times in a row.
5. Locally, the real-backend e2e, `tri-analyze eval` and `pytest` share the test database. Run one at a time. The e2e server's open transaction and the eval's seeded rows both make database tests fail while they last, as happened on 2026-09-28. The README sections for both commands say so.
