# Eval cost: usage record, rescore, case subsets, cost lines in plans

**Date:** 2026-09-28
**Status:** Draft
**Purpose:** Make the eval runs between gates cheap, and every run's cost visible. `docs/notes/2026-09-28-anthropic-api-usage-audit.md` found that almost all of September's $20 Anthropic spend was `tri-* eval` runs, at about $1 per full run. Some of those runs re-ran every Opus target only to test a judge change or re-check a few failing cases. Line numbers are `main` @ 8eb8506.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Goal | Cheaper iteration. Full gate runs keep the same target model, the same judge and every case (chosen 2026-09-28). | The gate is what decides a change, so its signal is not traded for cost. |
| Levers | Usage and cost record, `--rescore`, case subsets, cost lines in plans (chosen 2026-09-28). | Batches API, a monthly cap and a `--quick` profile are left out (§8). |
| Shape | Shared helpers in `tri_core` (`eval_usage.py` for usage and prices, `eval_select.py` for case selection and rescore, plus a shared run tail in `evals.py`), with thin wiring in each package's `evals/run.py` and `cli.py` (chosen 2026-09-28). | Follows how local results and `--local` landed. Merging the five runners is a refactor that isn't needed for this. |
| Unknown model price | Print the tokens and show the cost as `?`. Never fail the run (chosen 2026-09-28). | A new fallback model must not break an eval. |
| Asking before runs | Claude asks before **every** eval run, including rescores and subsets (chosen 2026-09-28). | The audit found a run Claude started from a handoff note. The rule is simplest when it has no exceptions. |

## 2. Feasibility, verified 2026-09-28

- Models: `make_model` (`tri_core/llm.py:142`) builds a `ChatAnthropic` whose metadata carries `tri_role`. `ChatAnthropic` has a `callbacks` field (langchain-anthropic 1.7.1, langchain-core 1.6.2). `ModelProvider = Callable[[Role], BaseChatModel]` (`llm.py:59`) is what every `run_eval` receives. `fallbacks_of` (`llm.py:155`) builds new `ChatAnthropic`s, so it must carry callbacks across (§3.1).
- Usage: langchain-core's `UsageMetadataCallbackHandler` sums `AIMessage.usage_metadata` per model name in `on_llm_end`. That's not enough here, because the analyst and the judge are both `claude-opus-5`.
- Runners: `run_eval` in `tri_analyze/evals/run.py:68`, `tri_coach/evals/run.py:58`, `tri_nutrition/evals/run.py:56`, `tri_planning/evals/run.py:57` and `tri_wellness/evals/run.py:57`. Each calls `aevaluate` with `max_concurrency=2`. Judges exist in analyze, coach and nutrition (`make_judge`). Planning and wellness have code evaluators only.
- Results: `record_rows` (`tri_core/evals.py:145`) writes case, inputs, outputs, error and results per line, with no `reference_outputs`. Only analyze passes `metadata` (`tri_analyze/evals/run.py:138`); the other four don't.
- Case names: analyze, coach, nutrition and wellness put `metadata.case` on each example. Planning doesn't: `build_examples` (`tri_planning/evals/design_eval.py:62`) sets only `goal_type` and `phase`.
- CLI: each package's `eval_cmd` (analyze `cli.py:130`, coach `:275`, nutrition `:322`, planning `:243`, wellness `:275`) calls an async `_eval` that calls `run_eval`.
- Prices (per MTok, Anthropic first-party, 2026-09-28): `claude-opus-5` $5 in / $25 out, and `claude-sonnet-5` $2 / $10. Cache writes cost 1.25× the input rate and cache reads 0.1×.

## 3. Usage and cost record

### 3.1 Collector

- `tri_core.eval_usage.UsageByRole` collects the sums, and hands out one LangChain callback handler per role (`usage.handler(role)`). Each handler's `on_llm_end` adds every response's `usage_metadata` under its role and the response's model name. The role comes from which handler fired, not from model metadata, so fakes in tests are counted too. Four counts are summed: uncached input, output, cache read and cache write. langchain-anthropic's `input_tokens` already includes cache reads and writes, and cache writes arrive either as `cache_creation` or split into `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`, so the uncached count is the total minus both. A response with no usage adds nothing. A lock guards the sums.
- `with_usage(models: ModelProvider, usage: UsageByRole) -> ModelProvider` wraps a provider so every model it returns has the handler for the role it was asked for in its `callbacks`. Each `run_eval` wraps its `models` argument once, before building the target and the judge. A model object handed out for two roles reports under the last one (`make_model` builds a new model per call). `fallbacks_of` copies the primary's `callbacks` onto the fallbacks it builds, so a fallback's tokens are counted under the same role.

### 3.2 Pricing

- `tri_core.eval_usage.PRICES: dict[str, Price]` has entries for `claude-opus-5`, `claude-opus-4-8` (the fallback chain), `claude-sonnet-5` and `claude-haiku-4-5`. A `Price` is input and output $ per MTok. Cache writes are costed at 1.25× the input rate and cache reads at 0.1×.
- `cost(model, counts) -> float | None` returns `None` for a model missing from `PRICES`.

### 3.3 Output

- After the pass rates, each run logs one line: `usage: analyst 412k in / 38k out (cache read 290k) $2.41 · judge 96k in / 9k out $0.71 · total $3.12`. Roles come in first-use order. A role with an unknown model shows `$?`, and so does the total. A run with no model calls (a rescore with no judge) logs `usage: no model calls`.
- `record_rows` writes the same figures into each line's top-level `usage` key: per role, the model, the four counts and the cost (or `null`), plus `total_cost`. `usage` sits beside `metadata`, not inside it, so `metadata` stays equal to what the experiment sent LangSmith. All five runners now pass `metadata`: `prompt_version` where the package has one, plus `eval_metadata(...)`. A shared `tri_core.evals.finish_run` logs the experiment, pass rates, errored count, failed checks and usage, then writes the file and logs its path last.

## 4. `--rescore <results.jsonl>`

- **Scope:** all five `eval` commands. Rescore re-runs the package's evaluators (code checks, plus the judge where the package has one) over the file's saved outputs. It makes no target calls, doesn't seed or touch a database, and never talks to LangSmith. It is always local, whatever `--local` or `TRI_EVAL_LOCAL` say.
- **Shared loop:** `tri_core.eval_select.rescore_rows(lines, evaluators, *, lookup, cases, log)` wraps each evaluator with langsmith's `run_evaluator` and calls `aevaluate_run(run, example)` on each line, so arguments are mapped the way `aevaluate` maps them. It awaits async evaluators, with tracing off and awaiting async evaluators, with two rows at a time. It returns rows in the shape `pass_rates`, `failure_lines` and `record_rows` already read.
- **Reference outputs:** from now on `record_rows` writes `reference_outputs` on every line whose example has outputs (every real `Example`), and rescore uses the file's value when it's present. For an older file, `lookup(case)` returns the case's current example from the package's cases. If the case is gone, the row is skipped and listed as `skipped: <case> (no longer a case)`.
- **Inputs:** rescore uses the file's inputs, because those produced the saved outputs. When a case's current inputs differ, it logs `<package>: <case> inputs changed since this file` once per case and scores anyway.
- **Errored rows:** a row with an `error` and no outputs is counted and skipped, and logged as `N errored in the source, not rescored`.
- **Output:** the experiment is named `<source experiment>-rescore-<8 hex>`, with the source name taken from the file name. Pass rates, failed checks, the usage line (judge only) and a results file follow as usual. The metadata copies the source's `prompt_version`, `model` and `effort`, adds `rescored_from: <path>`, and sets the current `judge_model` and `judge_version`.
- **Flags:** `--rescore` with `--recreate-dataset` or `--eval-db` exits 2 with a message. `--rescore` with `--cases` scores only those cases. `--rescore` with `--failed-from` scores the union of the two case sets. A missing or unreadable file exits 2.

## 5. Case subsets

- **Flags on all five `eval` commands:**
  - `--cases a,b,c` takes case names.
  - `--failed-from <results.jsonl>` takes the cases in that file with any score below 1 or an error.
  - Given together, the case set is their union.
- **Selection:** `tri_core.eval_select.select_cases(requested: set[str], known: Sequence[str]) -> list[str]` returns the known names in their original order. It raises `EvalArgsError` naming requested names that aren't known. `selection(...)` turns the three CLI options into a `Selection(cases, rescore)`, and raises `NothingToRun` for an empty `--failed-from`. For `--rescore`, the known names are the file's cases.
- **Errors:**
  - An unknown name exits 2 with `unknown case(s): x, y; cases are: …`.
  - A `--failed-from` file with nothing failed exits 0 with `nothing failed in <file>`, before any model is built.
- **Local runs** filter the in-memory examples.
- **LangSmith runs** read the dataset's examples (`client.list_examples(dataset_name=...)`) and keep those whose `metadata.case` is selected, passing that list to `aevaluate` as `data`. A subset never rebuilds the dataset.
- **Marking a subset:**
  - The experiment prefix gets `-subset`.
  - The metadata records `cases: [...]`.
  - `render_pass_rates` takes an optional `total` and prints `pass rate over 3 of 12 examples (subset)`.
- **Planning case names:** `build_examples` sets `metadata.case` to `<goal_type>-<phase>`. The four presets have distinct goal types, so all 23 names are unique (checked 2026-09-28), and a test asserts it. A LangSmith subset of planning needs one `--recreate-dataset` run after this lands, so the stored examples carry the name. The planning README says so.

## 6. Plan cost lines

- **Project `CLAUDE.md`:** a new file at the repo root holding only an "Eval runs" section:
  - A spec or plan that calls for eval runs lists each one as its command, with the case count and an estimated $. The estimate comes from the `usage.total_cost` in the latest `.evals/` file for that eval, or is marked "no baseline".
  - Pick the cheapest run that answers the question: `--rescore` for a judge-only change, then `--cases` / `--failed-from` while iterating. A full run is only for a gate.
  - Claude asks before starting any `tri-* eval` run and any `pytest --live`, even when a plan, spec or handoff note lists it, and gives the estimate when it asks.
- **README:** an "Evals and cost" subsection under Run covers `--rescore`, `--cases`, `--failed-from`, the usage line, and `TRI_MODEL_JUDGE=claude-sonnet-5` for cheap iteration runs. That override already works through the role registry, so it needs no new code.
- **Package READMEs:** each package's eval section gets one line per new flag. The planning README also gets the `--recreate-dataset` note from §5.

## 7. Errors

- An unknown model price never fails a run (§3.2).
- A callback that raises inside `UsageByRole` must not fail a model call. The handler sets `raise_error = False`, which is langchain's default, and a test covers it.
- `--rescore` and subset argument errors exit 2 before any model or database is touched. The existing exit codes are unchanged: 0 means every rate is 1.0, and 1 means a failure or an errored example.

## 8. Out of scope

- Batches API for judge calls, a monthly spend cap, a `--quick` profile flag (the env override covers it), and merging the five runners.
- Changing gate runs, prompts, judges or case sets.
- Anthropic Admin usage reports.

## 9. Testing

- **`tri_core`:**
  - `UsageByRole` sums fake `LLMResult`s by role and model, including cache counts, a response with no usage, and two concurrent roles on one model.
  - `with_usage` attaches the handler, and `fallbacks_of` keeps it.
  - `cost` is exact for known models and `None` for an unknown one.
  - The usage line is rendered for known and unknown prices and for no calls.
  - `select_cases` covers order, an unknown name and the union.
  - `rescore_rows` covers sync and async evaluators, a reference from the file vs. from `lookup`, a missing case, an errored row, and the inputs-changed warning.
  - `record_rows` writes `reference_outputs` and `usage`, and leaves both out when there are none, so existing results-file tests hold.
- **Each package:**
  - The CLI passes `--rescore`, `--cases` and `--failed-from` to `run_eval`, and exits 2 on bad combinations and unknown names.
  - `run_eval` on stub models logs a usage line and runs only the selected cases under a `-subset` name.
  - A rescore of a fixture results file with a fake judge writes a `-rescore-` results file with `rescored_from`.
- **Planning:** case names are unique.
- **No live calls:** every test uses stub or fake models, and CI still skips `--live`.

## 10. Rollout

One branch, `feat/eval-cost`, in this order: collector and pricing (§3), then subsets (§5), then rescore (§4), then docs (§6). There's no eval run in this rollout. The first real usage lines come from the next gate run a plan asks for, which Claude asks about first (§6).
