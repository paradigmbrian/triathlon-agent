"""Create the LangSmith dataset of target weeks and run the design prompt over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY. The dataset keeps the name the earlier script used, so
experiments before and after this command compare. Each example costs one or two model calls."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from langsmith import Client, aevaluate

from tri_core.db.repo import Conn
from tri_core.llm import ModelProvider, Role, eval_metadata
from tri_planning.config import PlanningSettings
from tri_planning.evals.design_eval import build_examples, design_target, validator_pass
from tri_planning.graph.deps import GraphDeps

DATASET_NAME = "tri-planning-design-weeks"
DATASET_DESCRIPTION = "Target weeks for the tri-planning design prompt"


def case_examples(today: date) -> list[dict[str, Any]]:
    return [{**e, "outputs": {}} for e in build_examples(today)]


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples(date.today()))


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples:"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


def _no_database() -> AbstractContextManager[Conn]:
    raise RuntimeError("the design eval reads no database")


async def run_eval(
    settings: PlanningSettings,
    models: ModelProvider,
    *,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    """The pass rate per evaluator key. Weeks are designed on the planning_design role."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    designer = models(
        Role.PLANNING_DESIGN
    )  # design_week reads design_model; model is the required field
    deps = GraphDeps(
        model=designer,
        connect=_no_database,
        db_url=settings.database_url,
        design_model=designer,
    )
    results = await aevaluate(
        design_target(deps),
        data=DATASET_NAME,
        evaluators=[validator_pass],
        experiment_prefix=prefix or "design",
        metadata=eval_metadata(settings, Role.PLANNING_DESIGN, judge=False),
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
