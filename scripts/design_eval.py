"""Create/refresh the LangSmith dataset of target weeks and score the design prompt.

    uv run python scripts/design_eval.py --prompt-version v1

Needs LANGSMITH_API_KEY and ANTHROPIC_API_KEY in .env. Each example costs one or two model calls.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import date

from dotenv import load_dotenv
from langsmith import Client
from langsmith.evaluation import aevaluate

from tri_core.llm import Role, make_model
from tri_planning.config import get_planning_settings
from tri_planning.evals.design_eval import build_examples, design_target, validator_pass
from tri_planning.graph.deps import GraphDeps


def ensure_dataset(client: Client, name: str) -> None:
    examples = build_examples(date.today())
    if client.has_dataset(dataset_name=name):
        return
    ds = client.create_dataset(
        dataset_name=name, description="Target weeks for the tri-planning design prompt"
    )
    client.create_examples(
        dataset_id=ds.id,
        inputs=[e["inputs"] for e in examples],
        metadata=[e["metadata"] for e in examples],
    )


async def main(dataset: str, version: str) -> None:
    load_dotenv()
    settings = get_planning_settings()
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, dataset)
    deps = GraphDeps(
        model=make_model(settings, Role.PLANNING_DESIGN),
        connect=lambda: contextlib.nullcontext(None),
        db_url=settings.database_url,
    )  # type: ignore[arg-type]
    results = await aevaluate(
        design_target(deps),
        data=dataset,
        evaluators=[validator_pass],
        experiment_prefix=f"design-{version}",
        metadata={"prompt_version": version},
        client=client,
        max_concurrency=2,
    )
    rows = [dict(row) async for row in results]
    scores = [
        float(r.score)
        for row in rows
        for r in row["evaluation_results"]["results"]
        if r.key == "validator_pass" and r.score is not None
    ]
    pass_rate = sum(scores) / len(scores) if scores else 0.0
    print(f"experiment: {results.experiment_name}")
    print(f"validator_pass: {pass_rate:.0%} over {len(scores)} examples (prompt version {version})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="tri-planning-design-weeks")
    p.add_argument("--prompt-version", default="v1")
    a = p.parse_args()
    asyncio.run(main(a.dataset, a.prompt_version))
