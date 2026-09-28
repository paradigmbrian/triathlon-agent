"""Create the LangSmith dataset of target weeks and run the design prompt over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY. The dataset keeps the name the earlier script used, so
experiments before and after this command compare. Each example costs one or two model calls.
The experiment is named by PROMPT_VERSION (design-v<N>), so pass rates compare across prompt
versions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date
from typing import Any

from langsmith import Client, aevaluate, tracing_context

from tri_core.config import readonly_url
from tri_core.db.repo import Conn
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
from tri_core.llm import ModelProvider, Role, eval_metadata
from tri_planning.config import PlanningSettings
from tri_planning.evals.design_eval import build_examples, design_target, validator_pass
from tri_planning.graph.deps import GraphDeps
from tri_planning.prompts.design import PROMPT_VERSION

DATASET_NAME = "tri-planning-design-weeks"
DATASET_DESCRIPTION = "Target weeks for the tri-planning design prompt"


def case_examples(today: date) -> list[dict[str, Any]]:
    return [{**e, "outputs": {}} for e in build_examples(today)]


def case_names() -> list[str]:
    return [e["metadata"]["case"] for e in case_examples(date.today())]


def case_lookup() -> CaseLookup:
    return {e["metadata"]["case"]: e for e in case_examples(date.today())}.get


def ensure_dataset(client: Client, *, recreate: bool = False) -> None:
    if recreate and client.has_dataset(dataset_name=DATASET_NAME):
        client.delete_dataset(dataset_name=DATASET_NAME)
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(DATASET_NAME, description=DATASET_DESCRIPTION)
    client.create_examples(dataset_name=DATASET_NAME, examples=case_examples(date.today()))


def _no_database() -> AbstractContextManager[Conn]:
    raise RuntimeError("the design eval reads no database")


async def run_eval(
    settings: PlanningSettings,
    models: ModelProvider,
    *,
    prefix: str | None = None,
    recreate: bool = False,
    local: bool = False,
    log: Callable[[str], None] = print,
    selection: Selection | None = None,
) -> dict[str, float]:
    """The pass rate per evaluator key. Weeks are designed on the planning_design role.
    `local=True` never talks to LangSmith: no dataset, traces or feedback are sent.
    `selection` narrows the run to some weeks, or re-scores a results file instead (no design
    calls, no LangSmith)."""
    usage = UsageByRole()
    models = with_usage(models, usage)
    chosen = selection.cases if selection is not None else None
    if selection is not None and selection.rescore is not None:
        rates, _ = await run_rescore(
            selection.rescore,
            evaluators=[validator_pass],
            lookup=case_lookup(),
            cases=chosen,
            current={},
            usage=usage,
            log=log,
        )
        return rates
    examples = case_examples(date.today())
    if local:
        client = offline_client()
        data: Any = local_examples(subset_examples(examples, chosen))
        disable_network_sampling()
    else:
        client = Client(api_key=settings.langsmith_api_key)
        ensure_dataset(client, recreate=recreate)
        data = DATASET_NAME if chosen is None else dataset_subset(client, DATASET_NAME, chosen)
    # design_week reads design_model; model is only the dataclass's required field.
    designer = models(Role.PLANNING_DESIGN)
    deps = GraphDeps(
        model=designer,
        connect=_no_database,
        readonly_db_url=readonly_url(settings),
        design_model=designer,
    )
    experiment_prefix = (
        (prefix or f"design-v{PROMPT_VERSION}")
        + ("-subset" if chosen is not None else "")
        + ("-local" if local else "")
    )
    metadata: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        **eval_metadata(settings, Role.PLANNING_DESIGN, judge=False),
    }
    if chosen is not None:
        metadata["cases"] = chosen
    with tracing_context(enabled="local", client=client) if local else nullcontext():
        results = await aevaluate(
            design_target(deps),
            data=data,
            evaluators=[validator_pass],
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
        total=len(examples) if chosen is not None else None,
    )
    return rates
