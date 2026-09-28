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
from tri_core.evals import (
    disable_network_sampling,
    errored,
    failure_lines,
    local_examples,
    local_experiment_name,
    offline_client,
    pass_rates,
    record_rows,
    render_pass_rates,
    scored_counts,
)
from tri_core.llm import ModelProvider, Role, eval_metadata

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
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples. The analyst
    runs on its role's model and the judge on the judge role's. The history in evals/seed.py is
    seeded into the eval database (the test database unless given) and the tables are emptied
    afterwards, pass or fail. `local=True` never talks to LangSmith: no dataset, traces or
    feedback are sent."""
    url = eval_db_url or settings.test_database_url
    if url == settings.database_url:
        raise AthletesDatabaseRefused(
            "refusing to seed the athlete's database; use the test database"
        )
    if local:
        client = offline_client()
        data: Any = local_examples(case_examples())
        disable_network_sampling()
    else:
        client = Client(api_key=settings.langsmith_api_key)
        ensure_dataset(client, recreate=recreate)
        data = DATASET_NAME
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(models(Role.JUDGE)))
    experiment_prefix = (prefix or f"analyst-v{PROMPT_VERSION}") + ("-local" if local else "")
    metadata: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        **eval_metadata(settings, Role.ANALYST, judge=judge),
    }
    if judge:
        metadata["judge_version"] = JUDGE_VERSION
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
    dict_rows = [dict(r) for r in rows]
    rates = pass_rates(dict_rows)
    errors = errored(dict_rows)
    experiment = local_experiment_name(experiment_prefix) if local else results.experiment_name
    log(f"experiment: {experiment}")
    log(render_pass_rates(rates, scored_counts(dict_rows), len(rows), version=PROMPT_VERSION))
    if errors:
        log(f"{errors} errored")
    failures = failure_lines(dict_rows)
    if failures:
        log("failed checks:\n" + "\n".join(failures))
    log(f"results: {record_rows(dict_rows, experiment, metadata=metadata)}")
    return rates, errors
