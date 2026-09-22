# Model routing Plan 2 of 2: Eval wiring and tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every eval its target's own model and the judge its own model, record which models each experiment ran on, add `tri-planning eval` in place of `scripts/design_eval.py`, and set out the athlete-run tuning that decides each role's default.

**Architecture:** Each package's `run_eval` takes a `ModelProvider` (role → model) instead of one model. The target builds from its role (`analyst`, `coach`, `nutrition_fuel`, `lab_report`, `planning_design`) and each judge from `judge`. A small `tri_core.llm.eval_metadata` builds the `model` / `effort` / `judge_model` metadata from `resolve`, so every package records the same keys. `tri-planning` gets the same `evals/run.py` + `eval` command shape as its siblings. Tuning is manual: the athlete runs baseline and candidate experiments and adopts a candidate only when it passes the gate, each adoption a one-line `DEFAULTS` change.

**Tech Stack:** Python 3.12, uv workspace, langsmith 0.12 (`Client`, `aevaluate`), Typer (`CliRunner` in tests), `tri_core.llm` from plan 1, pytest with `pytest-asyncio` in auto mode, `tri_core.testing.ScriptedChatModel`.

**Spec:** `docs/superpowers/specs/2026-09-15-model-routing-design.md`, as amended 2026-09-22 (§11). This plan implements §7 (eval wiring, tuning procedure and gate) and the plan 02 part of §10.

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed. Every command runs from the worktree root as `uv run ...`.
- **Prerequisite: plan 1 is merged on `main`.** From the main checkout, both must succeed:

  ```bash
  test -f packages/tri-core/src/tri_core/llm.py && ! test -e packages/tri-planning/src/tri_planning/graph/llm.py && echo "plan 1 is on main"
  grep -n "def make_model(settings: Settings, role: Role)" packages/tri-core/src/tri_core/llm.py
  ```
- **Execute in a sibling worktree:** `git worktree add ../triathlon_agent-routing-02 -b feat/model-routing-02 main`, copy `.env`, then `uv sync`. Other Claude sessions share the main checkout.
- **Baseline B:** run `uv run pytest -q` before Task 1. Plan 1 ends at `981 passed, 6 skipped, 1 warning`; if it differs, record the actual number and shift every expected count below by the same amount.
- **"Before" code in this plan is plan 1's result.** Plan 1 Task 7 Step 4 left each eval `run.py` with `from tri_core.llm import Role, resolve` and `"model": resolve(settings, Role.<TARGET>).model` in its metadata. Re-read each file before editing; if a before-block does not match, stop and report.
- **No change to what an eval measures.** Datasets, cases, evaluators, prompts and experiment prefixes stay as they are, except that `tri-planning`'s eval moves from the script to the CLI (keeping the dataset `tri-planning-design-weeks`).
- **Judges stay on the `judge` role, which is never tuned** (spec §6.2), so experiments across candidates stay comparable. `tri-wellness` has no judge.
- **Test rules:** the existing eval CLI tests stub `run_eval(settings, model, **kw)` positionally; they keep working unchanged when the second parameter becomes `models`. No existing assertion is edited.
- **Files this plan may touch:**
  - `packages/tri-core/src/tri_core/llm.py`, `packages/tri-core/tests/test_llm.py`
  - `packages/tri-analyze/src/tri_analyze/{evals/run.py,cli.py}`, `packages/tri-analyze/tests/test_evals.py`
  - `packages/tri-coach/src/tri_coach/{evals/run.py,cli.py}`, `packages/tri-coach/tests/test_evals.py`
  - `packages/tri-nutrition/src/tri_nutrition/{evals/run.py,cli.py}`, `packages/tri-nutrition/tests/test_evals.py`
  - `packages/tri-wellness/src/tri_wellness/{evals/run.py,cli.py}`, `packages/tri-wellness/tests/test_evals.py`
  - `packages/tri-planning/src/tri_planning/{evals/run.py (new),cli.py}`, `packages/tri-planning/pyproject.toml`, `uv.lock`, `packages/tri-planning/tests/{test_cli.py (new),test_eval_run.py (new)}`, `packages/tri-planning/README.md`
  - `scripts/design_eval.py` (deleted)
  - Task 3 only: `packages/tri-core/src/tri_core/llm.py` `DEFAULTS` and `packages/tri-core/tests/test_llm.py`'s launch-defaults test, one role per commit.
- **Definition of done per task, in order:**
  1. `uv run ruff format packages scripts`
  2. `uv run ruff check --fix packages scripts`
  3. `uv run pytest -q`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `uv run mypy`

  The only acceptable pytest warning is the existing langsmith `DeprecationWarning`. Never add `# type: ignore`.
- **Commits:** git commits are permitted (Brian's standing permission). Commit once per task on `feat/model-routing-02`, ending every message with the executing model's attribution line (the `Co-Authored-By:` line the session's git attribution reminder gives).
- No "LangChain lesson:" framing in docstrings or comments.
- Every markdown file edited is also copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>` with a kebab-case name (`readme.md` for READMEs).
- **Every eval run costs API money.** Tasks 1 and 2 never call a model: their tests use fakes and stub LangSmith. Only Brian runs Task 3.

### Facts verified while writing this plan (against `main` @ b4c7efa plus plan 1, 2026-09-22)

1. Each package keeps its own `ensure_dataset`, `pass_rates` and `render_pass_rates` in `evals/run.py`; `tri_coach.evals.run` imports `pass_rates` from `tri_nutrition.evals.run`.
2. `run_eval` signatures today: analyze `(settings, model, *, judge=True, prefix=None, recreate=False, log=print) -> tuple[dict[str, float], int]`; coach and nutrition the same shape returning `dict[str, float]`; wellness `(settings, model, *, prefix=None, recreate=False, log=print) -> dict[str, float]` with no judge. Each passes one `model` to `make_target` and, when `judge`, to `make_judge` / `make_brief_judge` / `make_fuel_judge`.
3. The eval CLIs: `tri-analyze eval` (no `--judge` flag), `tri-coach eval --judge/--no-judge`, `tri-nutrition eval --judge/--no-judge`, `tri-wellness eval`. Each exits 2 without `LANGSMITH_API_KEY` or `ANTHROPIC_API_KEY` and 1 when any rate is below 100% (analyze also on errored examples).
4. `tri_planning.evals.design_eval` has `build_examples(today)`, `validator_pass(inputs, outputs)` and `design_target(deps)`; its examples carry `inputs` and `metadata` but no `outputs`. `tri_planning` has no `PROMPT_VERSION`, no `evals/run.py`, no `eval` command, no `tests/test_cli.py`, and does not list `langsmith` (siblings pin `langsmith>=0.12,<1`; 0.12.2 is already in `uv.lock`).
5. `scripts/design_eval.py` runs the design eval against dataset `tri-planning-design-weeks` with experiment prefix `design-<version>`; `packages/tri-planning/README.md:75` documents it. Nothing else imports it.
6. `tri_planning/cli.py` calls `get_planning_settings()` at import (line 22) to set `LANGSMITH_PROJECT`; tests patch `cli.get_planning_settings` the same way `tri-analyze/tests/test_cli.py` patches `cli.get_analyze_settings`.
7. `design_week` never touches `deps.connect`; the eval target needs only `deps.design_model or deps.model`, so `run_eval` asks the provider for `PLANNING_DESIGN` once and uses it for both fields.

### Stop conditions

Stop and report to Brian without working around it if:
- a before-block in Task 1 does not match plan 1's result;
- `uv lock` changes any resolved `version =` line when `langsmith` is added to `tri-planning`;
- an existing eval test fails after Task 1.

---

## File Structure

```
packages/tri-core/src/tri_core/llm.py        Task 1: eval_metadata
packages/tri-*/src/*/evals/run.py            Task 1: run_eval(settings, models, ...); metadata via eval_metadata
packages/tri-*/src/*/cli.py                  Task 1: eval passes lambda role: make_model(settings, role)
packages/tri-*/tests/test_evals.py           Task 1: run_eval wiring with a stubbed LangSmith
packages/tri-planning/src/tri_planning/
  evals/run.py                               Task 2: dataset, pass rates, run_eval
  cli.py                                     Task 2: `eval`
packages/tri-planning/tests/
  test_eval_run.py, test_cli.py              Task 2
packages/tri-planning/pyproject.toml, uv.lock Task 2: langsmith
scripts/design_eval.py                       Task 2: deleted
packages/tri-core/src/tri_core/llm.py        Task 3 (Brian): DEFAULTS, one role per adoption
```

---

### Task 1: Every eval runs its target and its judge on their own roles

**Files:**
- Modify: `packages/tri-core/src/tri_core/llm.py` (append), `packages/tri-core/tests/test_llm.py` (append)
- Modify: `evals/run.py` and `cli.py` in `tri-analyze`, `tri-coach`, `tri-nutrition`, `tri-wellness`
- Test: `tests/test_evals.py` in the same four packages (append)

**Interfaces:**
- Consumes (plan 1): `Role`, `ModelProvider`, `resolve`, `make_model`.
- Produces:
  - `tri_core.llm.eval_metadata(settings: Settings, target: Role, *, judge: bool) -> dict[str, Any]` → `{"model": <target model>, "effort": <target effort>}` plus `"judge_model": <judge model>` when `judge`
  - `tri_analyze.evals.run.run_eval(settings, models: ModelProvider, *, judge=True, prefix=None, recreate=False, log=print) -> tuple[dict[str, float], int]`
  - `tri_coach.evals.run.run_eval(settings, models: ModelProvider, *, judge=True, prefix=None, recreate=False, log=print) -> dict[str, float]`
  - `tri_nutrition.evals.run.run_eval(settings, models: ModelProvider, *, judge=True, prefix=None, recreate=False, log=print) -> dict[str, float]`
  - `tri_wellness.evals.run.run_eval(settings, models: ModelProvider, *, prefix=None, recreate=False, log=print) -> dict[str, float]`

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_llm.py` (add `eval_metadata` to its `tri_core.llm` import):

```python
def test_eval_metadata_names_the_target_and_judge_models():
    assert eval_metadata(settings(), Role.ANALYST, judge=True) == {
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }
    s = settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium")
    assert eval_metadata(s, Role.ANALYST, judge=False) == {
        "model": "claude-sonnet-5",
        "effort": "medium",
    }
```

Each package test below stubs LangSmith, so no network or key is needed. Add this helper block once to each of the four `tests/test_evals.py` files, importing `ScriptedChatModel` from `tri_core.testing` where the file does not already (ruff sorts the imports into the file's import block):

```python
from tri_core.llm import Role


class _FakeClient:
    def __init__(self, **kw):
        pass

    def has_dataset(self, **kw):
        return True


class _FakeResults:
    experiment_name = "exp"

    def __aiter__(self):
        async def rows():
            return
            yield

        return rows()


def _stub_langsmith(monkeypatch, run_module) -> dict:
    captured: dict = {}

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return _FakeResults()

    monkeypatch.setattr(run_module, "Client", _FakeClient)
    monkeypatch.setattr(run_module, "aevaluate", fake_aevaluate)
    return captured


def _recording_models():
    roles: list[Role] = []
    fake = ScriptedChatModel(script=[])

    def models(role: Role):
        roles.append(role)
        return fake

    return models, roles
```

`packages/tri-analyze/tests/test_evals.py` (import `tri_analyze.evals.run as analyze_run`, `from tri_analyze.config import AnalyzeSettings` and `from tri_analyze.prompts.analyst import PROMPT_VERSION` if not already imported):

```python
async def test_run_eval_uses_the_analyst_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, roles = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    assert await analyze_run.run_eval(settings, models, log=lambda m: None) == ({}, 0)
    assert sorted(roles) == sorted([Role.ANALYST, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }


async def test_run_eval_without_the_judge_records_no_judge_model(monkeypatch):
    captured = _stub_langsmith(monkeypatch, analyze_run)
    models, roles = _recording_models()
    settings = AnalyzeSettings(_env_file=None, langsmith_api_key="ls")
    await analyze_run.run_eval(settings, models, judge=False, log=lambda m: None)
    assert roles == [Role.ANALYST] and "judge_model" not in captured["metadata"]
```

`packages/tri-coach/tests/test_evals.py` (import `tri_coach.evals.run as coach_run`, `from tri_coach.config import CoachSettings`, `from tri_coach.prompts.coach import PROMPT_VERSION`):

```python
async def test_run_eval_uses_the_coach_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, coach_run)
    models, roles = _recording_models()
    settings = CoachSettings(_env_file=None, langsmith_api_key="ls")
    assert await coach_run.run_eval(settings, models, log=lambda m: None) == {}
    assert sorted(roles) == sorted([Role.COACH, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }
```

`packages/tri-nutrition/tests/test_evals.py` (import `tri_nutrition.evals.run as nutrition_run`, `from tri_nutrition.config import NutritionSettings`, `from tri_nutrition.prompts.fuel import PROMPT_VERSION`):

```python
async def test_run_eval_uses_the_fuel_and_judge_roles(monkeypatch):
    captured = _stub_langsmith(monkeypatch, nutrition_run)
    models, roles = _recording_models()
    settings = NutritionSettings(_env_file=None, langsmith_api_key="ls")
    assert await nutrition_run.run_eval(settings, models, log=lambda m: None) == {}
    assert sorted(roles) == sorted([Role.NUTRITION_FUEL, Role.JUDGE])
    assert captured["metadata"] == {
        "prompt_version": PROMPT_VERSION,
        "model": "claude-opus-5",
        "effort": None,
        "judge_model": "claude-opus-5",
    }
```

`packages/tri-wellness/tests/test_evals.py` (import `tri_wellness.evals.run as wellness_run`, `from tri_wellness.config import WellnessSettings`, `from tri_wellness.prompts.report import PROMPT_VERSION`):

```python
async def test_run_eval_uses_the_lab_report_role_and_no_judge(monkeypatch):
    captured = _stub_langsmith(monkeypatch, wellness_run)
    models, roles = _recording_models()
    settings = WellnessSettings(_env_file=None, tri_athlete_sex="male", langsmith_api_key="ls")
    assert await wellness_run.run_eval(settings, models, log=lambda m: None) == {}
    assert roles == [Role.LAB_REPORT]
    meta = captured["metadata"]
    assert meta["prompt_version"] == PROMPT_VERSION and "ranges_version" in meta
    assert meta["model"] == "claude-opus-5" and meta["effort"] is None
    assert "judge_model" not in meta
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_llm.py packages/tri-analyze/tests/test_evals.py packages/tri-coach/tests/test_evals.py packages/tri-nutrition/tests/test_evals.py packages/tri-wellness/tests/test_evals.py -q`
Expected: `test_llm.py` fails to import `eval_metadata`; the package tests fail because `run_eval` calls `models` as a model (e.g. `TypeError` or `AttributeError` from `make_target`) and the metadata lacks `effort`.

- [ ] **Step 3: `eval_metadata`**

Append to `packages/tri-core/src/tri_core/llm.py`:

```python
def eval_metadata(settings: Settings, target: Role, *, judge: bool) -> dict[str, Any]:
    """What an eval experiment records about its models: the target role's model and effort,
    and the judge's model when a judge runs."""
    spec = resolve(settings, target)
    out: dict[str, Any] = {"model": spec.model, "effort": spec.effort}
    if judge:
        out["judge_model"] = resolve(settings, Role.JUDGE).model
    return out
```

- [ ] **Step 4: The four `run_eval`s take a provider**

In each `run.py`, replace the `from tri_core.llm import Role, resolve` import (added by plan 1) with `from tri_core.llm import ModelProvider, Role, eval_metadata`, and remove `from langchain_core.language_models import BaseChatModel` if nothing else in the file uses it (`ruff check --fix` reports it).

`packages/tri-analyze/src/tri_analyze/evals/run.py`: replace

```python
async def run_eval(
    settings: AnalyzeSettings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": resolve(settings, Role.ANALYST).model},
```

with

```python
async def run_eval(
    settings: AnalyzeSettings,
    models: ModelProvider,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples. The analyst
    runs on its role's model and the judge on the judge role's."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(models(Role.JUDGE)))
    results = await aevaluate(
        make_target(models(Role.ANALYST)),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}",
        metadata={
            "prompt_version": PROMPT_VERSION,
            **eval_metadata(settings, Role.ANALYST, judge=judge),
        },
```

`packages/tri-coach/src/tri_coach/evals/run.py`: replace

```python
async def run_eval(
    settings: Settings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [routing_accuracy, no_unrequested_adjustment]
    if judge:
        evaluators.append(make_brief_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"coach-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": resolve(settings, Role.COACH).model},
```

with

```python
async def run_eval(
    settings: Settings,
    models: ModelProvider,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [routing_accuracy, no_unrequested_adjustment]
    if judge:
        evaluators.append(make_brief_judge(models(Role.JUDGE)))
    results = await aevaluate(
        make_target(models(Role.COACH)),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"coach-v{PROMPT_VERSION}",
        metadata={
            "prompt_version": PROMPT_VERSION,
            **eval_metadata(settings, Role.COACH, judge=judge),
        },
```

`packages/tri-nutrition/src/tri_nutrition/evals/run.py`: replace

```python
    model: BaseChatModel,
```

```python
    if judge:
        evaluators.append(make_fuel_judge(model))
    results = await aevaluate(
        make_target(model),
```

```python
        metadata={"prompt_version": PROMPT_VERSION, "model": resolve(settings, Role.NUTRITION_FUEL).model},
```

with, respectively,

```python
    models: ModelProvider,
```

```python
    if judge:
        evaluators.append(make_fuel_judge(models(Role.JUDGE)))
    results = await aevaluate(
        make_target(models(Role.NUTRITION_FUEL)),
```

```python
        metadata={
            "prompt_version": PROMPT_VERSION,
            **eval_metadata(settings, Role.NUTRITION_FUEL, judge=judge),
        },
```

(If `ruff format` wrapped plan 1's metadata line, match the wrapped form; the content is the same.)

`packages/tri-wellness/src/tri_wellness/evals/run.py`: replace

```python
    model: BaseChatModel,
```

```python
        make_target(model, registry),
```

```python
            "model": resolve(settings, Role.LAB_REPORT).model,
```

with, respectively,

```python
    models: ModelProvider,
```

```python
        make_target(models(Role.LAB_REPORT), registry),
```

```python
            **eval_metadata(settings, Role.LAB_REPORT, judge=False),
```

- [ ] **Step 5: The four eval commands pass a provider**

In each package's `cli.py` `_eval`, replace the model argument (plan 1 left `make_model(settings, Role.<TARGET>),`) with `lambda role: make_model(settings, role),` and let `ruff check --fix` drop the then-unused `Role` from that function's `from tri_core.llm import ...` line:

- `packages/tri-analyze/src/tri_analyze/cli.py`: `make_model(settings, Role.ANALYST),` in `_eval` → `lambda role: make_model(settings, role),`
- `packages/tri-coach/src/tri_coach/cli.py`: `make_model(settings, Role.COACH),` → `lambda role: make_model(settings, role),`
- `packages/tri-nutrition/src/tri_nutrition/cli.py`: `make_model(settings, Role.NUTRITION_FUEL),` in `_eval` → `lambda role: make_model(settings, role),`
- `packages/tri-wellness/src/tri_wellness/cli.py`: `make_model(settings, Role.LAB_REPORT),` in `_eval` → `lambda role: make_model(settings, role),`

Only the `_eval` call changes; the other `make_model(settings, Role.…)` calls in these files stay.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_llm.py packages/tri-analyze packages/tri-coach packages/tri-nutrition packages/tri-wellness -q`
Expected: all pass. The existing CLI tests' `run_eval(settings, model, **kw)` stubs still work.

Run: `rg -n "resolve\(settings, Role\.\w+\)\.model|run_eval\(\s*settings,\s*make_model" packages`
Expected: no output.

- [ ] **Step 7: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+6 passed` (987), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 8: Commit**

```bash
git add packages/tri-core packages/tri-analyze packages/tri-coach packages/tri-nutrition packages/tri-wellness
git commit -m "feat(evals): targets and judges run on their own roles; metadata names both models"
```

---

### Task 2: `tri-planning eval` replaces `scripts/design_eval.py`

**Files:**
- Create: `packages/tri-planning/src/tri_planning/evals/run.py`
- Modify: `packages/tri-planning/src/tri_planning/cli.py`, `packages/tri-planning/pyproject.toml`, `uv.lock`, `packages/tri-planning/README.md`
- Delete: `scripts/design_eval.py`
- Test: `packages/tri-planning/tests/test_eval_run.py`, `packages/tri-planning/tests/test_cli.py` (both new)

**Interfaces:**
- Consumes: `tri_planning.evals.design_eval.{build_examples, validator_pass, design_target}`; `tri_planning.graph.deps.GraphDeps` with `design_model` (plan 1); `tri_core.llm.{ModelProvider, Role, eval_metadata, make_model}`.
- Produces:
  - `tri_planning.evals.run.DATASET_NAME = "tri-planning-design-weeks"`
  - `case_examples(today: date) -> list[dict[str, Any]]`, `ensure_dataset(client: Client, *, recreate: bool = False) -> None`, `pass_rates(rows) -> dict[str, float]`, `render_pass_rates(rates, n) -> str`
  - `run_eval(settings: PlanningSettings, models: ModelProvider, *, prefix: str | None = None, recreate: bool = False, log=print) -> dict[str, float]`
  - `tri-planning eval [--prefix TEXT] [--recreate-dataset]`: exit 2 without `LANGSMITH_API_KEY` or `ANTHROPIC_API_KEY`; 0 when every rate is 100%, else 1.

- [ ] **Step 1: Add `langsmith` to tri-planning**

In `packages/tri-planning/pyproject.toml`, add `"langsmith>=0.12,<1",` to `dependencies` (the same pin the sibling packages use).

Run: `uv lock && git diff uv.lock | grep '^[-+]version'`
Expected: no output (only tri-planning's dependency list changes). Then `uv sync`.

- [ ] **Step 2: Write the failing tests**

Create `packages/tri-planning/tests/test_eval_run.py`:

```python
from datetime import date

import tri_planning.evals.run as planning_run
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel
from tri_planning.config import PlanningSettings
from tri_planning.evals.run import DATASET_NAME, case_examples, render_pass_rates


def test_the_dataset_keeps_the_scripts_name_and_examples_carry_empty_outputs():
    assert DATASET_NAME == "tri-planning-design-weeks"
    ex = case_examples(date(2026, 9, 14))
    assert len(ex) >= 16
    assert all(e["outputs"] == {} and "goal" in e["inputs"] and "phase" in e["metadata"] for e in ex)


def test_render_pass_rates_lists_each_key():
    out = render_pass_rates({"validator_pass": 0.75}, 4)
    assert out.splitlines() == ["pass rate over 4 examples:", "  validator_pass             75%"]


async def test_run_eval_designs_on_the_design_role(monkeypatch):
    captured: dict = {}

    class FakeClient:
        def __init__(self, **kw):
            pass

        def has_dataset(self, **kw):
            return True

    class FakeResults:
        experiment_name = "exp"

        def __aiter__(self):
            async def rows():
                return
                yield

            return rows()

    async def fake_aevaluate(target, **kw):
        captured.update(kw)
        return FakeResults()

    monkeypatch.setattr(planning_run, "Client", FakeClient)
    monkeypatch.setattr(planning_run, "aevaluate", fake_aevaluate)
    roles: list[Role] = []

    def models(role: Role):
        roles.append(role)
        return ScriptedChatModel(script=[])

    settings = PlanningSettings(_env_file=None, langsmith_api_key="ls")
    assert await planning_run.run_eval(settings, models, log=lambda m: None) == {}
    assert roles == [Role.PLANNING_DESIGN]
    assert captured["experiment_prefix"] == "design"
    assert captured["metadata"] == {"model": "claude-opus-5", "effort": None}
    assert [e.__name__ for e in captured["evaluators"]] == ["validator_pass"]
```

Create `packages/tri-planning/tests/test_cli.py`:

```python
from typer.testing import CliRunner

from tri_planning import cli
from tri_planning.cli import app
from tri_planning.config import PlanningSettings

runner = CliRunner()


def test_help_lists_eval():
    assert "eval" in runner.invoke(app, ["--help"]).output


def test_eval_exits_2_without_langsmith_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key=None),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "LANGSMITH_API_KEY" in result.output


def test_eval_exits_2_without_anthropic_key(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key=None, langsmith_api_key="ls"),
    )
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 2 and "ANTHROPIC_API_KEY" in result.output


def test_eval_exit_code_follows_rates(monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_planning_settings",
        lambda: PlanningSettings(_env_file=None, anthropic_api_key="k", langsmith_api_key="ls"),
    )
    seen: list[dict] = []

    def stub(rates):
        async def run_eval(settings, models, **kw):
            seen.append(kw)
            kw["log"]("experiment: design-test")
            return rates

        monkeypatch.setattr("tri_planning.evals.run.run_eval", run_eval)

    stub({"validator_pass": 1.0})
    result = runner.invoke(app, ["eval", "--prefix", "try", "--recreate-dataset"])
    assert result.exit_code == 0 and "experiment: design-test" in result.output
    assert seen[-1]["prefix"] == "try" and seen[-1]["recreate"] is True
    stub({"validator_pass": 0.5})
    assert runner.invoke(app, ["eval"]).exit_code == 1
    stub({})
    assert runner.invoke(app, ["eval"]).exit_code == 1
    assert seen[-1]["prefix"] is None and seen[-1]["recreate"] is False
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_eval_run.py packages/tri-planning/tests/test_cli.py -q`
Expected: `test_eval_run.py` fails to import `tri_planning.evals.run`; in `test_cli.py`, `test_help_lists_eval` fails and the `eval` invocations exit 2 with "No such command".

- [ ] **Step 4: Write `evals/run.py`**

Create `packages/tri-planning/src/tri_planning/evals/run.py`:

```python
"""Create the LangSmith dataset of target weeks and run the design prompt over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY. The dataset keeps the name the earlier script used, so
experiments before and after this command compare. Each example costs one or two model calls."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from langsmith import Client, aevaluate

from tri_core.db.repo import Conn
from tri_core.llm import ModelProvider, Role, eval_metadata
from tri_planning.config import PlanningSettings
from tri_planning.evals.design_eval import build_examples, design_target, validator_pass
from tri_planning.graph.deps import GraphDeps

DATASET_NAME = "tri-planning-design-weeks"
DATASET_DESCRIPTION = "Target weeks for the tri-planning design prompt"


def case_examples(today: date) -> list[dict[str, Any]]:
    return [{**e, "outputs": {}} for e in build_examples(today)]


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples(date.today()))


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples:"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


def _no_database() -> AbstractContextManager[Conn]:
    raise RuntimeError("the design eval reads no database")


async def run_eval(
    settings: PlanningSettings,
    models: ModelProvider,
    *,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    """The pass rate per evaluator key. Weeks are designed on the planning_design role."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    designer = models(Role.PLANNING_DESIGN)  # design_week reads design_model; model is the required field
    deps = GraphDeps(
        model=designer,
        connect=_no_database,
        db_url=settings.database_url,
        design_model=designer,
    )
    results = await aevaluate(
        design_target(deps),
        data=DATASET_NAME,
        evaluators=[validator_pass],
        experiment_prefix=prefix or "design",
        metadata=eval_metadata(settings, Role.PLANNING_DESIGN, judge=False),
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
```

- [ ] **Step 5: The `eval` command**

In `packages/tri-planning/src/tri_planning/cli.py`, replace the first line

```python
"""Command-line entry points for the planning agent: chat, check-in, reset."""
```

with

```python
"""Command-line entry points for the planning agent: chat, check-in, reset, eval."""
```

and insert before `if __name__ == "__main__":`:

```python
@app.command(name="eval")
def eval_cmd(
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default design)"
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate-dataset",
        help="Delete and re-create the LangSmith dataset from the presets in code",
    ),
) -> None:
    """Design one week per example in the LangSmith dataset and print the validator pass rate
    (exit 1 when it is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(prefix=prefix, recreate=recreate)))


async def _eval(*, prefix: str | None, recreate: bool) -> int:
    from tri_core.llm import make_model
    from tri_planning.evals.run import run_eval

    settings = get_planning_settings()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings,
        lambda role: make_model(settings, role),
        prefix=prefix,
        recreate=recreate,
        log=lambda m: _out(m + "\n"),
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1
```

- [ ] **Step 6: Delete the script and update the README**

Run: `git rm scripts/design_eval.py`

In `packages/tri-planning/README.md`, replace line 75

```
uv run python scripts/design_eval.py --prompt-version v1         # LangSmith pass rate for the design prompt
```

with

```
uv run tri-planning eval [--prefix NAME] [--recreate-dataset]    # LangSmith pass rate for the design prompt
```

and copy the README to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/packages/tri-planning/readme.md`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-planning -q`
Expected: all pass, including the seven new tests.

Run: `rg -n "design_eval\.py|scripts/design_eval" --glob '!docs/superpowers/**' .`
Expected: no output.

- [ ] **Step 8: Definition of done**

Run the six commands from Global Constraints.
Expected: `B+13 passed` (994), same skips, ruff clean, `mypy` `Success`.

- [ ] **Step 9: Commit**

```bash
git add packages/tri-planning uv.lock
git commit -m "feat(planning): tri-planning eval replaces scripts/design_eval.py, same dataset"
```

---

### Task 3: Tuning runs and adopted defaults (Brian runs; every run costs API money)

**Files (per adoption):**
- Modify: `packages/tri-core/src/tri_core/llm.py` (`DEFAULTS`, one role)
- Modify: `packages/tri-core/tests/test_llm.py` (`test_every_role_launches_on_opus_5_at_default_effort`: the changed role's expectation)

**Interfaces:**
- Consumes: the eval commands from Tasks 1–2 and the env overrides from plan 1.
- Produces: at most one `DEFAULTS` change per gated role, each in its own commit.

This task is not delegated. Claude may prepare each adoption commit once Brian has run the experiments and shared the printed pass rates.

- [ ] **Step 1: Baselines on the launch defaults**

With no `TRI_MODEL*` or `TRI_EFFORT*` lines in `.env` (remove `TRI_MODEL=claude-opus-5` if it is still there):

```bash
uv run tri-analyze eval --prefix analyst-base
uv run tri-coach eval --prefix coach-base
uv run tri-nutrition eval --prefix fuel-base
uv run tri-wellness eval --prefix report-base
uv run tri-planning eval --prefix design-base
```

Record each command's printed `pass rate over N examples` block and (analyze) errored count.

- [ ] **Step 2: Candidates (spec §6.2, as amended)**

```bash
TRI_EFFORT_ANALYST=medium uv run tri-analyze eval --prefix analyst-opus5-med
TRI_MODEL_ANALYST=claude-sonnet-5 TRI_EFFORT_ANALYST=medium uv run tri-analyze eval --prefix analyst-sonnet5-med
TRI_EFFORT_COACH=high uv run tri-coach eval --prefix coach-opus5-high
TRI_MODEL_NUTRITION_FUEL=claude-sonnet-5 uv run tri-nutrition eval --prefix fuel-sonnet5
```

`planning_design` and `lab_report` stay unchanged; their baselines are recorded for later comparisons. `nutrition_fuel`, like every structured role, takes no effort. `wellness_chat`, `lab_extract` and `nutrition_agent` have no eval gate and stay on the launch default.

- [ ] **Step 3: Apply the gate**

For each candidate against its baseline: passing count per evaluator key = rate × N. Adopt only if **no key's passing count drops by more than one example** and **the errored count does not rise**. When two analyst candidates both pass, prefer the cheaper one (Sonnet 5 over Opus 5).

- [ ] **Step 4: One commit per adopted default**

For an adopted role, change its single `DEFAULTS` line in `packages/tri-core/src/tri_core/llm.py`, for example:

```python
    Role.ANALYST: ModelSpec(model="claude-sonnet-5", effort="medium", max_tokens=16000, fallbacks=()),
```

and in `packages/tri-core/tests/test_llm.py` change `test_every_role_launches_on_opus_5_at_default_effort` so that role's expectation matches, for example:

```python
def test_every_role_launches_on_its_default():
    assert set(DEFAULTS) == set(Role)
    tuned = {Role.ANALYST: ("claude-sonnet-5", "medium")}
    for role in Role:
        spec = resolve(settings(), role)
        assert (spec.model, spec.effort) == tuned.get(role, ("claude-opus-5", None))
    assert resolve(settings(), Role.LAB_EXTRACT).max_tokens == 32000
    assert resolve(settings(), Role.LAB_REPORT).max_tokens == 32000
    assert resolve(settings(), Role.COACH).max_tokens == 16000
```

(the fallback-chain assertion moves to `test_default_chain_is_the_first_two_other_models`, which already covers it). Run the six Definition of Done commands, then commit with both experiment names:

```bash
git commit -am "tune(analyst): claude-sonnet-5 / medium (analyst-sonnet5-med vs analyst-base)" -m "<the executing model's Co-Authored-By line>"
```

A candidate that fails the gate changes nothing; record the experiment names in the tri-harness/model-routing notes instead.

---

## Self-review against the spec

- **§7.1:** every `run_eval` takes `models: ModelProvider` (Task 1); targets on `analyst`, `coach`, `nutrition_fuel`, `lab_report`, judges on `judge`; wellness has no judge (amendment). Metadata from `resolve` via `eval_metadata`: `model`, `effort`, and `judge_model` only when a judge runs (amendment). `tri-planning eval [--prefix] [--recreate-dataset]` with `build_examples`, `design_target` on `design_model=models(PLANNING_DESIGN)`, `validator_pass`, the sibling helper shape, exit 2 without either key (Task 2); dataset `tri-planning-design-weeks`, default prefix `design`, `langsmith` dependency, script deleted (amendment).
- **§7.2:** baseline, candidate, gate and one-line adoption commits (Task 3), run by the athlete.
- **§4:** `tri-planning` `evals/run.py`, `cli.py` `eval`, `pyproject.toml`, `scripts/design_eval.py` deleted (Task 2).
- **§8:** `tri-planning` gains `tests/test_cli.py` with the exit-2 tests (Task 2).
- **§6.2 targets:** the candidates in Task 3 Step 2 are exactly the amended table's; `judge` is never tuned.
- **Test count:** B = 981; +6 (Task 1: 1 tri-core, 2 analyze, 1 each coach, nutrition, wellness), +7 (Task 2: 3 run, 4 CLI): 994. Task 3 changes no count.
