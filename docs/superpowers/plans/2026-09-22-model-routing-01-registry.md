# Model routing Plan 1 of 2: Role registry and Claude fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `TRI_MODEL` pin with a per-role model registry in `tri_core.llm`, route every model construction through it, and retry an overloaded or unavailable model call on the next Claude model, with no other change in behaviour: every role still runs `claude-opus-5` at its default effort.

**Architecture:** `tri_core.llm` holds the `Role` enum, one `ModelSpec` per role, `resolve` (env overrides over defaults), `make_model` (a `ChatAnthropic` carrying its role and fallback chain as metadata), and three fallback carriers: the `claude_fallback` agent middleware (added once, in the harness builders, just before prompt caching), `structured()` for structured-output calls and `streaming()` for the lab report stream. The five package `make_model` copies are deleted; planning and nutrition deps gain an optional design/fuel model; the coach's `make_deps` takes a role → model provider.

**Tech Stack:** Python 3.12, uv workspace, langchain 1.4.0 (`AgentMiddleware`), langchain-core 1.6.2 (`Runnable.with_fallbacks`, `RunnableLambda`), langchain-anthropic 1.7.1 (`ChatAnthropic(effort=...)`, model profiles), anthropic 1.4.0 (error classes), pydantic-settings, pytest with `pytest-asyncio` in auto mode, `tri_core.testing.ScriptedChatModel`.

**Spec:** `docs/superpowers/specs/2026-09-15-model-routing-design.md`, as amended 2026-09-22 (§11). This plan implements §4, §5, §6, §8 and the plan 01 docs in §10. Plan 02 (`2026-09-22-model-routing-02-evals.md`) does the eval wiring in §7.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-routing-01 -b feat/model-routing-01 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout. First confirm this plan and the amended spec are on `main`: `grep -c "Amendments 2026-09-22" docs/superpowers/specs/2026-09-15-model-routing-design.md` prints `1`.
- **Baseline B:** run `uv run pytest -q` before Task 1. On `main` @ b4c7efa it is `948 passed, 6 skipped, 1 warning`. If it differs, record the actual number and shift every expected count below by the same amount.
- **No behaviour change except fallback.** `DEFAULTS` puts every role on `claude-opus-5` with `effort=None` and today's output ceilings (16000; 32000 for `lab_extract` and `lab_report`). Terminal output, error sentences and tool descriptions stay byte-identical.
- **Structured roles never send an effort.** `planning_design`, `nutrition_fuel`, `lab_extract` and `judge` run `with_structured_output`, which forces a tool choice the API rejects when thinking is on; any effort turns thinking on (spec §6.1 step 5).
- **Middleware order:** `[*middleware, claude_fallback, caching]`. Prompt caching stays the last middleware.
- **`claude_fallback` is an `AgentMiddleware` subclass instance with both `wrap_model_call` and `awrap_model_call`.** The `@wrap_model_call` decorator builds only one of the two.
- **Every model carries `metadata["lc_versions"]`** (LangChain adds it). Tests check the `tri_role` / `tri_fallbacks` / `tri_fallback_from` keys, never the whole dict.
- **Errors:** `claude_fallback` raises the last error when every model fails; `structured()` and `streaming()` (built on `with_fallbacks`) raise the primary's error.
- **Test rules:** fixtures and `make_test_deps` keep their signatures. Assertions change only where this plan says so: `tri-core/tests/test_config.py` (the `tri_model` default) and `tri-core/tests/test_harness_agents.py` (the middleware list). `tri-coach/tests/test_servers.py` changes only the argument it passes to `make_deps`.
- **Files this plan may touch:**
  - `packages/tri-core/src/tri_core/{config.py,llm.py,harness/agents.py}`, `packages/tri-core/tests/{test_config.py,test_llm.py,test_harness_agents.py}`, `packages/tri-core/README.md`
  - `packages/tri-analyze/src/tri_analyze/{llm.py (deleted),cli.py,evals/run.py,evals/evaluators.py}`, `packages/tri-analyze/tests/test_llm.py` (deleted), `packages/tri-analyze/README.md`
  - `packages/tri-coach/src/tri_coach/{graph/llm.py (deleted),graph/deps.py,cli.py,evals/run.py,evals/evaluators.py}`, `packages/tri-coach/tests/{test_servers.py,test_live.py}`
  - `packages/tri-planning/src/tri_planning/{graph/llm.py (deleted),graph/deps.py,graph/nodes/design.py,cli.py}`, `packages/tri-planning/tests/test_design_node.py`, `packages/tri-planning/README.md`
  - `packages/tri-nutrition/src/tri_nutrition/{graph/llm.py (deleted),graph/deps.py,graph/nodes/fuel.py,cli.py,evals/run.py,evals/evaluators.py}`, `packages/tri-nutrition/tests/test_fuel_node.py`
  - `packages/tri-wellness/src/tri_wellness/{graph/llm.py (deleted),labs/extract/structured.py,report.py,cli.py,evals/run.py}`, `packages/tri-wellness/tests/{test_report.py,test_extract.py,test_live_pdf.py}`
  - `packages/tri-web/src/tri_web/runtime.py`
  - `scripts/design_eval.py`, `.env.example`
  - `docs/architecture/harness.md`, `docs/architecture/harness/{layers.svg,packages.svg}`
- **Definition of done per task, in order:**
  1. `uv run ruff format packages scripts`
  2. `uv run ruff check --fix packages scripts`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing langsmith `DeprecationWarning`. `ruff check --fix` may reorder the import lines shown below; accept its order. Never add `# type: ignore`.
- **Commits:** git commits are permitted (Brian's standing permission). Commit once per task on `feat/model-routing-01`, ending every message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file edited is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs). The two SVGs are copied alongside `harness.md` there too.

### Facts verified while writing this plan (against `main` @ b4c7efa, 2026-09-22)

1. The five `llm.py` files (`tri_analyze/llm.py`, and `graph/llm.py` in `tri_coach`, `tri_planning`, `tri_nutrition`, `tri_wellness`) each hold only `MAX_TOKENS` (16000; 32000 in wellness) and `make_model(settings) -> ChatAnthropic` reading `settings.tri_model`. `MAX_TOKENS` is imported only by `tri-analyze/tests/test_llm.py`.
2. `settings.tri_model` is read by those five files and by the four eval `run.py` metadata dicts (analyze `:83`, coach `:71`, nutrition `:78`, wellness `:79`).
3. `make_model` callers: `tri_analyze/cli.py:60,93,143,154`; `tri_coach/cli.py:78,93,291,302`; `tri_web/runtime.py:57,71`; `tri-coach/tests/test_live.py:14,30`; `tri_planning/cli.py:48,81`; `scripts/design_eval.py:22,45`; `tri_nutrition/cli.py:118,134,228,248,282,300,323,334`; `tri_wellness/cli.py:97,126,163,173,195,220,285,296`; `tri-wellness/tests/test_live_pdf.py:16,30`. No other `ChatAnthropic(` construction exists.
4. `with_structured_output` is called at `tri_planning/graph/nodes/design.py:43`, `tri_nutrition/graph/nodes/fuel.py:63,64`, `tri_wellness/labs/extract/structured.py:28`, and the three judges: `tri_analyze/evals/evaluators.py:163`, `tri_coach/evals/evaluators.py:72`, `tri_nutrition/evals/evaluators.py:105`. All use the default `method="function_calling"`.
5. `tri_coach.graph.deps.make_deps(settings, model, servers, *, today)` is called by `tri_coach/cli.py:93`, `tri_web/runtime.py:71`, `tri-coach/tests/test_live.py:30` and `tri-coach/tests/test_servers.py:119,131,134`. The test fixtures build `CoachDeps` through `make_test_deps` and never call it.
6. Library behaviour this plan relies on, checked in the installed packages: `ModelRequest` has `.model` and `.override(model=...)`; the agent binds tools from `request.model` on every call; `ChatAnthropic(effort=...)` adds adaptive thinking on models whose profile lists `xhigh` (Opus 5, Opus 4.8, Sonnet 5; Haiku 4.5 lists no levels); `ChatAnthropic(model=id).profile` is built by the constructor, so a fallback built with the constructor gets its own profile; `RunnableWithFallbacks` moves on only for listed exceptions and, in `astream`, only before the first chunk; anthropic 1.4.0 raises `OverloadedError` for 529 and `InternalServerError` for other 5xx.
7. The code in Tasks 2–4 was prototyped against `main` @ b4c7efa: the 26 `test_llm.py` tests pass, `mypy` is clean, and wiring `claude_fallback` into the harness builders keeps every existing agent test green.

### Stop conditions

Stop and report to Brian without working around it if:
- an existing assertion outside the three test files named in "Test rules" fails;
- `mypy` rejects `claude_fallback` as a middleware, or `Settings` rejects a field;
- a grep in Task 8 finds a `make_model` or `tri_model` reader this plan does not list.

---

## File Structure

```
packages/tri-core/src/tri_core/
  config.py              Task 1: Effort; tri_model -> None; per-role model/effort; fallbacks
  llm.py                 Task 2: Role, ModelSpec, DEFAULTS, STRUCTURED_ROLES, RETRYABLE, resolve,
                                 make_model, fallbacks_of
                         Task 3: ClaudeFallbackMiddleware, claude_fallback
                         Task 4: structured, streaming
  harness/agents.py      Task 3: claude_fallback before caching
packages/tri-core/tests/
  test_config.py         Task 1
  test_llm.py            Tasks 2-4
  test_harness_agents.py Task 3
packages/tri-planning    Task 5: GraphDeps.design_model; design.py via structured()
packages/tri-nutrition   Task 5: GraphDeps.fuel_model; FuelPlanner via structured()
packages/tri-wellness    Task 6: extraction via structured(); ReportWriter via streaming()
three judges             Task 6: via structured()
every make_model caller  Task 7: tri_core.llm.make_model(settings, role); coach make_deps
                                 takes a provider; five llm.py deleted
docs                     Task 8: .env.example, READMEs, harness map
```

---

### Task 1: Per-role settings

**Files:**
- Modify: `packages/tri-core/src/tri_core/config.py`
- Test: `packages/tri-core/tests/test_config.py`

**Interfaces:**
- Produces: `tri_core.config.Effort = Literal["low", "medium", "high", "xhigh", "max"]`; `Settings.tri_model: str | None = None`; `Settings.tri_model_fallbacks: str | None = None`; for each role value `r` in `coach, analyst, wellness_chat, planning_agent, planning_design, nutrition_agent, nutrition_fuel, lab_extract, lab_report, judge`: `Settings.tri_model_<r>: str | None = None` and `Settings.tri_effort_<r>: Effort | None = None`.

- [ ] **Step 1: Record the baseline**

Run: `uv run pytest -q`
Expected: `948 passed, 6 skipped, 1 warning` (write down B).

- [ ] **Step 2: Write the failing tests**

In `packages/tri-core/tests/test_config.py`, replace line 20:

```python
    assert s.tri_model == "claude-opus-5"
```

with:

```python
    assert s.tri_model is None
```

Add these imports at the top of the file (ruff sorts them):

```python
import pytest
from pydantic import ValidationError
```

and append:

```python
def test_model_routing_fields_read_from_env(monkeypatch):
    monkeypatch.setenv("TRI_MODEL_ANALYST", "claude-sonnet-5")
    monkeypatch.setenv("TRI_EFFORT_ANALYST", "medium")
    monkeypatch.setenv("TRI_MODEL_FALLBACKS", "")
    monkeypatch.delenv("TRI_MODEL_COACH", raising=False)
    monkeypatch.delenv("TRI_EFFORT_JUDGE", raising=False)
    s = Settings(_env_file=None)
    assert s.tri_model_analyst == "claude-sonnet-5" and s.tri_effort_analyst == "medium"
    assert s.tri_model_fallbacks == ""
    assert s.tri_model_coach is None and s.tri_effort_judge is None


def test_an_unknown_effort_is_rejected(monkeypatch):
    monkeypatch.setenv("TRI_EFFORT_COACH", "extreme")
    with pytest.raises(ValidationError, match="tri_effort_coach"):
        Settings(_env_file=None)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_config.py -v`
Expected: `test_defaults_when_env_empty` fails (`'claude-opus-5' is not None`), `test_model_routing_fields_read_from_env` fails (`AttributeError ... tri_model_analyst`), `test_an_unknown_effort_is_rejected` fails (`DID NOT RAISE`).

- [ ] **Step 4: Write the implementation**

In `packages/tri-core/src/tri_core/config.py`, replace:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
```

with:

```python
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
```

and replace:

```python
    tri_model: str = "claude-opus-5"
```

with:

```python
    # Model routing (tri_core.llm). TRI_MODEL pins every role; TRI_MODEL_<ROLE> and
    # TRI_EFFORT_<ROLE> override one role; TRI_MODEL_FALLBACKS is comma-separated, "" disables it.
    tri_model: str | None = None
    tri_model_fallbacks: str | None = None
    tri_model_coach: str | None = None
    tri_effort_coach: Effort | None = None
    tri_model_analyst: str | None = None
    tri_effort_analyst: Effort | None = None
    tri_model_wellness_chat: str | None = None
    tri_effort_wellness_chat: Effort | None = None
    tri_model_planning_agent: str | None = None
    tri_effort_planning_agent: Effort | None = None
    tri_model_planning_design: str | None = None
    tri_effort_planning_design: Effort | None = None
    tri_model_nutrition_agent: str | None = None
    tri_effort_nutrition_agent: Effort | None = None
    tri_model_nutrition_fuel: str | None = None
    tri_effort_nutrition_fuel: Effort | None = None
    tri_model_lab_extract: str | None = None
    tri_effort_lab_extract: Effort | None = None
    tri_model_lab_report: str | None = None
    tri_effort_lab_report: Effort | None = None
    tri_model_judge: str | None = None
    tri_effort_judge: Effort | None = None
```

The five `make_model` copies still read `settings.tri_model`, now possibly `None`; `ChatAnthropic(model=None)` would fail only when a CLI runs, and Task 7 replaces them before the branch is used. Tests never build them with `tri_model` unset.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 6: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+2 passed` (950), same skips, ruff clean, `mypy` `Success`. `packages/tri-analyze/tests/test_llm.py` still passes: it sets `tri_model` explicitly.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-core/src/tri_core/config.py packages/tri-core/tests/test_config.py
git commit -m "feat(core): per-role model and effort settings; TRI_MODEL defaults to unset"
```

---

### Task 2: `tri_core.llm` registry: `resolve`, `make_model`, `fallbacks_of`

**Files:**
- Create: `packages/tri-core/src/tri_core/llm.py`
- Test: `packages/tri-core/tests/test_llm.py`

**Interfaces:**
- Consumes: Task 1's `Settings` fields and `Effort`.
- Produces:
  - `class Role(StrEnum)` with `COACH, ANALYST, WELLNESS_CHAT, PLANNING_AGENT, PLANNING_DESIGN, NUTRITION_AGENT, NUTRITION_FUEL, LAB_EXTRACT, LAB_REPORT, JUDGE` (values are the lower-case names)
  - `@dataclass(frozen=True) class ModelSpec: model: str; effort: Effort | None; max_tokens: int; fallbacks: tuple[str, ...]`
  - `ModelProvider = Callable[[Role], BaseChatModel]`
  - `DEFAULTS: dict[Role, ModelSpec]`, `STRUCTURED_ROLES: frozenset[Role]`, `RETRYABLE: tuple[type[BaseException], ...]`
  - `resolve(settings: Settings, role: Role) -> ModelSpec`
  - `make_model(settings: Settings, role: Role) -> ChatAnthropic`
  - `fallbacks_of(model: BaseChatModel) -> list[ChatAnthropic]`
  - `Effort` re-exported: `from tri_core.llm import Effort` works.

- [ ] **Step 1: Write the failing tests**

Create `packages/tri-core/tests/test_llm.py`:

```python
from typing import Any

import pytest

from tri_core.config import Settings
from tri_core.llm import (
    DEFAULTS,
    STRUCTURED_ROLES,
    Role,
    fallbacks_of,
    make_model,
    resolve,
)
from tri_core.testing import ScriptedChatModel


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, anthropic_api_key="k", **kw)


# resolve


def test_every_role_launches_on_opus_5_at_default_effort():
    assert set(DEFAULTS) == set(Role)
    for role in Role:
        spec = resolve(settings(), role)
        assert spec.model == "claude-opus-5" and spec.effort is None
        assert spec.fallbacks == ("claude-opus-4-8", "claude-sonnet-5")
    assert resolve(settings(), Role.LAB_EXTRACT).max_tokens == 32000
    assert resolve(settings(), Role.LAB_REPORT).max_tokens == 32000
    assert resolve(settings(), Role.COACH).max_tokens == 16000


def test_role_override_beats_tri_model_which_beats_the_default():
    s = settings(tri_model="claude-sonnet-5", tri_model_analyst="claude-haiku-4-5")
    assert resolve(s, Role.ANALYST).model == "claude-haiku-4-5"
    assert resolve(s, Role.COACH).model == "claude-sonnet-5"


def test_effort_override_applies_and_a_model_override_does_not_reset_it():
    s = settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium")
    assert resolve(s, Role.ANALYST).effort == "medium"
    assert resolve(settings(tri_effort_coach="high"), Role.COACH).effort == "high"


def test_default_chain_is_the_first_two_other_models():
    assert resolve(settings(tri_model="claude-opus-4-8"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-sonnet-5",
    )
    assert resolve(settings(tri_model="claude-sonnet-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )
    assert resolve(settings(tri_model="claude-haiku-4-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )


def test_tri_model_fallbacks_is_parsed_and_drops_the_primary():
    s = settings(tri_model_fallbacks=" claude-sonnet-5 , claude-opus-5,claude-sonnet-5 ")
    assert resolve(s, Role.COACH).fallbacks == ("claude-sonnet-5",)
    assert resolve(settings(tri_model_fallbacks=""), Role.COACH).fallbacks == ()


def test_an_effort_the_model_does_not_list_raises_naming_the_env_var():
    s = settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low")
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST=low is not supported by claude-haiku"):
        resolve(s, Role.ANALYST)
    assert resolve(settings(tri_model_analyst="claude-haiku-4-5"), Role.ANALYST).effort is None


def test_structured_roles_refuse_an_effort():
    assert {
        Role.PLANNING_DESIGN,
        Role.NUTRITION_FUEL,
        Role.LAB_EXTRACT,
        Role.JUDGE,
    } == STRUCTURED_ROLES
    with pytest.raises(ValueError, match="TRI_EFFORT_JUDGE=low is not allowed"):
        resolve(settings(tri_effort_judge="low"), Role.JUDGE)
    with pytest.raises(ValueError, match="TRI_EFFORT_NUTRITION_FUEL=medium is not allowed"):
        resolve(settings(tri_effort_nutrition_fuel="medium"), Role.NUTRITION_FUEL)


# make_model


def test_make_model_builds_the_role_spec_with_its_metadata():
    m = make_model(
        settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium"), Role.ANALYST
    )
    assert m.model == "claude-sonnet-5" and m.max_tokens == 16000 and m.effort == "medium"
    assert m.anthropic_api_key.get_secret_value() == "k"
    meta = m.metadata or {}
    assert meta["tri_role"] == "analyst"
    assert meta["tri_fallbacks"] == ["claude-opus-5", "claude-opus-4-8"]
    lab = make_model(settings(), Role.LAB_EXTRACT)
    assert lab.max_tokens == 32000 and lab.effort is None


def test_make_model_raises_before_any_call_for_a_bad_override():
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST"):
        make_model(
            settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low"), Role.ANALYST
        )


# fallbacks_of


def test_fallbacks_of_is_empty_for_models_make_model_did_not_build():
    from langchain_anthropic import ChatAnthropic

    assert fallbacks_of(ScriptedChatModel(script=[])) == []
    assert fallbacks_of(ChatAnthropic(model="claude-opus-5")) == []
    assert fallbacks_of(make_model(settings(tri_model_fallbacks=""), Role.COACH)) == []


def test_fallbacks_of_builds_each_model_with_its_own_profile_and_effort():
    primary = make_model(settings(), Role.COACH)
    fbs = fallbacks_of(primary)
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert [f.effort for f in fbs] == ["high", "high"]  # primary at default: run fallbacks at high
    assert all(f.max_tokens == 16000 for f in fbs)
    assert all(f.anthropic_api_key.get_secret_value() == "k" for f in fbs)
    assert all((f.metadata or {})["tri_fallback_from"] == "claude-opus-5" for f in fbs)
    assert all((f.metadata or {})["tri_role"] == "coach" for f in fbs)


def test_fallbacks_keep_the_primary_effort_when_listed_and_drop_it_for_haiku():
    s = settings(
        tri_effort_analyst="medium", tri_model_fallbacks="claude-sonnet-5,claude-haiku-4-5"
    )
    fbs = fallbacks_of(make_model(s, Role.ANALYST))
    assert [(f.model, f.effort) for f in fbs] == [
        ("claude-sonnet-5", "medium"),
        ("claude-haiku-4-5", None),
    ]


def test_structured_roles_fall_back_without_effort():
    fbs = fallbacks_of(make_model(settings(), Role.NUTRITION_FUEL))
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert all(f.effort is None for f in fbs)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_llm.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'tri_core.llm'`.

- [ ] **Step 3: Write the implementation**

Create `packages/tri-core/src/tri_core/llm.py`:

```python
"""Model routing: one model, effort, output ceiling and fallback chain per role.

Every role launches on today's model. A role moves to a lighter model or effort only after its
eval holds quality (docs/superpowers/specs/2026-09-15-model-routing-design.md §7.2); env vars
override one role at a time. A thread stays on one model, so the prompt cache keeps hitting.
When the primary model is overloaded or unavailable, the call is retried on the next Claude
model in the role's chain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from anthropic import (
    APIConnectionError,
    DeadlineExceededError,
    InternalServerError,
    OverloadedError,
    RateLimitError,
    ServiceUnavailableError,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from tri_core.config import Effort as Effort
from tri_core.config import Settings


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


@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: Effort | None  # None: the model's default (sends nothing)
    max_tokens: int
    fallbacks: tuple[str, ...]


ModelProvider = Callable[[Role], BaseChatModel]

_OPUS = "claude-opus-5"
_CHAIN = ("claude-opus-5", "claude-opus-4-8", "claude-sonnet-5")


def _spec(max_tokens: int = 16000) -> ModelSpec:
    return ModelSpec(model=_OPUS, effort=None, max_tokens=max_tokens, fallbacks=())


# Launch defaults: every role on today's model at its default effort. Change one line here only
# when that role's eval passes the gate in the spec's §7.2.
DEFAULTS: dict[Role, ModelSpec] = {
    Role.COACH: _spec(),
    Role.ANALYST: _spec(),
    Role.WELLNESS_CHAT: _spec(),
    Role.PLANNING_AGENT: _spec(),
    Role.PLANNING_DESIGN: _spec(),
    Role.NUTRITION_AGENT: _spec(),
    Role.NUTRITION_FUEL: _spec(),
    Role.LAB_EXTRACT: _spec(32000),  # a 200-row panel is roughly 12k output tokens as JSON
    Role.LAB_REPORT: _spec(32000),  # reports are long
    Role.JUDGE: _spec(),
}

# Roles that run structured output. It forces a tool call, which the API refuses when thinking
# is on, and an effort level turns thinking on; so these roles, and their fallbacks, never send
# an effort.
STRUCTURED_ROLES = frozenset(
    {Role.PLANNING_DESIGN, Role.NUTRITION_FUEL, Role.LAB_EXTRACT, Role.JUDGE}
)

# The errors worth retrying on another model: overload, rate limits, server errors and lost
# connections. A 400, 401, 403, 404 or 413 would fail the same way on any model.
RETRYABLE: tuple[type[BaseException], ...] = (
    RateLimitError,
    OverloadedError,
    InternalServerError,
    ServiceUnavailableError,
    DeadlineExceededError,
    APIConnectionError,
)


def _effort_levels(model_id: str) -> tuple[str, ...]:
    """The effort levels the model's profile lists; () for a model with no levels or profile."""
    profile = ChatAnthropic(model=model_id).profile or {}
    return tuple(profile.get("reasoning_effort_levels") or ())


def _env(role: Role) -> str:
    return role.value.upper()


def resolve(settings: Settings, role: Role) -> ModelSpec:
    default = DEFAULTS[role]
    role_model: str | None = getattr(settings, f"tri_model_{role.value}")
    role_effort: Effort | None = getattr(settings, f"tri_effort_{role.value}")
    model = role_model or settings.tri_model or default.model
    effort = role_effort or default.effort
    if settings.tri_model_fallbacks is not None:
        wanted = [m.strip() for m in settings.tri_model_fallbacks.split(",") if m.strip()]
    else:
        wanted = [m for m in _CHAIN if m != model][:2]
    fallbacks = tuple(dict.fromkeys(m for m in wanted if m != model))
    if effort is not None:
        if role in STRUCTURED_ROLES:
            raise ValueError(
                f"TRI_EFFORT_{_env(role)}={effort} is not allowed: {role.value} runs structured "
                "output, which cannot use thinking"
            )
        if effort not in _effort_levels(model):
            raise ValueError(f"TRI_EFFORT_{_env(role)}={effort} is not supported by {model}")
    return ModelSpec(model=model, effort=effort, max_tokens=default.max_tokens, fallbacks=fallbacks)


def make_model(settings: Settings, role: Role) -> ChatAnthropic:
    """The role's model. Raises ValueError for an invalid override, so a bad .env fails when the
    CLI or server starts, before any turn."""
    spec = resolve(settings, role)
    return ChatAnthropic(
        model=spec.model,
        max_tokens=spec.max_tokens,
        api_key=settings.anthropic_api_key,
        effort=spec.effort,
        metadata={"tri_role": role.value, "tri_fallbacks": list(spec.fallbacks)},
    )


def fallbacks_of(model: BaseChatModel) -> list[ChatAnthropic]:
    """The models to try, in order, when `model` fails with a RETRYABLE error. Empty for anything
    make_model did not build (fakes in tests, a model passed in by hand)."""
    if not isinstance(model, ChatAnthropic):
        return []
    meta = model.metadata or {}
    ids = meta.get("tri_fallbacks")
    if not ids:
        return []
    role = str(meta.get("tri_role", ""))
    out: list[ChatAnthropic] = []
    for model_id in ids:
        levels = _effort_levels(model_id)
        effort: Effort | None
        if role in STRUCTURED_ROLES:
            effort = None
        elif model.effort is not None and model.effort in levels:
            effort = model.effort
        elif levels:
            effort = "high"
        else:
            effort = None
        out.append(
            ChatAnthropic(
                model=model_id,
                max_tokens=model.max_tokens,
                api_key=model.anthropic_api_key,
                effort=effort,
                metadata={"tri_role": role, "tri_fallback_from": model.model},
            )
        )
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_llm.py -v`
Expected: 13 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+15 passed` (963), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/llm.py packages/tri-core/tests/test_llm.py
git commit -m "feat(core): tri_core.llm role registry with resolve, make_model and fallbacks_of"
```

---

### Task 3: `claude_fallback` middleware in the harness builders

**Files:**
- Modify: `packages/tri-core/src/tri_core/llm.py` (append)
- Modify: `packages/tri-core/src/tri_core/harness/agents.py`
- Test: `packages/tri-core/tests/test_llm.py` (append), `packages/tri-core/tests/test_harness_agents.py`

**Interfaces:**
- Consumes (Task 2): `RETRYABLE`, `fallbacks_of`.
- Produces: `class ClaudeFallbackMiddleware(AgentMiddleware[Any, Any, Any])` with `wrap_model_call(self, request: Any, handler: Any) -> Any` and `async awrap_model_call(self, request: Any, handler: Any) -> Any`; the instance `claude_fallback`; `make_subagent` and `build_chat_agent` pass `middleware=[*middleware, claude_fallback, caching]`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_llm.py`, and merge these imports into its import block:

```python
import logging

import anthropic
import httpx
from langgraph.errors import GraphBubbleUp

from tri_core.llm import claude_fallback
```

```python
REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def overloaded() -> anthropic.OverloadedError:
    return anthropic.OverloadedError(
        "overloaded", response=httpx.Response(529, request=REQ), body=None
    )


def bad_request() -> anthropic.BadRequestError:
    return anthropic.BadRequestError("bad", response=httpx.Response(400, request=REQ), body=None)


# claude_fallback


class FakeRequest:
    def __init__(self, model: Any) -> None:
        self.model = model

    def override(self, **kw: Any) -> "FakeRequest":
        return FakeRequest(kw["model"])


def recording_handler(errors: dict[str, BaseException]):
    seen: list[str] = []

    async def handler(request: FakeRequest) -> str:
        seen.append(request.model.model)
        if request.model.model in errors:
            raise errors[request.model.model]
        return f"answered by {request.model.model}"

    return handler, seen


async def test_claude_fallback_moves_to_the_next_model_on_overload(caplog):
    handler, seen = recording_handler({"claude-opus-5": overloaded()})
    primary = make_model(settings(), Role.COACH)
    with caplog.at_level(logging.WARNING, logger="tri_core.llm"):
        out = await claude_fallback.awrap_model_call(FakeRequest(primary), handler)
    assert out == "answered by claude-opus-4-8"
    assert seen == ["claude-opus-5", "claude-opus-4-8"]
    assert "coach fell back from claude-opus-5 to claude-opus-4-8 after OverloadedError" in (
        caplog.text
    )


async def test_claude_fallback_raises_a_bad_request_without_retrying():
    handler, seen = recording_handler({"claude-opus-5": bad_request()})
    with pytest.raises(anthropic.BadRequestError):
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert seen == ["claude-opus-5"]


async def test_claude_fallback_lets_graph_control_flow_through():
    handler, seen = recording_handler({"claude-opus-5": GraphBubbleUp()})
    with pytest.raises(GraphBubbleUp):
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert seen == ["claude-opus-5"]


async def test_claude_fallback_raises_the_last_error_when_every_model_fails():
    last = overloaded()
    errors = {
        "claude-opus-5": overloaded(),
        "claude-opus-4-8": overloaded(),
        "claude-sonnet-5": last,
    }
    handler, seen = recording_handler(errors)
    with pytest.raises(anthropic.OverloadedError) as info:
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert info.value is last and len(seen) == 3


async def test_claude_fallback_without_fallbacks_raises_the_original_error():
    first = overloaded()
    handler, seen = recording_handler({"claude-opus-5": first})
    model = make_model(settings(tri_model_fallbacks=""), Role.COACH)
    with pytest.raises(anthropic.OverloadedError) as info:
        await claude_fallback.awrap_model_call(FakeRequest(model), handler)
    assert info.value is first and seen == ["claude-opus-5"]


def test_claude_fallback_has_a_sync_hook_too():
    def handler(request: FakeRequest) -> str:
        if request.model.model == "claude-opus-5":
            raise overloaded()
        return request.model.model

    out = claude_fallback.wrap_model_call(FakeRequest(make_model(settings(), Role.COACH)), handler)
    assert out == "claude-opus-4-8"
```

In `packages/tri-core/tests/test_harness_agents.py`, add `from tri_core.llm import claude_fallback` to the imports and replace lines 84–87 and 90:

```python
    assert len(sub["middleware"]) == 2 and sub["middleware"][0] is one_tool_call_at_a_time
    assert isinstance(sub["middleware"][1], AnthropicPromptCachingMiddleware)
    assert chat["middleware"][0] is one_tool_call_at_a_time
    assert isinstance(chat["middleware"][1], AnthropicPromptCachingMiddleware)
```

```python
    assert isinstance(bare["checkpointer"], InMemorySaver) and len(bare["middleware"]) == 1
```

with:

```python
    assert len(sub["middleware"]) == 3 and sub["middleware"][0] is one_tool_call_at_a_time
    assert sub["middleware"][1] is claude_fallback
    assert isinstance(sub["middleware"][2], AnthropicPromptCachingMiddleware)
    assert chat["middleware"][0] is one_tool_call_at_a_time
    assert chat["middleware"][1] is claude_fallback
    assert isinstance(chat["middleware"][2], AnthropicPromptCachingMiddleware)
```

```python
    assert isinstance(bare["checkpointer"], InMemorySaver) and len(bare["middleware"]) == 2
    assert bare["middleware"][0] is claude_fallback
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_llm.py packages/tri-core/tests/test_harness_agents.py -v`
Expected: collection error in `test_llm.py`, `ImportError: cannot import name 'claude_fallback' from 'tri_core.llm'` (and the same in `test_harness_agents.py`).

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/llm.py`, add to the imports:

```python
import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
```

add below the imports (before `class Role`):

```python
log = logging.getLogger(__name__)
```

and append to the module:

```python
def _note(primary: BaseChatModel, fallback: ChatAnthropic, error: BaseException | None) -> None:
    meta = primary.metadata or {}
    after = f" after {type(error).__name__}" if error is not None else ""
    log.warning(
        "%s fell back from %s to %s%s",
        meta.get("tri_role", "?"),
        getattr(primary, "model", "?"),
        getattr(fallback, "model", "?"),
        after,
    )


class ClaudeFallbackMiddleware(AgentMiddleware[Any, Any, Any]):
    """Retries a failed model call on the role's next Claude model. Only RETRYABLE errors fall
    back; interrupts and every other error propagate at once. When the whole chain fails, the
    last error is raised."""

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return handler(request)
        except RETRYABLE as exc:
            error: BaseException = exc
        for fallback in fallbacks_of(request.model):
            _note(request.model, fallback, error)
            try:
                return handler(request.override(model=fallback))
            except RETRYABLE as exc:
                error = exc
        raise error

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        try:
            return await handler(request)
        except RETRYABLE as exc:
            error: BaseException = exc
        for fallback in fallbacks_of(request.model):
            _note(request.model, fallback, error)
            try:
                return await handler(request.override(model=fallback))
            except RETRYABLE as exc:
                error = exc
        raise error


claude_fallback = ClaudeFallbackMiddleware()
```

In `packages/tri-core/src/tri_core/harness/agents.py`, replace the module docstring:

```python
"""The agent builders every package uses. Prompt caching is always the last middleware, so the
prompt an earlier dynamic-prompt middleware renders is what gets marked for the cache."""
```

with:

```python
"""The agent builders every package uses. Every agent ends with the same two middlewares: the
Claude fallback, then prompt caching. Caching stays last, so the prompt an earlier
dynamic-prompt middleware renders is what gets marked for the cache, and the marks are applied
to whichever model the fallback picked."""
```

add after the `langgraph.checkpoint.memory` import:

```python
from tri_core.llm import claude_fallback
```

and replace both occurrences (in `make_subagent` and `build_chat_agent`) of:

```python
        middleware=[*middleware, _caching()],
```

with:

```python
        middleware=[*middleware, claude_fallback, _caching()],
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_llm.py packages/tri-core/tests/test_harness_agents.py -v`
Expected: all pass (19 in `test_llm.py`).

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+21 passed` (969), same skips, ruff clean, `mypy` `Success`. Every agent test in every package still passes: `ScriptedChatModel` has no fallbacks, so `claude_fallback` only calls the handler once.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/llm.py packages/tri-core/src/tri_core/harness/agents.py packages/tri-core/tests/test_llm.py packages/tri-core/tests/test_harness_agents.py
git commit -m "feat(core): claude_fallback middleware, just before prompt caching in every agent"
```

---

### Task 4: `structured()` and `streaming()`

**Files:**
- Modify: `packages/tri-core/src/tri_core/llm.py` (append)
- Test: `packages/tri-core/tests/test_llm.py` (append)

**Interfaces:**
- Consumes (Tasks 2–3): `RETRYABLE`, `fallbacks_of`, `_note`.
- Produces:
  - `structured(model: BaseChatModel, schema: type[BaseModel]) -> Runnable[LanguageModelInput, Any]`
  - `streaming(model: BaseChatModel) -> Runnable[LanguageModelInput, Any]`

  With no fallbacks, `structured` returns `model.with_structured_output(schema)` and `streaming` returns `model` itself, so fakes behave exactly as today.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_llm.py`, merging these imports into its import block:

```python
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

import tri_core.llm as llm
from tri_core.llm import streaming, structured
from tri_core.testing import tool_call
```

```python
# structured and streaming


class Verdict(BaseModel):
    ok: bool


class Raising(ScriptedChatModel):
    """A fake that fails every call with `error` before producing anything."""

    error: Any = None

    def _generate(self, *a: Any, **k: Any) -> Any:
        raise self.error

    def _stream(self, *a: Any, **k: Any) -> Any:
        raise self.error


def with_fallbacks_to(monkeypatch, *fallbacks: Any) -> None:
    monkeypatch.setattr(llm, "fallbacks_of", lambda model: list(fallbacks))


async def test_structured_falls_back_on_a_retryable_error(monkeypatch):
    backup = ScriptedChatModel(script=[tool_call("Verdict", {"ok": True})])
    with_fallbacks_to(monkeypatch, backup)
    runnable = structured(Raising(script=[], error=overloaded()), Verdict)
    assert await runnable.ainvoke([HumanMessage("judge")]) == Verdict(ok=True)


async def test_structured_does_not_fall_back_on_a_bad_request(monkeypatch):
    backup = ScriptedChatModel(script=[tool_call("Verdict", {"ok": True})])
    with_fallbacks_to(monkeypatch, backup)
    with pytest.raises(anthropic.BadRequestError):
        await structured(Raising(script=[], error=bad_request()), Verdict).ainvoke(
            [HumanMessage("x")]
        )
    assert backup.calls == 0


async def test_structured_raises_the_primary_error_when_every_model_fails(monkeypatch):
    first = overloaded()
    with_fallbacks_to(monkeypatch, Raising(script=[], error=overloaded()))
    with pytest.raises(anthropic.OverloadedError) as info:
        await structured(Raising(script=[], error=first), Verdict).ainvoke([HumanMessage("x")])
    assert info.value is first


def test_structured_without_fallbacks_is_the_plain_structured_model():
    model = ScriptedChatModel(script=[tool_call("Verdict", {"ok": False})])
    assert structured(model, Verdict).invoke([HumanMessage("x")]) == Verdict(ok=False)


async def test_streaming_falls_back_before_the_first_chunk(monkeypatch):
    with_fallbacks_to(monkeypatch, ScriptedChatModel(script=[AIMessage(content="from backup")]))
    chunks = [c async for c in streaming(Raising(script=[], error=overloaded())).astream("hi")]
    assert "".join(str(c.content) for c in chunks) == "from backup"


async def test_streaming_does_not_fall_back_on_a_bad_request(monkeypatch):
    backup = ScriptedChatModel(script=[AIMessage(content="x")])
    with_fallbacks_to(monkeypatch, backup)
    with pytest.raises(anthropic.BadRequestError):
        [c async for c in streaming(Raising(script=[], error=bad_request())).astream("hi")]
    assert backup.calls == 0


def test_streaming_without_fallbacks_is_the_model_itself():
    model = ScriptedChatModel(script=[])
    assert streaming(model) is model
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_llm.py -v`
Expected: collection error, `ImportError: cannot import name 'streaming' from 'tri_core.llm'`.

- [ ] **Step 3: Write the implementation**

In `packages/tri-core/src/tri_core/llm.py`, extend the imports:

```python
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel
```

(the first line replaces the existing `from langchain_core.language_models import BaseChatModel`), and append:

```python
def _noting(primary: BaseChatModel, fallback: ChatAnthropic) -> Runnable[Any, Any]:
    """An identity step that logs the switch before the fallback runs."""

    def note(value: Any) -> Any:
        _note(primary, fallback, None)
        return value

    return RunnableLambda(note)


def structured(model: BaseChatModel, schema: type[BaseModel]) -> Runnable[LanguageModelInput, Any]:
    """`model.with_structured_output(schema)`, retried on the role's fallbacks for a RETRYABLE
    error. When every model fails, the primary's error is raised."""
    primary = model.with_structured_output(schema)
    fallbacks = fallbacks_of(model)
    if not fallbacks:
        return primary
    return primary.with_fallbacks(
        [_noting(model, fb) | fb.with_structured_output(schema) for fb in fallbacks],
        exceptions_to_handle=RETRYABLE,
    )


def streaming(model: BaseChatModel) -> Runnable[LanguageModelInput, Any]:
    """`model`, retried on the role's fallbacks when a RETRYABLE error comes before the first
    chunk. An error after the first chunk propagates. When every model fails, the primary's
    error is raised."""
    fallbacks = fallbacks_of(model)
    if not fallbacks:
        return model
    return model.with_fallbacks(
        [_noting(model, fb) | fb for fb in fallbacks], exceptions_to_handle=RETRYABLE
    )
```

The fallbacks run without effort on structured roles (`fallbacks_of`, Task 2), so a structured fallback never pairs forced tool use with thinking.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_llm.py -v`
Expected: 26 passed.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+28 passed` (976), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/llm.py packages/tri-core/tests/test_llm.py
git commit -m "feat(core): structured() and streaming() retry on the role's Claude fallbacks"
```

---

### Task 5: Planning design and nutrition fuel models

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/deps.py`, `packages/tri-planning/src/tri_planning/graph/nodes/design.py`
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/deps.py`, `packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`
- Test: `packages/tri-planning/tests/test_design_node.py` (append), `packages/tri-nutrition/tests/test_fuel_node.py` (append)

**Interfaces:**
- Consumes (Task 4): `tri_core.llm.structured`.
- Produces:
  - `tri_planning.graph.deps.GraphDeps.design_model: BaseChatModel | None = None`; `make_deps(settings, model, tp, *, design_model: BaseChatModel | None = None) -> GraphDeps`
  - `tri_nutrition.graph.deps.GraphDeps.fuel_model: BaseChatModel | None = None`; `make_deps(settings, model, garmin, tp=None, *, fuel_model: BaseChatModel | None = None) -> GraphDeps`
  - `design_week` builds its structured runnable with `structured(deps.design_model or deps.model, PlannedWeek)`; `make_fuel_node` builds `FuelPlanner(deps.fuel_model or deps.model)`, whose two runnables come from `structured(model, SessionFuel)` and `structured(model, RaceFuelPlan)`.

- [ ] **Step 1: Write the failing tests**

These tests build `GraphDeps` directly rather than through the `make_deps` fixture, which needs the test database. Append to `packages/tri-planning/tests/test_design_node.py`, adding these imports (and `PlannedWeek` to the existing `tri_planning.planning.models` import if it is not already there; `design_week` joins the existing `tri_planning.graph.nodes.design` import):

```python
import contextlib

import tri_planning.graph.nodes.design as design_node
from tri_planning.config import PlanningSettings
from tri_planning.graph.deps import GraphDeps
from tri_planning.graph.deps import make_deps as real_make_deps
from tri_planning.graph.nodes.design import design_week
from tri_planning.planning.models import PlannedWeek
```

```python
class _Stop(Exception):
    pass


async def test_design_week_uses_the_design_model_when_one_is_set(monkeypatch):
    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        raise _Stop

    monkeypatch.setattr(design_node, "structured", spy)
    agent, designer = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    deps = GraphDeps(model=agent, connect=lambda: contextlib.nullcontext(None), db_url="unused")
    with pytest.raises(_Stop):
        await design_week(deps, None, None, None, None, None, {})
    deps.design_model = designer
    with pytest.raises(_Stop):
        await design_week(deps, None, None, None, None, None, {})
    assert seen == [(agent, PlannedWeek), (designer, PlannedWeek)]


def test_make_deps_takes_an_optional_design_model():
    agent, designer = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    settings = PlanningSettings(_env_file=None)
    assert real_make_deps(settings, agent, None).design_model is None
    assert real_make_deps(settings, agent, None, design_model=designer).design_model is designer
```

Append to `packages/tri-nutrition/tests/test_fuel_node.py`, adding these imports (merge `SessionFuel` and `RaceFuelPlan` into the existing `tri_nutrition.nutrition.models` import):

```python
import contextlib

import tri_nutrition.graph.nodes.fuel as fuel_node
from tri_nutrition.config import NutritionSettings
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.deps import make_deps as real_make_deps
from tri_nutrition.nutrition.models import RaceFuelPlan, SessionFuel
```

```python
def test_the_fuel_node_plans_with_the_fuel_model_when_one_is_set(monkeypatch):
    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        return ScriptedChatModel(script=[])

    monkeypatch.setattr(fuel_node, "structured", spy)
    agent, fueler = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    deps = GraphDeps(model=agent, connect=lambda: contextlib.nullcontext(None), db_url="unused")
    make_fuel_node(deps)
    deps.fuel_model = fueler
    make_fuel_node(deps)
    assert seen == [
        (agent, SessionFuel),
        (agent, RaceFuelPlan),
        (fueler, SessionFuel),
        (fueler, RaceFuelPlan),
    ]


def test_make_deps_takes_an_optional_fuel_model():
    agent, fueler = ScriptedChatModel(script=[]), ScriptedChatModel(script=[])
    settings = NutritionSettings(_env_file=None)
    assert real_make_deps(settings, agent, None).fuel_model is None
    assert real_make_deps(settings, agent, None, None, fuel_model=fueler).fuel_model is fueler
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_design_node.py packages/tri-nutrition/tests/test_fuel_node.py -v`
Expected: the four new tests fail (`AttributeError: ... has no attribute 'structured'` from `monkeypatch.setattr`, and `TypeError: make_deps() got an unexpected keyword argument ...`). The existing tests pass.

- [ ] **Step 3: Write the implementation**

`packages/tri-planning/src/tri_planning/graph/deps.py`: replace

```python
@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
```

with

```python
@dataclass
class GraphDeps:
    model: BaseChatModel  # the intake and adjust sub-agents
    connect: ConnectFactory
```

replace

```python
    horizon_weeks: int = 3
    today: Callable[[], date] = date.today


def make_deps(settings: PlanningSettings, model: BaseChatModel, tp: ToolCaller | None) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        tp=tp,
        horizon_weeks=settings.tri_planning_horizon_weeks,
    )
```

with

```python
    horizon_weeks: int = 3
    today: Callable[[], date] = date.today
    design_model: BaseChatModel | None = None  # the week design call; None: use `model`


def make_deps(
    settings: PlanningSettings,
    model: BaseChatModel,
    tp: ToolCaller | None,
    *,
    design_model: BaseChatModel | None = None,
) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        tp=tp,
        horizon_weeks=settings.tri_planning_horizon_weeks,
        design_model=design_model,
    )
```

`packages/tri-planning/src/tri_planning/graph/nodes/design.py`: add `from tri_core.llm import structured` to the imports, and replace

```python
    structured = deps.model.with_structured_output(PlannedWeek)
```

```python
        out = await structured.ainvoke(
```

with

```python
    designer = structured(deps.design_model or deps.model, PlannedWeek)
```

```python
        out = await designer.ainvoke(
```

`packages/tri-nutrition/src/tri_nutrition/graph/deps.py`: replace

```python
@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
```

with

```python
@dataclass
class GraphDeps:
    model: BaseChatModel  # the intake and check-in sub-agents
    connect: ConnectFactory
```

replace

```python
    horizon_days: int = 14
    today: Callable[[], date] = date.today


def make_deps(
    settings: NutritionSettings,
    model: BaseChatModel,
    garmin: ToolCaller | None,
    tp: ToolCaller | None = None,
) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        garmin=garmin,
        tp=tp,
        horizon_days=settings.tri_nutrition_horizon_days,
    )
```

with

```python
    horizon_days: int = 14
    today: Callable[[], date] = date.today
    fuel_model: BaseChatModel | None = None  # the fueling calls; None: use `model`


def make_deps(
    settings: NutritionSettings,
    model: BaseChatModel,
    garmin: ToolCaller | None,
    tp: ToolCaller | None = None,
    *,
    fuel_model: BaseChatModel | None = None,
) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        db_url=url,
        garmin=garmin,
        tp=tp,
        horizon_days=settings.tri_nutrition_horizon_days,
        fuel_model=fuel_model,
    )
```

`packages/tri-nutrition/src/tri_nutrition/graph/nodes/fuel.py`: add `from tri_core.llm import structured` to the imports, replace

```python
        self._session: Runnable[LanguageModelInput, Any] = model.with_structured_output(SessionFuel)
        self._race: Runnable[LanguageModelInput, Any] = model.with_structured_output(RaceFuelPlan)
```

with

```python
        self._session: Runnable[LanguageModelInput, Any] = structured(model, SessionFuel)
        self._race: Runnable[LanguageModelInput, Any] = structured(model, RaceFuelPlan)
```

and replace

```python
    planner = FuelPlanner(deps.model)
```

with

```python
    planner = FuelPlanner(deps.fuel_model or deps.model)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning packages/tri-nutrition -q`
Expected: all pass, including the four new tests.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+32 passed` (980), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-planning packages/tri-nutrition
git commit -m "feat(planning,nutrition): optional design and fuel models; structured calls fall back"
```

---

### Task 6: Lab extraction, the lab report and the judges on the helpers

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/extract/structured.py`, `packages/tri-wellness/src/tri_wellness/report.py`
- Modify: `packages/tri-analyze/src/tri_analyze/evals/evaluators.py`, `packages/tri-coach/src/tri_coach/evals/evaluators.py`, `packages/tri-nutrition/src/tri_nutrition/evals/evaluators.py`
- Test: `packages/tri-wellness/tests/test_extract.py` (append), `packages/tri-wellness/tests/test_report.py` (append)

**Interfaces:**
- Consumes (Task 4): `tri_core.llm.structured`, `tri_core.llm.streaming`.
- Produces: `extract_structured` builds its runnable with `structured(model, ExtractedPanel)`; `ReportWriter.write` streams through `streaming(self.model)`; the three judges build theirs with `structured(model, <Judgement>)`. `ReportWriter.model` stays the model it was given.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-wellness/tests/test_extract.py`, adding these imports (`ScriptedChatModel` joins the existing `tri_core.testing` import):

```python
import tri_wellness.labs.extract.structured as structured_module
from tri_core.testing import ScriptedChatModel
from tri_wellness.labs.extract.structured import extract_structured
```

```python
async def test_extraction_goes_through_the_structured_helper(monkeypatch):
    class _Stop(Exception):
        pass

    seen = []

    def spy(model, schema):
        seen.append((model, schema))
        raise _Stop

    monkeypatch.setattr(structured_module, "structured", spy)
    model = ScriptedChatModel(script=[])
    with pytest.raises(_Stop):
        await extract_structured(model, "prompt", None, [], None)
    assert seen == [(model, ExtractedPanel)]
```

Append to `packages/tri-wellness/tests/test_report.py`, adding these imports:

```python
from typing import Any

import anthropic
import httpx

import tri_core.llm as llm
```

```python
class Overloaded(ScriptedChatModel):
    def _generate(self, *a: Any, **k: Any) -> Any:
        raise self._error()

    def _stream(self, *a: Any, **k: Any) -> Any:
        raise self._error()

    @staticmethod
    def _error() -> anthropic.OverloadedError:
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return anthropic.OverloadedError(
            "overloaded", response=httpx.Response(529, request=req), body=None
        )


async def test_writer_falls_back_when_the_report_model_is_overloaded(monkeypatch):
    backup = ScriptedChatModel(script=[AIMessage(content="from the backup")])
    monkeypatch.setattr(llm, "fallbacks_of", lambda model: [backup])
    chunks: list[str] = []
    text = await ReportWriter(Overloaded(script=[])).write("prompt", chunks.append, ["panel_id:1"])
    assert text == "from the backup" and "".join(chunks) == "from the backup"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_extract.py packages/tri-wellness/tests/test_report.py -v`
Expected: `test_extraction_goes_through_the_structured_helper` fails (`AttributeError: ... has no attribute 'structured'`); `test_writer_falls_back_when_the_report_model_is_overloaded` fails with `anthropic.OverloadedError`. The existing tests pass.

- [ ] **Step 3: Write the implementation**

`packages/tri-wellness/src/tri_wellness/labs/extract/structured.py`: add `from tri_core.llm import structured` to the imports, and replace

```python
    structured = model.with_structured_output(ExtractedPanel)
    cfg = merge_configs(config, {"tags": tags})
    out = await structured.ainvoke(
```

with

```python
    extractor = structured(model, ExtractedPanel)
    cfg = merge_configs(config, {"tags": tags})
    out = await extractor.ainvoke(
```

`packages/tri-wellness/src/tri_wellness/report.py`: add `from tri_core.llm import streaming` to the imports, and replace

```python
        async for chunk in self.model.astream(
```

with

```python
        async for chunk in streaming(self.model).astream(
```

`packages/tri-analyze/src/tri_analyze/evals/evaluators.py`: add `from tri_core.llm import structured` to the imports and replace

```python
    judge = model.with_structured_output(FeedbackJudgement)
```

with

```python
    judge = structured(model, FeedbackJudgement)
```

`packages/tri-coach/src/tri_coach/evals/evaluators.py`: add `from tri_core.llm import structured` to the imports and replace

```python
    judge = model.with_structured_output(BriefJudgement)
```

with

```python
    judge = structured(model, BriefJudgement)
```

`packages/tri-nutrition/src/tri_nutrition/evals/evaluators.py`: add `from tri_core.llm import structured` to the imports and replace

```python
    judge = model.with_structured_output(FuelJudgement)
```

with

```python
    judge = structured(model, FuelJudgement)
```

`report.py`'s existing `except anthropic.RateLimitError / APIStatusError / APIConnectionError` clauses still see an anthropic error when every model fails, because `streaming` raises the primary's error.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-wellness packages/tri-analyze packages/tri-coach packages/tri-nutrition -q`
Expected: all pass, including the two new tests. The judge tests use `ScriptedChatModel`, so `structured` returns the plain structured model.

Run: `rg -n "with_structured_output" packages --glob '!**/tri_core/llm.py'`
Expected: no output.

- [ ] **Step 5: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+34 passed` (982), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 6: Commit**

```bash
git add packages/tri-wellness packages/tri-analyze/src/tri_analyze/evals/evaluators.py packages/tri-coach/src/tri_coach/evals/evaluators.py packages/tri-nutrition/src/tri_nutrition/evals/evaluators.py
git commit -m "feat: lab extraction, lab report and judges retry on the role's Claude fallbacks"
```

---

### Task 7: Every model from `tri_core.llm.make_model`; the five copies deleted

**Files:**
- Delete: `packages/tri-analyze/src/tri_analyze/llm.py`, `packages/tri-analyze/tests/test_llm.py`, and `graph/llm.py` in `tri-coach`, `tri-planning`, `tri-nutrition`, `tri-wellness`
- Modify: `packages/tri-coach/src/tri_coach/graph/deps.py`
- Modify: `packages/tri-analyze/src/tri_analyze/cli.py`, `packages/tri-coach/src/tri_coach/cli.py`, `packages/tri-planning/src/tri_planning/cli.py`, `packages/tri-nutrition/src/tri_nutrition/cli.py`, `packages/tri-wellness/src/tri_wellness/cli.py`, `packages/tri-web/src/tri_web/runtime.py`, `scripts/design_eval.py`
- Modify: the four eval `run.py`: `packages/tri-analyze/src/tri_analyze/evals/run.py`, `packages/tri-coach/src/tri_coach/evals/run.py`, `packages/tri-nutrition/src/tri_nutrition/evals/run.py`, `packages/tri-wellness/src/tri_wellness/evals/run.py`
- Modify (tests): `packages/tri-coach/tests/test_servers.py`, `packages/tri-coach/tests/test_live.py`, `packages/tri-wellness/tests/test_live_pdf.py`

**Interfaces:**
- Consumes (Tasks 2, 5): `Role`, `ModelProvider`, `make_model`, `resolve`; the new `design_model` / `fuel_model` keywords.
- Produces: `tri_coach.graph.deps.make_deps(settings: CoachSettings, models: ModelProvider, servers: Servers, *, today=date.today) -> CoachDeps`. Every production model comes from `make_model(settings, Role.<role>)`.

- [ ] **Step 1: Run the affected tests on the unchanged code**

Run: `uv run pytest packages/tri-coach/tests/test_servers.py packages/tri-web -q`
Expected: all pass.

- [ ] **Step 2: The coach's `make_deps` takes a provider**

In `packages/tri-coach/src/tri_coach/graph/deps.py`, add `from tri_core.llm import ModelProvider, Role` to the imports and replace

```python
def make_deps(
    settings: CoachSettings,
    model: BaseChatModel,
    servers: Servers,
    *,
    today: Callable[[], date] = date.today,
) -> CoachDeps:
    url = settings.database_url
    connect = lambda: core_connect(url)  # noqa: E731
    planning = make_planning_deps(get_planning_settings(), model, servers.tp)
    planning.garmin_tools = filter_tools(servers.garmin_tools, planning_allow.GARMIN_LIVE_TOOLS)
    planning.today = today
    nutrition = make_nutrition_deps(get_nutrition_settings(), model, servers.garmin, servers.tp)
    nutrition.today = today
    registry = load_registry(settings.tri_athlete_sex) if settings.tri_athlete_sex else None
    return CoachDeps(
        model=model,
        analyst_model=model,
        connect=connect,
        db_url=url,
        planning_deps=planning,
        nutrition_deps=nutrition,
        analyst_tools=analyst_tools_for(servers, url, today, connect),
        wellness_model=model,
```

with

```python
def make_deps(
    settings: CoachSettings,
    models: ModelProvider,
    servers: Servers,
    *,
    today: Callable[[], date] = date.today,
) -> CoachDeps:
    """`models` maps each role to its model: `lambda role: make_model(settings, role)` in the
    CLI and tri-web, one fake for every role in tests."""
    url = settings.database_url
    connect = lambda: core_connect(url)  # noqa: E731
    planning = make_planning_deps(
        get_planning_settings(),
        models(Role.PLANNING_AGENT),
        servers.tp,
        design_model=models(Role.PLANNING_DESIGN),
    )
    planning.garmin_tools = filter_tools(servers.garmin_tools, planning_allow.GARMIN_LIVE_TOOLS)
    planning.today = today
    nutrition = make_nutrition_deps(
        get_nutrition_settings(),
        models(Role.NUTRITION_AGENT),
        servers.garmin,
        servers.tp,
        fuel_model=models(Role.NUTRITION_FUEL),
    )
    nutrition.today = today
    registry = load_registry(settings.tri_athlete_sex) if settings.tri_athlete_sex else None
    return CoachDeps(
        model=models(Role.COACH),
        analyst_model=models(Role.ANALYST),
        connect=connect,
        db_url=url,
        planning_deps=planning,
        nutrition_deps=nutrition,
        analyst_tools=analyst_tools_for(servers, url, today, connect),
        wellness_model=models(Role.WELLNESS_CHAT),
```

In `packages/tri-coach/tests/test_servers.py`, change only the second argument of the three `make_deps` calls, from `model` to `lambda _: model`:

| Line | Before | After |
|---|---|---|
| 119 | `make_deps(CoachSettings(_env_file=None), model, servers, today=lambda: date(2026, 9, 14))` | `make_deps(CoachSettings(_env_file=None), lambda _: model, servers, today=lambda: date(2026, 9, 14))` |
| 131 | `make_deps(CoachSettings(_env_file=None), model, servers)` | `make_deps(CoachSettings(_env_file=None), lambda _: model, servers)` |
| 134 | `make_deps(CoachSettings(_env_file=None), model, servers)` | `make_deps(CoachSettings(_env_file=None), lambda _: model, servers)` |

The assertions (`deps.model is model and deps.analyst_model is model`, `deps.wellness_model is model`) are unchanged.

- [ ] **Step 3: Point every caller at `tri_core.llm`**

In each file below, replace the package `make_model` import with `from tri_core.llm import Role, make_model` (inside the same function), and change each call as shown. `ruff check --fix` sorts the moved import.

`packages/tri-analyze/src/tri_analyze/cli.py`
- `:60` `from tri_analyze.llm import make_model` → `from tri_core.llm import Role, make_model`
- `:93` `agent = build_agent(make_model(settings), tools)` → `agent = build_agent(make_model(settings, Role.ANALYST), tools)`
- `:143` same import change
- `:154` `make_model(settings),` → `make_model(settings, Role.ANALYST),`

`packages/tri-coach/src/tri_coach/cli.py`
- `:78` `from tri_coach.graph.llm import make_model` → `from tri_core.llm import Role, make_model`
- `:93` `deps = make_deps(settings, make_model(settings), servers)` → `deps = make_deps(settings, lambda role: make_model(settings, role), servers)`
- `:291` same import change
- `:302` `make_model(settings),` → `make_model(settings, Role.COACH),`

In `_open_graph` only `make_model` is used, so the import there is `from tri_core.llm import make_model`.

`packages/tri-planning/src/tri_planning/cli.py`
- `:48` `from tri_planning.graph.llm import make_model` → `from tri_core.llm import Role, make_model`
- `:81` `deps = make_deps(settings, make_model(settings), tp)` →

```python
        deps = make_deps(
            settings,
            make_model(settings, Role.PLANNING_AGENT),
            tp,
            design_model=make_model(settings, Role.PLANNING_DESIGN),
        )
```

`packages/tri-nutrition/src/tri_nutrition/cli.py`
- `:118`, `:228`, `:282`, `:323` `from tri_nutrition.graph.llm import make_model` → `from tri_core.llm import Role, make_model`
- `:134` and `:300` `graph = build_graph(make_deps(settings, make_model(settings), garmin, tp), saver, store)` →

```python
        deps = make_deps(
            settings,
            make_model(settings, Role.NUTRITION_AGENT),
            garmin,
            tp,
            fuel_model=make_model(settings, Role.NUTRITION_FUEL),
        )
        graph = build_graph(deps, saver, store)
```

- `:248` `deps = make_deps(settings, make_model(settings), garmin)` → `deps = make_deps(settings, make_model(settings, Role.NUTRITION_AGENT), garmin)`
- `:334` `make_model(settings),` → `make_model(settings, Role.NUTRITION_FUEL),`

`packages/tri-wellness/src/tri_wellness/cli.py`
- `:97`, `:163`, `:195`, `:285` `from tri_wellness.graph.llm import make_model` → `from tri_core.llm import Role, make_model`
- `:126` `deps = make_deps(settings, make_model(settings))` → `deps = make_deps(settings, make_model(settings, Role.LAB_EXTRACT))`
- `:173` `make_model(settings),` → `make_model(settings, Role.LAB_REPORT),`
- `:220` `agent = build_chat_agent(make_model(settings), tools, system_prompt=prompt)` → `agent = build_chat_agent(make_model(settings, Role.WELLNESS_CHAT), tools, system_prompt=prompt)`
- `:296` `make_model(settings),` → `make_model(settings, Role.LAB_REPORT),`

`packages/tri-web/src/tri_web/runtime.py`: in `open_runtime`, replace

```python
    """Readiness, then servers, checkpointer, store, deps, graph; everything closes with the
    exit stack. `model` overrides make_model (tests)."""
```

with

```python
    """Readiness, then servers, checkpointer, store, deps, graph; everything closes with the
    exit stack. `model`, when given, replaces every role's model (tests)."""
```

replace `from tri_coach.graph.llm import make_model` with `from tri_core.llm import Role, make_model`, and replace

```python
        deps = make_deps(settings, model or make_model(settings), servers)
```

with

```python
        def models(role: Role) -> BaseChatModel:
            return model if model is not None else make_model(settings, role)

        deps = make_deps(settings, models, servers)
```

(`BaseChatModel` is already imported at the top of `runtime.py`.)

`scripts/design_eval.py`: replace `from tri_planning.graph.llm import make_model` with `from tri_core.llm import Role, make_model`, and `model=make_model(settings),` with `model=make_model(settings, Role.PLANNING_DESIGN),`. Plan 02 replaces this script with `tri-planning eval`.

`packages/tri-coach/tests/test_live.py`: replace `from tri_coach.graph.llm import make_model` with `from tri_core.llm import make_model`, and on line 30 `make_deps(settings, make_model(settings), servers),` with `make_deps(settings, lambda role: make_model(settings, role), servers),`.

`packages/tri-wellness/tests/test_live_pdf.py`: replace `from tri_wellness.graph.llm import make_model` with `from tri_core.llm import Role, make_model`, and on line 30 `make_model(settings)` with `make_model(settings, Role.LAB_EXTRACT)`.

- [ ] **Step 4: Eval metadata names the resolved model**

`settings.tri_model` is `None` unless pinned, so each eval records the model its role resolves to. Add `from tri_core.llm import Role, resolve` to each file's imports and replace:

- `packages/tri-analyze/src/tri_analyze/evals/run.py:83` `metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model},` → `metadata={"prompt_version": PROMPT_VERSION, "model": resolve(settings, Role.ANALYST).model},`
- `packages/tri-coach/src/tri_coach/evals/run.py:71` the same line → `"model": resolve(settings, Role.COACH).model`
- `packages/tri-nutrition/src/tri_nutrition/evals/run.py:78` the same line → `"model": resolve(settings, Role.NUTRITION_FUEL).model`
- `packages/tri-wellness/src/tri_wellness/evals/run.py:79` `"model": settings.tri_model,` → `"model": resolve(settings, Role.LAB_REPORT).model,`

Until plan 02, each eval's judge still shares the target's model; plan 02 gives the judge its own role.

- [ ] **Step 5: Delete the five copies**

```bash
git rm packages/tri-analyze/src/tri_analyze/llm.py packages/tri-analyze/tests/test_llm.py packages/tri-coach/src/tri_coach/graph/llm.py packages/tri-planning/src/tri_planning/graph/llm.py packages/tri-nutrition/src/tri_nutrition/graph/llm.py packages/tri-wellness/src/tri_wellness/graph/llm.py
```

`tri-analyze/tests/test_llm.py` is covered by `tri-core/tests/test_llm.py::test_make_model_builds_the_role_spec_with_its_metadata`, which checks the model id and output ceiling through the new `make_model`.

- [ ] **Step 6: Nothing reads the old names**

Run: `rg -n "tri_(analyze|coach|planning|nutrition|wellness)(\.graph)?\.llm\b|def make_model\b|settings\.tri_model\b" packages scripts`
Expected: only `packages/tri-core/src/tri_core/llm.py:` `def make_model(settings: Settings, role: Role) -> ChatAnthropic:`.

Run: `rg -n "make_model\(settings\)" packages scripts`
Expected: no output.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+33 passed` (981: one test deleted), same skips, ruff clean, `mypy` `Success`. `scripts/` is not type-checked; `uv run python -c "import runpy, sys; sys.argv=['x','--help']; runpy.run_path('scripts/design_eval.py', run_name='__main__')"` prints the argparse usage without an `ImportError`.

- [ ] **Step 8: Commit**

```bash
git add -A packages scripts
git commit -m "refactor: every model from tri_core.llm.make_model; coach deps take a role provider"
```

---

### Task 8: Docs, final checks

**Files:**
- Modify: `.env.example`, `packages/tri-core/README.md`, `packages/tri-analyze/README.md`, `packages/tri-planning/README.md`
- Modify: `docs/architecture/harness.md`, `docs/architecture/harness/layers.svg`, `docs/architecture/harness/packages.svg`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: nothing new.

- [ ] **Step 1: `.env.example`**

Replace lines 19–20:

```
# Agent model (used later)
TRI_MODEL=claude-opus-5
```

with:

```
# Models (tri_core/llm.py). Every role runs claude-opus-5 at its default effort unless set here.
# TRI_MODEL pins every role at once; leave it unset so each role uses its own default.
# TRI_MODEL=
# One role: TRI_MODEL_<ROLE> and TRI_EFFORT_<ROLE> (low, medium, high, xhigh, max). Roles:
# COACH, ANALYST, WELLNESS_CHAT, PLANNING_AGENT, PLANNING_DESIGN, NUTRITION_AGENT, NUTRITION_FUEL,
# LAB_EXTRACT, LAB_REPORT, JUDGE. PLANNING_DESIGN, NUTRITION_FUEL, LAB_EXTRACT and JUDGE run
# structured output and take no effort.
# TRI_MODEL_ANALYST=claude-sonnet-5
# TRI_EFFORT_ANALYST=medium
# Models tried in order when the primary is overloaded or down; empty disables fallback.
# Default: the first two of claude-opus-5, claude-opus-4-8, claude-sonnet-5 that differ from it.
# TRI_MODEL_FALLBACKS=claude-opus-4-8,claude-sonnet-5
```

- [ ] **Step 2: READMEs**

`packages/tri-core/README.md`: replace

```
ETL behind `tri sync`), `tri_core.harness` (the agent harness every package builds on), and
```

with

```
ETL behind `tri sync`), `tri_core.llm` (the model for each role, its effort and its Claude
fallbacks), `tri_core.harness` (the agent harness every package builds on), and
```

and in the Harness table's `harness.agents` row replace

```
Prompt caching is always the last middleware.
```

with

```
Every agent ends with `claude_fallback` (from `tri_core.llm`) and then prompt caching, which is always last.
```

`packages/tri-analyze/README.md`: replace lines 23–25

```
`llm.make_model` wraps Claude in `ChatAnthropic` (no `thinking` parameter; adaptive thinking is
the model default). `agent.build_agent(model, tools, checkpointer)` builds through `tri_core.harness.agents.build_chat_agent`, which calls `create_agent` with
two middlewares and an `InMemorySaver`, and returns the graph with a run config: tag `analyst`
```

with

```
`tri_core.llm.make_model(settings, Role.ANALYST)` wraps Claude in `ChatAnthropic` with the
analyst role's model, effort and fallback chain. `agent.build_agent(model, tools, checkpointer)` builds through `tri_core.harness.agents.build_chat_agent`, which calls `create_agent` with
three middlewares and an `InMemorySaver`, and returns the graph with a run config: tag `analyst`
```

delete line 109:

```
  llm.py              make_model, MAX_TOKENS
```

and replace line 189:

```
- **Model or cost:** `TRI_MODEL` in `.env`; `MAX_TOKENS` in `llm.py`.
```

with

```
- **Model or cost:** `TRI_MODEL_ANALYST` and `TRI_EFFORT_ANALYST` in `.env` (see `.env.example`);
  the defaults and output ceilings are in `tri_core/llm.py`.
```

`packages/tri-planning/README.md`: in line 111 replace `` `llm.py` (model), `` with nothing (the line keeps `` `deps.py` (GraphDeps), `nodes/` (one file per node), ``).

- [ ] **Step 3: Harness map**

`docs/architecture/harness.md`: in the "Inner loop" bullet replace

```
Its middleware runs in a fixed order: `one_tool_call_at_a_time`, then prompt caching last.
```

with

```
Its middleware runs in a fixed order: `one_tool_call_at_a_time`, then `claude_fallback`, which retries an overloaded or unavailable call on the role's next Claude model, then prompt caching last.
```

In the module table's `agents` row replace

```
Prompt caching is always the last middleware.
```

with

```
Every agent ends with `claude_fallback` and then prompt caching, which is always last.
```

In "Rules to keep", after the `create_agent` rule, add:

```
- **Build models with `tri_core.llm.make_model(settings, Role.<ROLE>)`.** Each role has its own model, effort and fallback chain; `.env.example` lists the overrides. Structured-output calls go through `structured()`, the lab report stream through `streaming()`, so they fall back too. Roles that run structured output take no effort.
```

`docs/architecture/harness/layers.svg`: replace the middleware pills

```xml
  <text class="m10" x="538" y="410">middleware, in order</text>
  <rect class="b-n" x="538" y="418" width="124" height="20" rx="10"/>
  <text class="ss" x="600" y="432" text-anchor="middle">1 · one call per step</text>
  <rect class="b-n" x="538" y="444" width="124" height="20" rx="10"/>
  <text class="ss" x="600" y="458" text-anchor="middle">2 · prompt caching</text>
```

with

```xml
  <text class="m10" x="538" y="402">middleware, in order</text>
  <rect class="b-n" x="538" y="408" width="124" height="20" rx="10"/>
  <text class="ss" x="600" y="422" text-anchor="middle">1 · one call per step</text>
  <rect class="b-n" x="538" y="432" width="124" height="20" rx="10"/>
  <text class="ss" x="600" y="446" text-anchor="middle">2 · Claude fallback</text>
  <rect class="b-n" x="538" y="456" width="124" height="20" rx="10"/>
  <text class="ss" x="600" y="470" text-anchor="middle">3 · prompt caching</text>
```

and in its `<desc>` replace `with one tool call per step and prompt caching last.` with `with one tool call per step, a Claude fallback, and prompt caching last.`

`docs/architecture/harness/packages.svg`:
- in `<desc>` replace ` Every package except tri-web carries its own make_model.` with ` Every model comes from tri_core.llm.make_model.`
- delete the five `make_model` boxes, each a pair like:

```xml
  <rect class="b-dup" x="35" y="116" width="120" height="20" rx="2"/>
  <text class="m10" x="95" y="130" text-anchor="middle">make_model</text>
```

  (the pairs at x = 35, 197, 359, 521, 683)
- replace the key's first entry

```xml
  <rect class="b-dup" x="20" y="386" width="40" height="16" rx="2"/>
  <text class="ss" x="70" y="398">one copy per package</text>
  <path class="ln-acc" d="M230 394 H266" marker-end="url(#packages-c)"/>
  <text class="ss" x="276" y="398">imports from the harness</text>
```

  with

```xml
  <path class="ln-acc" d="M20 394 H56" marker-end="url(#packages-c)"/>
  <text class="ss" x="66" y="398">imports from the harness</text>
```

- remove the now-unused `.b-dup` style line.

Validate: `xmllint --noout docs/architecture/harness/layers.svg docs/architecture/harness/packages.svg` prints nothing.

- [ ] **Step 4: Vault copies**

Copy each edited markdown file to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same path>`: `packages/tri-core/readme.md`, `packages/tri-analyze/readme.md`, `packages/tri-planning/readme.md`, `docs/architecture/harness.md`, and the two SVGs to `docs/architecture/harness/`. Create directories as needed.

- [ ] **Step 5: Final checks**

Run: `git diff --name-only main...HEAD`
Expected: only paths from "Files this plan may touch".

Run: `rg -n "TRI_MODEL=claude|MAX_TOKENS|llm\.py|make_model" --glob '*.md' . --glob '!docs/superpowers/**' --glob '!**/node_modules/**'`
Expected: only `docs/architecture/harness.md` (the new rule) and `packages/tri-analyze/README.md` / `packages/tri-core/README.md` lines this task wrote.

- [ ] **Step 6: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+33 passed` (981), same skips, `1 warning`, ruff clean, `mypy` `Success`. This plan adds no build step; `web/` is untouched.

- [ ] **Step 7: Commit**

```bash
git add .env.example packages/tri-core/README.md packages/tri-analyze/README.md packages/tri-planning/README.md docs/architecture
git commit -m "docs: model routing in .env.example, READMEs and the harness map"
```

**After merge (Brian):** remove `TRI_MODEL=claude-opus-5` from your own `.env`, or every role stays pinned to it (harmless today, since it is also every role's default, but it would override plan 02's tuned defaults).

---

## Self-review against the spec

- **§4 layout:** `config.py` (Task 1), `llm.py` (Tasks 2–4), `test_llm.py` (Tasks 2–4), five `llm.py` deleted (Task 7), `harness/agents.py` (Task 3). The eval pieces of §4 (`tri-planning` `evals/run.py`, `eval` command, `langsmith` dependency, `scripts/design_eval.py` deletion) are plan 02.
- **§5.1:** every name in Tasks 2–4, plus `STRUCTURED_ROLES` (amendment). `claude_fallback` is a subclass instance (amendment). `Effort` is defined in `tri_core.config` and re-exported by `tri_core.llm`, since `Settings` needs it.
- **§5.2:** Task 1, ten explicit pairs plus `tri_model_fallbacks`.
- **§5.3:** Task 5 (planning `design_model`, nutrition `fuel_model`), Task 7 (coach provider, `open_runtime`, every CLI call site, `scripts/design_eval.py`, live tests). `make_test_deps` and fixtures unchanged.
- **§6.1:** `resolve` steps 1–5 in Task 2, including the structured-role rule; `make_model` raises before any call.
- **§6.2:** every role on opus-5 / default in `DEFAULTS`; targets are plan 02.
- **§6.3:** `fallbacks_of` (Task 2), `claude_fallback` before caching (Task 3), `structured` / `streaming` (Task 4) adopted at every site (Tasks 5–6), logging with and without the error class.
- **§6.4:** non-retryable errors raise at once (Task 3 and 4 tests); invalid override raises `ValueError` from `make_model` (Task 2).
- **§7:** plan 02; Task 7 Step 4 keeps the eval metadata truthful in between.
- **§8:** `test_llm.py` covers resolve, validation, make_model, fallbacks_of, claude_fallback and the helpers; `test_config.py` covers the new default and fields; `tri-analyze/tests/test_llm.py` is replaced by the `make_model` case.
- **§10 docs:** `.env.example`, `tri-analyze/README.md`; plus the README and harness-map lines the re-check found.
- **Test count:** B = 948; +2 (Task 1), +13 (Task 2), +6 (Task 3), +7 (Task 4), +4 (Task 5), +2 (Task 6), −1 (Task 7): 981.
