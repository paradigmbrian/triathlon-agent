"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langsmith import Client, aevaluate

from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import CASES
from tri_analyze.evals.evaluators import make_judge, pulls_splits, states_window, uses_sql
from tri_analyze.evals.target import make_target
from tri_analyze.prompts.analyst import PROMPT_VERSION
from tri_core.evals import errored, pass_rates, render_pass_rates, scored_counts
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
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    dict_rows = [dict(r) for r in rows]
    rates = pass_rates(dict_rows)
    errors = errored(dict_rows)
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, scored_counts(dict_rows), len(rows), version=PROMPT_VERSION))
    if errors:
        log(f"{errors} errored")
    return rates, errors
