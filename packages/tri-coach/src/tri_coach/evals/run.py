"""Create the LangSmith routing dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langsmith import Client, aevaluate

from tri_coach.evals.cases import CASES
from tri_coach.evals.evaluators import (
    make_brief_judge,
    no_unrequested_adjustment,
    routing_accuracy,
)
from tri_coach.evals.target import make_target
from tri_coach.prompts.coach import PROMPT_VERSION
from tri_core.config import Settings
from tri_core.llm import ModelProvider, Role, eval_metadata
from tri_nutrition.evals.run import pass_rates

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


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


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
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
