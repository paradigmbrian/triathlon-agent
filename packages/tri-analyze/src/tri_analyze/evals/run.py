"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from langsmith import Client, aevaluate, tracing_context

from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import CASES
from tri_analyze.evals.evaluators import (
    JUDGE_VERSION,
    make_judge,
    pulls_splits,
    states_window,
    uses_sql,
)
from tri_analyze.evals.seed import (
    AthletesDatabaseRefused,
    clear_database,
    seed_database,
    verify_readable,
)
from tri_analyze.evals.target import make_target
from tri_analyze.prompts.analyst import PROMPT_VERSION
from tri_core.config import reader_url
from tri_core.eval_select import (
    CaseLookup,
    Selection,
    dataset_subset,
    run_rescore,
    subset_examples,
)
from tri_core.eval_usage import UsageByRole, with_usage
from tri_core.evals import (
    disable_network_sampling,
    finish_run,
    local_examples,
    local_experiment_name,
    offline_client,
)
from tri_core.llm import ModelProvider, Role, eval_metadata, resolve

DATASET_NAME = "tri_analyze_feedback"
DATASET_DESCRIPTION = (
    "Analyst questions (question, athlete context, bound tools, canned tool results) with the "
    "flags the checks read. Evaluators: uses_sql, pulls_splits, states_window, and an LLM judge "
    "for grounded and feedback_quality."
)


def case_examples() -> list[dict[str, Any]]:
    return [
        {"inputs": c.inputs(), "outputs": c.outputs(), "metadata": {"case": c.name}} for c in CASES
    ]


def case_names() -> list[str]:
    return [c.name for c in CASES]


def case_lookup() -> CaseLookup:
    return {e["metadata"]["case"]: e for e in case_examples()}.get


def _evaluators(models: ModelProvider, judge: bool) -> list[Any]:
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(models(Role.JUDGE)))
    return evaluators


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples())


async def run_eval(
    settings: AnalyzeSettings,
    models: ModelProvider,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    local: bool = False,
    log: Callable[[str], None] = print,
    eval_db_url: str | None = None,
    selection: Selection | None = None,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples. The analyst
    runs on its role's model and the judge on the judge role's. The history in evals/seed.py is
    seeded into the eval database (the test database unless given) and the tables are emptied
    afterwards, pass or fail. `local=True` never talks to LangSmith: no dataset, traces or
    feedback are sent. `selection` narrows the run to some cases, or re-scores a results file
    instead: no analyst, no database, no LangSmith."""
    usage = UsageByRole()
    models = with_usage(models, usage)
    chosen = selection.cases if selection is not None else None
    if selection is not None and selection.rescore is not None:
        current: dict[str, Any] = (
            {"judge_model": resolve(settings, Role.JUDGE).model, "judge_version": JUDGE_VERSION}
            if judge
            else {}
        )
        return await run_rescore(
            selection.rescore,
            evaluators=_evaluators(models, judge),
            lookup=case_lookup(),
            cases=chosen,
            current=current,
            usage=usage,
            log=log,
        )
    url = eval_db_url or settings.test_database_url
    if url == settings.database_url:
        raise AthletesDatabaseRefused(
            "refusing to seed the athlete's database; use the test database"
        )
    if local:
        client = offline_client()
        data: Any = local_examples(subset_examples(case_examples(), chosen))
        disable_network_sampling()
    else:
        client = Client(api_key=settings.langsmith_api_key)
        ensure_dataset(client, recreate=recreate)
        data = DATASET_NAME if chosen is None else dataset_subset(client, DATASET_NAME, chosen)
    evaluators = _evaluators(models, judge)
    experiment_prefix = (
        (prefix or f"analyst-v{PROMPT_VERSION}")
        + ("-subset" if chosen is not None else "")
        + ("-local" if local else "")
    )
    metadata: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        **eval_metadata(settings, Role.ANALYST, judge=judge),
    }
    if judge:
        metadata["judge_version"] = JUDGE_VERSION
    if chosen is not None:
        metadata["cases"] = chosen
        metadata["gate"] = False
    seed_database(url)
    try:
        verify_readable(url)
        with tracing_context(enabled="local", client=client) if local else nullcontext():
            results = await aevaluate(
                make_target(models(Role.ANALYST), reader_url(url)),
                data=data,
                evaluators=evaluators,
                experiment_prefix=experiment_prefix,
                metadata=metadata,
                client=client,
                upload_results=not local,
                max_concurrency=2,
            )
        rows: list[Any] = [row async for row in results]
    finally:
        try:
            clear_database(url)
        except Exception as exc:
            log(f"could not empty the eval database: {type(exc).__name__}: {exc}")
    experiment = local_experiment_name(experiment_prefix) if local else results.experiment_name
    return finish_run(
        [dict(r) for r in rows],
        experiment,
        version=PROMPT_VERSION,
        metadata=metadata,
        usage=usage,
        log=log,
        total=len(CASES) if chosen is not None else None,
    )
