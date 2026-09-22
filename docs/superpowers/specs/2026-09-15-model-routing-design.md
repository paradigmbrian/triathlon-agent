# Model routing — per-role model, effort and Claude fallback (module `tri_core.llm`)

**Date:** 2026-09-15
**Status:** Draft (amended 2026-09-15 to follow the agent harness spec; amended 2026-09-22 after the harness merged, see §11)
**Prerequisite:** the agent harness spec (`2026-09-15-tri-harness-design.md`, branch `docs/tri-harness-spec`) lands first. Its plans move `make_subagent`, the chat-agent builders, checkpointer setup and the turn drivers into `tri_core.harness`, and leave only `make_model` in each package's `llm.py`. The file and line references in §2 and §5.3 describe `main` @ 3a5a82c, before that move, and are re-checked when plan 01 is written.
**Purpose:** Replace the single `TRI_MODEL` pin with a per-role model registry. Each role (coach, analyst, lab extraction, eval judge, ...) gets its own model, effort, output ceiling and fallback chain, so light work stops paying for heavy settings and an overloaded model no longer fails the turn. Every role launches on today's model; a role moves to a lighter model or effort only when its eval shows it holds quality.

Companion specs: `tri-coach` (2026-09-11) owns `CoachDeps` and the sub-agent wiring this changes; `tri-planning` (2026-09-07), `tri-nutrition` (2026-09-10), `tri-wellness` (2026-09-10) and `tri-analyze` (2026-09-06, alignment 2026-09-13) own the nodes and evals whose models are split out here; `tri-web` (2026-09-14) opens the coach runtime through `make_deps`.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Driver | Right-size per task (chosen 2026-09-15). Resilience is handled simply; quality escalation and per-turn routing are out of scope. | One athlete, one machine: most of the saving is in matching each role to a model and effort once, not deciding per call. |
| Fallback reach | Claude models on the Anthropic API only (chosen 2026-09-15). | Covers overload (529) and model-specific capacity. Other vendors would need provider-neutral history, error handling and per-vendor evals; Bedrock would need AWS credentials. Neither is worth it yet. |
| Sequencing | After the agent harness spec (chosen 2026-09-15). | `claude_fallback` is added once, in the harness's `make_subagent` and `build_chat_agent`, instead of in five package builders. |
| Approach | A static role registry in `tri_core` (approach A, chosen 2026-09-15). No per-turn router. | A thread stays on one model, so the prompt cache (model-scoped) keeps hitting. A router can wrap the registry later. |
| Overrides | Env vars per role through the existing pydantic `Settings` (chosen 2026-09-15). | Same mechanism as every other setting; an eval run can try a candidate with one env var. |
| Launch defaults | Every role starts on `claude-opus-5` at the model's default effort, i.e. today's behaviour. Targets in §6.2 are adopted per role only after an eval passes the gate in §7.2. | Changing a model without a measurement is a guess. |
| Fallback carrier | The chain rides on the `ChatAnthropic` instance as `metadata`; no wrapper model class. | `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")` silently skips anything that is not a `ChatAnthropic`; a wrapper would switch caching off. Fakes and hand-built models carry no `tri_fallbacks` key (every model does carry LangChain's `lc_versions` metadata), so the existing deps constructions in tests are untouched. |

## 2. Feasibility, verified 2026-09-15

- `tri_core/config.py:22` holds `tri_model: str = "claude-opus-5"`. Five copies of `make_model(settings) -> ChatAnthropic` read it: `tri_analyze/llm.py`, and `graph/llm.py` in `tri_coach`, `tri_planning`, `tri_nutrition`, `tri_wellness` (the last with `MAX_TOKENS = 32000`, the rest `16000`). None sets effort, thinking, retries or fallbacks.
- `tri_coach.graph.deps.make_deps(settings, model, servers)` passes the one model to the coach, `analyst_model`, `wellness_model`, `make_planning_deps(...)` and `make_nutrition_deps(...)`. `CoachDeps` already has separate `model`, `analyst_model` and `wellness_model` fields.
- Every model use, by role:
  - coach: `tri_coach/graph/nodes/coach.py:47`; `tri_coach/evals/target.py:112`.
  - analyst: `tri_coach/tools/analyst.py` (`deps.analyst_model`); `tri_analyze/cli.py:93` (chat), `:154` (eval).
  - wellness chat: `tri_coach/tools/wellness.py` (`deps.wellness_model`); `tri_wellness/cli.py:219`.
  - planning agent: `tri_planning/graph/nodes/intake.py:34`, `adjust.py:77`.
  - planning design: `tri_planning/graph/nodes/design.py:43` (`with_structured_output(PlannedWeek)`); `tri_planning/evals/design_eval.py:105` `design_target(deps)`.
  - nutrition agent: `tri_nutrition/graph/nodes/intake.py:41`, `checkin.py:50`.
  - nutrition fuel: `tri_nutrition/graph/nodes/fuel.py:122` `FuelPlanner(deps.model)` (structured `SessionFuel`, `RaceFuelPlan` at `:63`); `tri_nutrition/evals/target.py:70`.
  - lab extract: `tri_wellness/graph/nodes/extract.py:23,26` (`deps.model`) → `labs/extract/structured.py:28`.
  - lab report: `tri_wellness/report.py` `ReportWriter.write` (one `astream` call); `tri_wellness/cli.py:172`, eval `:295`.
  - judge: `make_judge` / `make_brief_judge` / `make_fuel_judge` / the wellness judge, each given the eval's single `model`.
- langchain 1.4.0: `ModelFallbackMiddleware` catches every `Exception` (it re-raises `GraphBubbleUp`), so it would also fall back on a 400. `wrap_model_call` with `request.override(model=...)` is available (the coach's `one_tool_call_at_a_time` already uses the hook).
- langchain-core 1.6.2: `Runnable.with_fallbacks(fallbacks, exceptions_to_handle=...)`. `RunnableWithFallbacks.astream` moves to the next runnable only when the handled error is raised before the first chunk (`fallbacks.py:553-566`); later errors propagate.
- langchain-anthropic 1.7.1: `ChatAnthropic(effort=...)` (alias of `reasoning_effort`) sets `output_config.effort` and, when `thinking` is not set and the profile lists `xhigh`, sends `thinking={"type": "adaptive", "display": "summarized"}` (`chat_models.py:1688-1697`). Profiles: `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5` list `reasoning_effort_levels`; `claude-haiku-4-5` lists none. The profile is computed in a `model_validator(mode="before")`, so a model built with `model_copy` would keep the wrong profile. The key field is `anthropic_api_key: SecretStr`.
- anthropic 1.4.0: 529 raises `OverloadedError`, a sibling of `InternalServerError` (both `APIStatusError`), not a subclass. Also present: `RateLimitError`, `ServiceUnavailableError`, `DeadlineExceededError`, `APIConnectionError` (parent of `APITimeoutError`). The SDK's own `max_retries=2` already retries 408/409/429/5xx and connection errors before any of this runs.
- Evals: `tri-analyze`, `tri-coach`, `tri-nutrition`, `tri-wellness` each have `eval` commands whose `run_eval(settings, model, ...)` uses the one model for target and judge and records `metadata={"model": settings.tri_model}`. `tri-planning` has `evals/design_eval.py` (`build_examples`, `validator_pass`, `design_target`) and a test, but no `eval` command. `planning_agent`, `nutrition_agent`, `wellness_chat` and `lab_extract` have no eval.

## 3. Overview

```
 CLI / tri-web                          tri_core.llm
   models = lambda r: make_model(s, r) ──► resolve(settings, role) ─► ModelSpec(model, effort,
        │                                                              max_tokens, fallbacks)
        ▼                                  make_model ─► ChatAnthropic(metadata={tri_role,
 CoachDeps / GraphDeps (per-role models)                                tri_fallbacks})
        │
        ├─ agents ─ tri_core.harness make_subagent / build_chat_agent ─ middleware: [..., caching, claude_fallback]
        ├─ structured ─ structured(model, Schema) ─ with_structured_output + with_fallbacks
        └─ report stream ─ streaming(model) ─ model.with_fallbacks
                                          all three fall back on RETRYABLE only, via fallbacks_of(model)
```

## 4. Layout

```
packages/tri-core/src/tri_core/
  config.py        Settings: tri_model -> str | None = None; adds tri_model_<role>, tri_effort_<role>,
                   tri_model_fallbacks (§5.2)
  llm.py           NEW: Role, ModelSpec, DEFAULTS, RETRYABLE, resolve, make_model, fallbacks_of,
                   claude_fallback, structured, streaming
packages/tri-core/tests/test_llm.py   NEW
packages/tri-analyze/src/tri_analyze/llm.py       deleted; callers import tri_core.llm
packages/tri-{coach,planning,nutrition,wellness}/src/.../graph/llm.py
                   deleted (after the harness spec they hold only make_model); callers import tri_core.llm
packages/tri-core/src/tri_core/harness/agents.py
                   make_subagent and build_chat_agent append claude_fallback after caching
packages/tri-planning/src/tri_planning/evals/run.py   NEW: run_eval for design_eval
packages/tri-planning/src/tri_planning/cli.py          adds `eval`
packages/tri-planning/pyproject.toml                   adds langsmith>=0.12,<1
scripts/design_eval.py                                 deleted (replaced by `tri-planning eval`)
```

The harness spec already makes `langchain==1.4.0`, `langchain-anthropic==1.7.1` and `anthropic` dependencies of `tri-core`, so this spec adds none.

## 5. Interfaces

### 5.1 `tri_core.llm`

```python
class Role(StrEnum):
    COACH = "coach"
    ANALYST = "analyst"
    WELLNESS_CHAT = "wellness_chat"
    PLANNING_AGENT = "planning_agent"
    PLANNING_DESIGN = "planning_design"
    NUTRITION_AGENT = "nutrition_agent"
    NUTRITION_FUEL = "nutrition_fuel"
    LAB_EXTRACT = "lab_extract"
    LAB_REPORT = "lab_report"
    JUDGE = "judge"

Effort = Literal["low", "medium", "high", "xhigh", "max"]

@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: Effort | None        # None: the model's default (sends nothing)
    max_tokens: int
    fallbacks: tuple[str, ...]

DEFAULTS: dict[Role, ModelSpec]  # §6.2 launch column
STRUCTURED_ROLES: frozenset[Role]  # PLANNING_DESIGN, NUTRITION_FUEL, LAB_EXTRACT, JUDGE
RETRYABLE: tuple[type[BaseException], ...] = (
    RateLimitError, OverloadedError, InternalServerError, ServiceUnavailableError,
    DeadlineExceededError, APIConnectionError,
)
ModelProvider = Callable[[Role], BaseChatModel]

def resolve(settings: Settings, role: Role) -> ModelSpec: ...
def make_model(settings: Settings, role: Role) -> ChatAnthropic: ...
def fallbacks_of(model: BaseChatModel) -> list[ChatAnthropic]: ...
claude_fallback: AgentMiddleware          # an AgentMiddleware subclass with sync and async hooks
def structured(model: BaseChatModel, schema: type[BaseModel]) -> Runnable[LanguageModelInput, Any]: ...
def streaming(model: BaseChatModel) -> Runnable[LanguageModelInput, BaseMessage]: ...
```

### 5.2 Settings

Added to `tri_core.config.Settings`, one pair per `Role` value:

| Env var | Field | Type |
|---|---|---|
| `TRI_MODEL` | `tri_model` | `str \| None = None` (was `"claude-opus-5"`) |
| `TRI_MODEL_<ROLE>` e.g. `TRI_MODEL_ANALYST` | `tri_model_analyst` | `str \| None = None` |
| `TRI_EFFORT_<ROLE>` e.g. `TRI_EFFORT_ANALYST` | `tri_effort_analyst` | `Effort \| None = None` |
| `TRI_MODEL_FALLBACKS` | `tri_model_fallbacks` | `str \| None = None`, comma-separated; `""` disables fallback |

The ten pairs are written out as explicit fields (mypy strict, pydantic validation of `Effort`), not read dynamically.

### 5.3 Deps (additive)

- `tri_planning.graph.deps.GraphDeps` gains `design_model: BaseChatModel | None = None`; `design.py` uses `deps.design_model or deps.model`. `make_deps(settings, model, tp, *, design_model=None)`.
- `tri_nutrition.graph.deps.GraphDeps` gains `fuel_model: BaseChatModel | None = None`; `fuel.py:122` uses `FuelPlanner(deps.fuel_model or deps.model)`. `make_deps(..., *, fuel_model=None)`.
- `tri_wellness.graph.deps.GraphDeps.model` is documented as the lab-extract model; no field change.
- `tri_coach.graph.deps.make_deps(settings, models: ModelProvider, servers, *, today=...)`: `model=models(COACH)`, `analyst_model=models(ANALYST)`, `wellness_model=models(WELLNESS_CHAT)`, planning deps built with `models(PLANNING_AGENT)` and `design_model=models(PLANNING_DESIGN)`, nutrition deps with `models(NUTRITION_AGENT)` and `fuel_model=models(NUTRITION_FUEL)`.
- `tri_web.runtime.open_runtime(settings, *, no_live, log, model=None)` keeps its test override: `models = (lambda _: model) if model else (lambda r: make_model(settings, r))`.
- CLI call sites pass a role (lines as of `main` @ b4c7efa): `tri_analyze/cli.py:93,154` → `ANALYST` (eval via §7.1); `tri_coach/cli.py:93` → `models` provider, `:302` via §7.1; `tri_planning/cli.py:81` → `PLANNING_AGENT` with `design_model=PLANNING_DESIGN`; `tri_nutrition/cli.py:134,300` → `NUTRITION_AGENT` with `fuel_model=NUTRITION_FUEL`, `:248` (`today`, no model call) → `NUTRITION_AGENT`, `:334` via §7.1; `tri_wellness/cli.py:126` → `LAB_EXTRACT`, `:173` → `LAB_REPORT`, `:220` → `WELLNESS_CHAT`, `:296` via §7.1. Also: `scripts/design_eval.py` → `PLANNING_DESIGN` (until plan 02 replaces it), and the opt-in live tests `tri-coach/tests/test_live.py` (provider) and `tri-wellness/tests/test_live_pdf.py` (`LAB_EXTRACT`).
- `CoachDeps`, `tri_coach.testing.make_test_deps` and every test fixture keep their current signatures. The two tests in `tri-coach/tests/test_servers.py` that call the real coach `make_deps` pass `lambda _: model` as the provider; their assertions do not change.

## 6. Behaviour

### 6.1 Resolution

`resolve(settings, role)`:

1. `model` = `tri_model_<role>` or `tri_model` or `DEFAULTS[role].model`.
2. `effort` = `tri_effort_<role>` or `DEFAULTS[role].effort`. A per-role model override does not reset effort; set both when trying a candidate.
3. `max_tokens` = `DEFAULTS[role].max_tokens` (16000; 32000 for `lab_extract` and `lab_report`). Not env-overridable.
4. `fallbacks` = parsed `tri_model_fallbacks` when set (empty string → `()`), else the first two of `("claude-opus-5", "claude-opus-4-8", "claude-sonnet-5")` that differ from `model`. The primary is removed from any list.
5. Validation: when `effort` is set on a role in `STRUCTURED_ROLES`, raise `ValueError("TRI_EFFORT_<ROLE>=<effort> is not allowed: <role> runs structured output, which cannot use thinking")`. Otherwise, when `effort` is set and the model's profile (`_PROFILES` via `ChatAnthropic(model=...).profile`) does not list it, raise `ValueError("TRI_EFFORT_<ROLE>=<effort> is not supported by <model>")`. A model with no profile entry is accepted with `effort=None` only.

   Why structured roles take no effort: an effort level on Opus 5, Opus 4.8 or Sonnet 5 turns on adaptive thinking, and `with_structured_output` (default `method="function_calling"`) forces the tool choice, which the API rejects when thinking is on (a 400). Moving these roles to `method="json_schema"`, which allows both, is a separate, measured change and out of scope here.

`make_model` raises at construction, so a bad override fails when the CLI or server starts, before any turn.

`make_model(settings, role)` returns `ChatAnthropic(model=spec.model, max_tokens=spec.max_tokens, api_key=settings.anthropic_api_key, effort=spec.effort, metadata={"tri_role": role.value, "tri_fallbacks": list(spec.fallbacks)})`.

### 6.2 Defaults and targets

| Role | Launch default | Target (adopt only after §7.2) | Gate |
|---|---|---|---|
| `coach` | opus-5 / default | candidate opus-5 / high (an explicit effort also sends `thinking: adaptive`, which today's request omits; whether that matches the API default is what the eval decides) | `tri-coach eval` |
| `planning_agent` | opus-5 / default | unchanged | none |
| `planning_design` | opus-5 / default | unchanged (structured: no effort) | `tri-planning eval` (§7.1) |
| `lab_report` | opus-5 / default | unchanged | `tri-wellness eval` |
| `analyst` | opus-5 / default | opus-5 / medium, candidate sonnet-5 / medium | `tri-analyze eval` |
| `wellness_chat` | opus-5 / default | candidate opus-5 / medium | none |
| `lab_extract` | opus-5 / default | candidate sonnet-5 (structured: no effort) | none (manual: `TRI_WELLNESS_LIVE_PDF` test) |
| `nutrition_agent` | opus-5 / default | candidate sonnet-5 / medium | none |
| `nutrition_fuel` | opus-5 / default | sonnet-5 (structured: no effort) | `tri-nutrition eval` |
| `judge` | opus-5 / default | never tuned | — |

Roles with no gate stay on the launch default unless the athlete sets an env override. `judge` is held fixed so experiments across candidates stay comparable.

### 6.3 Fallback

`fallbacks_of(model)` returns `[]` unless `model` is a `ChatAnthropic` whose `metadata` carries `tri_fallbacks`. Otherwise each id becomes a fresh `ChatAnthropic(model=id, max_tokens=model.max_tokens, api_key=model.anthropic_api_key, effort=e, metadata={"tri_role": role, "tri_fallback_from": model.model})`, built with the constructor so the fallback's profile is its own. `e` is `None` for a role in `STRUCTURED_ROLES`; otherwise the primary's effort when the fallback's profile lists it; else `"high"` when the fallback lists any levels (so Opus 4.8 runs with adaptive thinking, which it would not by default); else `None`.

- **Agents.** `claude_fallback` is an `AgentMiddleware` subclass instance with both `wrap_model_call` and `awrap_model_call` (the `@wrap_model_call` decorator only builds one of the two). It calls `handler(request)`; on an error in `RETRYABLE` it tries `handler(request.override(model=fb))` for each `fb` in `fallbacks_of(request.model)`, in order. `GraphBubbleUp` and any other exception propagate immediately. When every model fails, the last error is raised. Middleware order puts it just before `AnthropicPromptCachingMiddleware`, which stays last as the harness requires: caching then marks the request for whichever Claude model the fallback chose, and `one_tool_call_at_a_time`'s `model_settings` travel with the overridden request. Added once, in `tri_core.harness.agents` (`make_subagent` and `build_chat_agent`), which imports it from `tri_core.llm`. After the harness spec every agent goes through one of those two builders: the coach, planning and nutrition nodes, `tri_analyze.agent.build_agent`, wellness chat, `ask_analyst` and `ask_wellness`.
- **Structured output.** `structured(model, schema)` is `model.with_structured_output(schema)` plus `.with_fallbacks([fb.with_structured_output(schema) for fb in fallbacks_of(model)], exceptions_to_handle=RETRYABLE)` when there are fallbacks. Replaces the direct calls in planning `design.py:43`, nutrition `fuel.py:63-64`, wellness `structured.py:28` and the three judges (`make_judge`, `make_brief_judge`, `make_fuel_judge`; wellness's evaluators use no model). When every model fails, `RunnableWithFallbacks` raises the primary's error.
- **Streaming.** `streaming(model)` is `model.with_fallbacks([...], exceptions_to_handle=RETRYABLE)`; `ReportWriter` streams through it. A failure after the first chunk surfaces as today (the athlete reruns `tri-wellness report`). When every model fails, the primary's error is raised.
- **Visibility.** Each fallback attempt logs `WARNING tri_core.llm: <role> fell back from <primary> to <fallback> after <ErrorClass>`. `structured` and `streaming` log the same line without `after <ErrorClass>`, since `with_fallbacks` does not pass the error on. The fallback model's `metadata` marks its LangSmith run with `tri_fallback_from`. REPL and web error messages are unchanged and now appear only when the whole chain has failed.

### 6.4 Errors

- A 400, 401, 403, 404 or 413 never falls back.
- An invalid override raises `ValueError` from `make_model` when the CLI or server builds its models (§6.1 step 5), before any model call. It is not caught.
- A thread whose earlier turns ran on a different model continues normally: Claude models accept each other's history, and thinking blocks from another model are dropped by the API.
- In an agent, `claude_fallback` wraps the whole model call while the REPL and web stream tokens through callbacks as they arrive. A RETRYABLE error after the first token (a dropped connection, in practice) reruns the call on the fallback, so the athlete may see the partial answer twice. Accepted for one athlete; the primary's SDK retries and the rarity of mid-stream errors keep it uncommon.

## 7. Evals and tuning

### 7.1 Eval wiring

- Each `run_eval` takes `models: ModelProvider` instead of one model: the target uses its role (`analyst`, `coach`, `nutrition_fuel`, `lab_report`), the judge uses `judge`. `tri-wellness` has no judge, so its `run_eval` only resolves `lab_report`.
- `metadata` records `{"model": <target spec.model>, "effort": <target spec.effort>}` from `resolve`, replacing `settings.tri_model`, plus `"judge_model": <judge spec.model>` when a judge runs.
- `tri-planning eval [--prefix] [--recreate-dataset]` is new and replaces `scripts/design_eval.py`, which is deleted: the LangSmith dataset keeps the script's name, `tri-planning-design-weeks`, so earlier experiments stay comparable. It is built from `build_examples(today)`, the target is `design_target(deps)` with `design_model=models(PLANNING_DESIGN)`, the evaluator is `validator_pass`, and the `ensure_dataset` / `pass_rates` / `render_pass_rates` shape matches the siblings (tri_planning has no `PROMPT_VERSION`, so the default experiment prefix is `design`). `langsmith>=0.12,<1` is added to `tri-planning`'s dependencies. Exits 2 without `ANTHROPIC_API_KEY` or `LANGSMITH_API_KEY`.

### 7.2 Tuning procedure and gate

Run by the athlete (every run costs API money):

1. Baseline on launch defaults: `uv run tri-analyze eval --prefix analyst-base`.
2. Candidate: `TRI_MODEL_ANALYST=claude-sonnet-5 TRI_EFFORT_ANALYST=medium uv run tri-analyze eval --prefix analyst-sonnet5-med`.
3. Gate: adopt only if no evaluator key's passing count drops by more than one example against the baseline and the errored count does not rise.
4. Adoption is a one-line `DEFAULTS` change whose commit message names both experiments.

## 8. Testing

New `packages/tri-core/tests/test_llm.py`, no network:

- `resolve`: role override beats `TRI_MODEL` beats default; effort override; `TRI_MODEL_FALLBACKS` parsing, `""` → `()`, primary removed; default chain for opus-5, sonnet-5, haiku-4-5.
- Validation: `TRI_MODEL_ANALYST=claude-haiku-4-5` with `TRI_EFFORT_ANALYST=low` raises naming the env var; haiku with no effort passes; an effort on any structured role raises.
- `make_model`: model id, `max_tokens` (32000 for lab roles), effort, metadata.
- `fallbacks_of`: `[]` for `ScriptedChatModel` and for a `ChatAnthropic` without `tri_fallbacks`; ids, effort mapping (primary effort kept when listed; `"high"` for Opus 4.8 when primary is `None`; `None` for haiku; `None` on every structured role), `tri_fallback_from` set.
- `claude_fallback` with a fake handler: `OverloadedError` → second model answers; `BadRequestError` → raised, no second call; `GraphBubbleUp` → propagated; all fail → last error raised; no fallbacks → original error.
- `structured` and `streaming` over fake runnables: retryable error before first chunk falls back; non-retryable does not; all fail → the primary's error.
- `tri-core/tests/test_config.py`: `tri_model` default is `None`; per-role fields read from env.

Existing suites (`uv run pytest`), `uv run ruff check`, `uv run mypy` pass without changes to test deps constructors. `tri-analyze/tests/test_llm.py` moves to `tri-core` as a `make_model` case. `tri-planning` gains `tests/test_cli.py` with a test for `eval` exiting 2 without keys. `tri-core/tests/test_harness_agents.py` expects `[..., claude_fallback, caching]`.

## 9. Out of scope

- Per-turn or per-call routing (a classifier or heuristic router); it can wrap `make_model` later.
- Escalation to a heavier model on validation failure.
- Fallback to Bedrock, Vertex or non-Anthropic vendors.
- Server-side refusal `fallbacks` (the API's `server-side-fallback` beta): no refusal has been seen in this app's traffic.
- Adding evals for the four ungated roles.
- Mid-conversation effort changes.

## 10. Rollout

1. **Plan 01, registry and fallback.** Starts after harness plan 04 is merged. `tri_core.llm`, settings, deps wiring, the five `make_model` copies removed, fallback middleware and helpers, tests. Behaviour change: fallback only; every role still resolves to opus-5.
2. **Plan 02, eval wiring and tuning.** `run_eval` per role, `tri-planning eval`, metadata; then the §7.2 runs (athlete-run), and one commit per adopted default.

Docs in plan 01: `.env.example` replaces `TRI_MODEL=claude-opus-5` with a commented block listing `TRI_MODEL`, `TRI_MODEL_<ROLE>`, `TRI_EFFORT_<ROLE>`, `TRI_MODEL_FALLBACKS`; `packages/tri-analyze/README.md:189` points at those vars and `tri_core/llm.py`. The athlete removes `TRI_MODEL` from their own `.env`, or every role stays pinned to it. Earlier specs are left as written.

## 11. Amendments 2026-09-22

Re-checked against `main` @ b4c7efa, after all four harness plans merged. Decisions by the athlete:

1. **Fallback sits just before caching.** `claude_fallback` goes in as `[*middleware, claude_fallback, caching]`, keeping the harness rule that prompt caching is the last middleware (§6.3).
2. **Structured roles take no effort.** Effort turns on thinking, and thinking cannot be combined with the forced tool choice `with_structured_output` uses. `planning_design`, `nutrition_fuel`, `lab_extract` and `judge` refuse an effort override, and their fallbacks run without one (§6.1, §6.2, §6.3).
3. **`tri-planning eval` replaces `scripts/design_eval.py`** and keeps its dataset name `tri-planning-design-weeks` (§7.1).

Corrections from the re-check: three judges, not four (wellness has none); `RunnableWithFallbacks` raises the primary's error when every model fails; the `@wrap_model_call` decorator builds only one hook, so `claude_fallback` is a subclass; every model carries `lc_versions` metadata; the §5.3 line numbers, and the callers the first draft missed (`scripts/design_eval.py`, two opt-in live tests), are updated in place.
