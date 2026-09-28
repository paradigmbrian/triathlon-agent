"""Create the LangSmith routing dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from langsmith import Client, aevaluate, tracing_context

from tri_coach.evals.cases import CASES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    routing_accuracy,
)
from tri_coach.evals.target import make_target
from tri_coach.prompts.coach import PROMPT_VERSION
from tri_core.config import Settings
from tri_core.evals import (
    disable_network_sampling,
    errored,
    failure_lines,
    local_examples,
    offline_client,
    pass_rates,
    record_rows,
    render_pass_rates,
    scored_counts,
)
from tri_core.llm import ModelProvider, Role, eval_metadata

DATASET_NAME = "tri_coach_routing"
DATASET_DESCRIPTION = (
    "Single coach turns (context block, memory, conversation) with the routes the coach may take. "
    "Evaluators: routing_accuracy, no_unrequested_adjustment, and an LLM judge over each brief."
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
    settings: Settings,
    models: ModelProvider,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    local: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    """`local=True` never talks to LangSmith: no dataset, traces or feedback are sent."""
    if local:
        client = offline_client()
        data: Any = local_examples(case_examples())
        disable_network_sampling()
    else:
        client = Client(api_key=settings.langsmith_api_key)
        ensure_dataset(client, recreate=recreate)
        data = DATASET_NAME
    evaluators: list[Any] = [routing_accuracy, no_unrequested_adjustment]
    if judge:
        evaluators.append(make_brief_judge(models(Role.JUDGE)))
    experiment_prefix = (prefix or f"coach-v{PROMPT_VERSION}") + ("-local" if local else "")
    with tracing_context(enabled="local", client=client) if local else nullcontext():
        results = await aevaluate(
            make_target(models(Role.COACH)),
            data=data,
            evaluators=evaluators,
            experiment_prefix=experiment_prefix,
            metadata={
                "prompt_version": PROMPT_VERSION,
                **eval_metadata(settings, Role.COACH, judge=judge),
            },
            client=client,
            upload_results=not local,
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
    failures = failure_lines(dict_rows)
    if failures:
        log("failed checks:\n" + "\n".join(failures))
    log(f"results: {record_rows(dict_rows, results.experiment_name)}")
    return rates
