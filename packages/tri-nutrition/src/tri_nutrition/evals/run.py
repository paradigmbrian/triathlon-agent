"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; every model call goes through the normal fueling prompts, so an experiment
is named by PROMPT_VERSION and the pass rate per evaluator is what changes between versions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from langsmith import Client, aevaluate, tracing_context

from tri_core.config import Settings
from tri_core.evals import (
    disable_network_sampling,
    errored,
    failure_lines,
    local_examples,
    pass_rates,
    record_rows,
    render_pass_rates,
    scored_counts,
)
from tri_core.llm import ModelProvider, Role, eval_metadata
from tri_nutrition.evals.cases import CASES
from tri_nutrition.evals.evaluators import (
    fuel_within_bounds,
    make_fuel_judge,
    targets_within_bounds,
)
from tri_nutrition.evals.target import make_target
from tri_nutrition.prompts.fuel import PROMPT_VERSION

DATASET_NAME = "tri_nutrition_fueling"
DATASET_DESCRIPTION = (
    "(profile, training week) pairs for the tri-nutrition fueling prompts. Evaluators: "
    "validate_targets, validate_fuel / validate_race, and an LLM judge for restrictions."
)


def case_examples() -> list[dict[str, Any]]:
    return [{"inputs": c.inputs(), "outputs": {}, "metadata": {"case": c.name}} for c in CASES]


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
        client: Client | None = None
        data: Any = local_examples(case_examples())
        disable_network_sampling()
    else:
        client = Client(api_key=settings.langsmith_api_key)
        ensure_dataset(client, recreate=recreate)
        data = DATASET_NAME
    evaluators: list[Any] = [targets_within_bounds, fuel_within_bounds]
    if judge:
        evaluators.append(make_fuel_judge(models(Role.JUDGE)))
    experiment_prefix = (prefix or f"fuel-v{PROMPT_VERSION}") + ("-local" if local else "")
    with tracing_context(enabled="local") if local else nullcontext():
        results = await aevaluate(
            make_target(models(Role.NUTRITION_FUEL)),
            data=data,
            evaluators=evaluators,
            experiment_prefix=experiment_prefix,
            metadata={
                "prompt_version": PROMPT_VERSION,
                **eval_metadata(settings, Role.NUTRITION_FUEL, judge=judge),
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
