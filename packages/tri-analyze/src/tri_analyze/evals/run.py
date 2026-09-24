"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY and ANTHROPIC_API_KEY; the experiment is named by PROMPT_VERSION, so the pass
rate per evaluator is what changes between prompt versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

from tri_analyze.config import AnalyzeSettings
from tri_analyze.evals.cases import CASES
from tri_analyze.evals.evaluators import make_judge, pulls_splits, states_window, uses_sql
from tri_analyze.evals.target import make_target
from tri_analyze.prompts.analyst import PROMPT_VERSION
from tri_core.llm import Role, resolve

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


def pass_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for r in row["evaluation_results"]["results"]:
            if r.score is not None:
                scores[r.key].append(float(r.score))
    return {key: sum(v) / len(v) for key, v in scores.items()}


def render_pass_rates(rates: dict[str, float], n: int) -> str:
    lines = [f"pass rate over {n} examples (prompt version {PROMPT_VERSION}):"]
    lines += [f"  {key:26} {rate:.0%}" for key, rate in sorted(rates.items())]
    return "\n".join(lines)


def errored(rows: list[dict[str, Any]]) -> int:
    """Examples whose target raised: LangSmith keeps the run with its error text."""
    return sum(1 for row in rows if getattr(row.get("run"), "error", None))


async def run_eval(
    settings: AnalyzeSettings,
    model: BaseChatModel,
    *,
    judge: bool = True,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[dict[str, float], int]:
    """Returns the pass rate per evaluator key and the number of errored examples."""
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    evaluators: list[Any] = [uses_sql, pulls_splits, states_window]
    if judge:
        evaluators.append(make_judge(model))
    results = await aevaluate(
        make_target(model),
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix=prefix or f"analyst-v{PROMPT_VERSION}",
        metadata={"prompt_version": PROMPT_VERSION, "model": resolve(settings, Role.ANALYST).model},
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    dict_rows = [dict(r) for r in rows]
    rates = pass_rates(dict_rows)
    errors = errored(dict_rows)
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    if errors:
        log(f"{errors} errored")
    return rates, errors
