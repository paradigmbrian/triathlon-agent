# Eval Cost Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Price 1-hour cache writes at their own rate, and mark every subset and rescore run `gate: false` with a `not a gate run` line, on top of the eval-cost work already on `main` (`9f4f048`).

**Architecture:** Two small changes to code that exists. `tri_core.eval_usage` counts 1-hour cache writes apart from 5-minute ones and prices them at 2× input. `tri_core.evals.finish_run` logs `not a gate run` when the metadata has `gate: false`; `tri_core.eval_select.run_rescore` and each package's `evals/run.py` set it. The original plan (`2026-09-28-eval-cost.md`) is the record of what shipped; don't re-run it.

**Tech Stack:** Python 3.12, uv workspace, langchain-anthropic 1.7.1 (`usage_metadata.input_token_details`), pytest (asyncio auto mode), ruff (line length 100), mypy strict.

**Spec:** `docs/superpowers/specs/2026-09-28-eval-cost-design.md` (§3.1–3.3, §4 Output, §5 Marking a subset, §7)

## Global Constraints

- Prices per MTok, unchanged: `claude-opus-5` $5 in / $25 out, `claude-opus-4-8` $5 / $25, `claude-sonnet-5` $2 / $10, `claude-haiku-4-5` $1 / $5. Cache reads cost 0.1× the input rate. Cache writes cost 1.25× for the 5-minute TTL (and for an unsplit `cache_creation`) and 2× for the 1-hour TTL. `PRICES_AS_OF = "2026-09-28"` sits next to the table.
- langchain-anthropic zeroes `cache_creation` when it splits writes into `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`. A `cache_creation` count is a 5-minute write (`cache_write`); the 1-hour tokens are `cache_write_1h`. The uncached count is the total minus reads and both kinds of write.
- A subset or rescore is never a gate: its metadata has `gate: false`, and `finish_run` logs `not a gate run` after the failed checks and before the usage line. A clean one still exits 0. A full run has no `gate` key and prints no such line.
- Existing exit codes are unchanged: 0, 1, 2.
- No eval runs in this plan. Every test uses fakes; nothing calls a model or LangSmith, so this plan spends no Anthropic credit.
- Every line stays within 100 characters (`ruff check` E501).

## Review Focus

- A full run (no `gate` key) must not print `not a gate run`. Pinned by the existing `test_finish_run_logs_in_order_and_the_results_path_last`, which asserts the usage line comes straight after the failed checks. Task 2 leaves that test unchanged.
- A rescore of a subset file carries the source's `gate: false` and sets it again; the rescore file must still say `gate: false` and list its own cases. Task 2 adds that assertion to `test_run_rescore_of_a_subset_marks_it`.
- The usage line's `in` total must include 1-hour writes, or a run that uses them under-reports its input. Task 1 adds a render test.
- A reply carrying only `cache_creation` (no TTL split) is a 5-minute write, not dropped. Already pinned by the first case of `test_counts_from_takes_cache_tokens_out_of_the_input_total`, which Task 1 keeps.
- A 1-hour write on an unpriced model still costs `$?`, never raises. Task 1 adds it to the cost test.

---

### Task 1: Count and price 1-hour cache writes apart

**Files:**
- Modify: `packages/tri-core/src/tri_core/eval_usage.py` (constants, `PRICES`, `TokenCounts`, `counts_from`, `cost`, `as_record` docstring, `render_usage`)
- Test: `packages/tri-core/tests/test_eval_usage.py`
- Modify: `README.md` ("Evals and cost")

**Interfaces:**
- Consumes: nothing new.
- Produces: `TokenCounts(input=0, output=0, cache_read=0, cache_write=0, cache_write_1h=0)`; `CACHE_WRITE_1H_FACTOR = 2.0`; `PRICES_AS_OF = "2026-09-28"`. `UsageByRole.as_record()` role entries gain `"cache_write_1h"` (it spreads `vars(TokenCounts)`, so no code change there).

- [ ] **Step 1: Change the tests**

In `packages/tri-core/tests/test_eval_usage.py`, change the second expectation of `test_counts_from_takes_cache_tokens_out_of_the_input_total` (the TTL-split case with `ephemeral_5m_input_tokens: 200` and `ephemeral_1h_input_tokens: 50`) from `TokenCounts(input=750, cache_write=250)` to:

```python
    ) == TokenCounts(input=750, cache_write=200, cache_write_1h=50)
```

Add to `test_cost_prices_each_kind_of_token`, before its last line:

```python
    # a 1-hour write costs 2x the input rate, a 5-minute write 1.25x
    assert cost("claude-opus-5", TokenCounts(cache_write_1h=1_000_000)) == pytest.approx(10.0)
    assert cost("claude-haiku-4-5", TokenCounts(cache_write=1_000_000)) == pytest.approx(1.25)
    assert cost("claude-unknown-9", TokenCounts(cache_write_1h=1)) is None
```

In `test_the_record_names_the_models_and_sums_the_counts`, add `"cache_write_1h": 0,` after `"cache_write": 0,` in the expected dict.

Add a new test after `test_the_usage_line_splits_roles_and_totals`:

```python
def test_the_usage_line_counts_one_hour_writes_as_input():
    usage = UsageByRole()
    usage.add("coach", "claude-opus-5", TokenCounts(input=10_000, cache_write_1h=20_000))
    # 30k in: 10k uncached + 20k 1-hour writes; $0.05 + $0.20
    assert render_usage(usage) == "usage: coach 30k in / 0 out $0.25 · total $0.25"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_eval_usage.py -q`
Expected: FAIL. `TokenCounts` has no `cache_write_1h` argument.

- [ ] **Step 3: Implement**

In `packages/tri-core/src/tri_core/eval_usage.py`:

Replace the two factor constants with:

```python
CACHE_WRITE_FACTOR = 1.25  # 5-minute TTL, and a write that arrives without a TTL
CACHE_WRITE_1H_FACTOR = 2.0
CACHE_READ_FACTOR = 0.1
```

Replace the comment above `PRICES` with:

```python
# Anthropic first-party list prices. A model missing here costs `$?`. Re-check them against
# Anthropic's pricing page when the models in use change.
PRICES_AS_OF = "2026-09-28"
```

Replace `TokenCounts` with:

```python
@dataclass
class TokenCounts:
    """`input` is the uncached input; cache reads and writes are counted apart, and 1-hour writes
    apart from 5-minute (or unsplit) ones because they cost more."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cache_write_1h: int = 0

    def add(self, other: TokenCounts) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    @property
    def total_input(self) -> int:
        return self.input + self.cache_read + self.cache_write + self.cache_write_1h
```

Replace `counts_from` with:

```python
def counts_from(usage: Mapping[str, Any]) -> TokenCounts:
    """LangChain's `usage_metadata` as counts. langchain-anthropic's `input_tokens` already
    includes cache reads and writes, and a write comes either as `cache_creation` (no TTL, counted
    as a 5-minute write) or split by TTL (with `cache_creation` zeroed); the uncached part is what
    is left."""
    details = usage.get("input_token_details") or {}
    read = int(details.get("cache_read") or 0)
    write = sum(
        int(details.get(key) or 0) for key in ("cache_creation", "ephemeral_5m_input_tokens")
    )
    write_1h = int(details.get("ephemeral_1h_input_tokens") or 0)
    total = int(usage.get("input_tokens") or 0)
    return TokenCounts(
        input=max(total - read - write - write_1h, 0),
        output=int(usage.get("output_tokens") or 0),
        cache_read=read,
        cache_write=write,
        cache_write_1h=write_1h,
    )
```

In `cost`, add the 1-hour term after the 5-minute one:

```python
        + counts.cache_write * price.input * CACHE_WRITE_FACTOR
        + counts.cache_write_1h * price.input * CACHE_WRITE_1H_FACTOR
```

In `UsageByRole.as_record`, change "the four counts" to "the five counts" in the docstring.

In `render_usage`, replace the `text = (...)` assignment with a local total, so the line stays under 100 characters:

```python
    for role, r in record["roles"].items():
        total_in = r["input"] + r["cache_read"] + r["cache_write"] + r["cache_write_1h"]
        text = f"{role} {_tokens(total_in)} in / {_tokens(r['output'])} out"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_eval_usage.py -q && uv run ruff check packages/tri-core && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Document the price table**

In `README.md` under "### Evals and cost", after the fenced `text` block holding the example usage line, add:

```markdown
Costs come from the price table in `tri_core.eval_usage` (`PRICES`, dated by `PRICES_AS_OF`).
Re-check it against Anthropic's pricing page when the models in use change. A model missing from
the table shows `$?`.
```

- [ ] **Step 6: Commit**

```bash
git add packages/tri-core/src/tri_core/eval_usage.py packages/tri-core/tests/test_eval_usage.py README.md
git commit -m "feat(evals): 1-hour cache writes counted and priced apart; PRICES_AS_OF"
```

---

### Task 2: Subsets and rescores are marked `gate: false`

**Files:**
- Modify: `packages/tri-core/src/tri_core/evals.py` (`finish_run`)
- Modify: `packages/tri-core/src/tri_core/eval_select.py` (`run_rescore`)
- Modify: `packages/tri-analyze/src/tri_analyze/evals/run.py:147-148`, `packages/tri-coach/src/tri_coach/evals/run.py:125-126`, `packages/tri-nutrition/src/tri_nutrition/evals/run.py:123-124`, `packages/tri-planning/src/tri_planning/evals/run.py:122-123`, `packages/tri-wellness/src/tri_wellness/evals/run.py:117-118`
- Test: `packages/tri-core/tests/test_evals.py`, `packages/tri-core/tests/test_eval_select.py`, `packages/{tri-analyze,tri-coach,tri-nutrition,tri-planning,tri-wellness}/tests/test_eval_cost.py`
- Modify: `README.md` ("Evals and cost")

**Interfaces:**
- Consumes: `finish_run(rows, experiment, *, version, metadata, usage, log, total=None)` as it is today.
- Produces: `finish_run` logs `not a gate run` when `metadata.get("gate") is False`. Subset and rescore metadata carry `"gate": False`.

- [ ] **Step 1: Write the failing tests**

In `packages/tri-core/tests/test_evals.py`, add after `test_finish_run_logs_in_order_and_the_results_path_last` (leave that test as it is; it pins that a full run prints no gate line):

```python
def test_finish_run_says_so_when_the_run_is_not_a_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRI_EVAL_DIR", str(tmp_path))
    ok = _row("z2", [SimpleNamespace(key="grounded", score=1, comment=None)])
    logged: list[str] = []
    finish_run(
        [ok],
        "exp",
        version="3",
        metadata={"prompt_version": "3", "gate": False},
        usage=UsageByRole(),
        log=logged.append,
    )
    assert logged[2:4] == ["not a gate run", "usage: no model calls"]
    line = json.loads((tmp_path / "exp.jsonl").read_text().splitlines()[0])
    assert line["metadata"]["gate"] is False
```

In `packages/tri-core/tests/test_eval_select.py`:
- In `test_run_rescore_names_the_experiment_after_its_source_and_records_where_it_came_from`, add `assert "not a gate run" in logged` after the `usage: no model calls` assertion, and add `"gate": False,` after `"rescored_from": str(src),` in the expected metadata dict.
- In `test_run_rescore_of_a_subset_marks_it`, replace the last line with:

```python
    out = json.loads(out_file.read_text())["metadata"]
    assert out["cases"] == ["brick"] and out["gate"] is False
```

In each package's `tests/test_eval_cost.py`, in its `test_a_local_subset_runs_only_the_chosen_…_and_says_so` test, add after the `captured["metadata"]["cases"] == …` assertion:

```python
    assert captured["metadata"]["gate"] is False
```

and add `not a gate run` next to the existing pass-rate assertion:
- analyze, coach, nutrition (which bind `text = "\n".join(logged)`): `assert "not a gate run" in text`
- planning, wellness: `assert "not a gate run" in "\n".join(logged)`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_evals.py packages/tri-core/tests/test_eval_select.py packages/*/tests/test_eval_cost.py -q`
Expected: FAIL on the new `gate` and `not a gate run` assertions.

- [ ] **Step 3: Implement**

In `packages/tri-core/src/tri_core/evals.py`, `finish_run`: replace the docstring's first two sentences with

```python
    """The end every eval run shares: the experiment name, pass rates, errored count, failed
    checks, a `not a gate run` line when the metadata has `gate: false`, and the usage line, then
    the results file, whose path is logged last. Returns the pass rates and the errored count."""
```

and insert before `log(render_usage(usage))`:

```python
    if metadata.get("gate") is False:
        log("not a gate run")
```

In `packages/tri-core/src/tri_core/eval_select.py`, `run_rescore`, after `metadata["rescored_from"] = str(path)`:

```python
    metadata["gate"] = False  # no target calls: never a gate
```

In each of the five `evals/run.py` files, the block is

```python
    if chosen is not None:
        metadata["cases"] = chosen
```

Make it

```python
    if chosen is not None:
        metadata["cases"] = chosen
        metadata["gate"] = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/tri-core/tests/test_evals.py packages/tri-core/tests/test_eval_select.py packages/*/tests/test_eval_cost.py -q`
Expected: PASS.

- [ ] **Step 5: Document it**

In `README.md` under "### Evals and cost", replace

```markdown
its header reads `N of M examples (subset)`; it is never a gate. `--rescore` with `--failed-from`
on the same file re-judges only the failures.
```

with

```markdown
its header reads `N of M examples (subset)`; it is never a gate. Subsets and rescores record
`gate: false` in their metadata and print `not a gate run`, though a clean one still exits 0.
`--rescore` with `--failed-from` on the same file re-judges only the failures.
```

Leave the sentence after it ("Plans estimate a full run …") as it is.

- [ ] **Step 6: Full checks**

Run: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q`
Expected: all pass; only `--live` tests skip. `web/` is untouched, so its build doesn't need to run.

- [ ] **Step 7: Commit**

```bash
git add packages/tri-core/src/tri_core/evals.py packages/tri-core/src/tri_core/eval_select.py \
  packages/*/src/*/evals/run.py packages/tri-core/tests/test_evals.py \
  packages/tri-core/tests/test_eval_select.py packages/*/tests/test_eval_cost.py README.md
git commit -m "feat(evals): subsets and rescores record gate: false and say not a gate run"
```
