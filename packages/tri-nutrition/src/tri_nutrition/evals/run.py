"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; every model call goes through the normal fueling prompts, so an experiment
is named by PROMPT_VERSION and the pass rate per evaluator is what changes between versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

from tri_core.config import Settings
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


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:24} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


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
    evaluators: list[Any] = [targets_within_bounds, fuel_within_bounds]
    if judge:
        evaluators.append(make_fuel_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"fuel-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": settings.tri_model},
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
