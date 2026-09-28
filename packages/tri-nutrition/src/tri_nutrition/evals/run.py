"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; every model call goes through the normal fueling prompts, so an experiment
is named by PROMPT_VERSION and the pass rate per evaluator is what changes between versions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from langsmith import Client, aevaluate, tracing_context

from tri_core.config import Settings
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


def case_names() -> list[str]:
    return [c.name for c in CASES]


def case_lookup() -> CaseLookup:
    return {e["metadata"]["case"]: e for e in case_examples()}.get


def _evaluators(models: ModelProvider, judge: bool) -> list[Any]:
    evaluators: list[Any] = [targets_within_bounds, fuel_within_bounds]
    if judge:
        evaluators.append(make_fuel_judge(models(Role.JUDGE)))
    return evaluators


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
    selection: Selection | None = None,
) -> dict[str, float]:
    """`local=True` never talks to LangSmith: no dataset, traces or feedback are sent.
    `selection` narrows the run to some cases, or re-scores a results file instead (no fueling
    calls, no LangSmith)."""
    usage = UsageByRole()
    models = with_usage(models, usage)
    chosen = selection.cases if selection is not None else None
    if selection is not None and selection.rescore is not None:
        current: dict[str, Any] = (
            {"judge_model": resolve(settings, Role.JUDGE).model} if judge else {}
        )
        rates, _ = await run_rescore(
            selection.rescore,
            evaluators=_evaluators(models, judge),
            lookup=case_lookup(),
            cases=chosen,
            current=current,
            usage=usage,
            log=log,
        )
        return rates
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
        (prefix or f"fuel-v{PROMPT_VERSION}")
        + ("-subset" if chosen is not None else "")
        + ("-local" if local else "")
    )
    metadata: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        **eval_metadata(settings, Role.NUTRITION_FUEL, judge=judge),
    }
    if chosen is not None:
        metadata["cases"] = chosen
        metadata["gate"] = False
    with tracing_context(enabled="local", client=client) if local else nullcontext():
        results = await aevaluate(
            make_target(models(Role.NUTRITION_FUEL)),
            data=data,
            evaluators=evaluators,
            experiment_prefix=experiment_prefix,
            metadata=metadata,
            client=client,
            upload_results=not local,
            max_concurrency=2,
        )
    rows: list[Any] = [row async for row in results]
    experiment = local_experiment_name(experiment_prefix) if local else results.experiment_name
    rates, _ = finish_run(
        [dict(r) for r in rows],
        experiment,
        version=PROMPT_VERSION,
        metadata=metadata,
        usage=usage,
        log=log,
        total=len(CASES) if chosen is not None else None,
    )
    return rates
