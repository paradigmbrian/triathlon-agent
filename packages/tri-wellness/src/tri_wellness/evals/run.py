"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; the experiment is named by PROMPT_VERSION."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from langsmith import Client, aevaluate, tracing_context

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
from tri_wellness.config import WellnessSettings
from tri_wellness.evals.cases import CASES
from tri_wellness.evals.evaluators import (
    cites_functional_ranges,
    has_required_sections,
    names_active_confounders,
)
from tri_wellness.evals.target import make_target
from tri_wellness.prompts.report import PROMPT_VERSION
from tri_wellness.ranges.registry import load_registry

DATASET_NAME = "tri_wellness_reports"
DATASET_DESCRIPTION = (
    "Findings sets (LabResults, context, training, previous values) for the tri-wellness "
    "report prompt. Evaluators: cites_functional_ranges, has_required_sections, "
    "names_active_confounders."
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
    settings: WellnessSettings,
    models: ModelProvider,
    *,
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
    registry = load_registry(settings.tri_athlete_sex)
    experiment_prefix = (prefix or f"report-v{PROMPT_VERSION}") + ("-local" if local else "")
    with tracing_context(enabled="local") if local else nullcontext():
        results = await aevaluate(
            make_target(models(Role.LAB_REPORT), registry),
            data=data,
            evaluators=[cites_functional_ranges, has_required_sections, names_active_confounders],
            experiment_prefix=experiment_prefix,
            metadata={
                "prompt_version": PROMPT_VERSION,
                "ranges_version": registry.version,
                **eval_metadata(settings, Role.LAB_REPORT, judge=False),
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
