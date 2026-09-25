"""The function under evaluation: evaluate the case's results with the current registry, render
the prompt, write the report. No database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel

from tri_wellness.labs.evaluate import evaluate
from tri_wellness.labs.models import LabResult, PanelContext, PreviousValue, TrainingContext
from tri_wellness.prompts.report import render_report_prompt, with_disclaimer
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import ReportWriter


def parse_inputs(
    inputs: dict[str, Any],
) -> tuple[
    list[LabResult],
    PanelContext,
    TrainingContext,
    dict[str, PreviousValue],
    dict[str, Any] | None,
]:
    previous: dict[str, PreviousValue] = {
        m: (date.fromisoformat(str(d)), float(v), (b[0] if b else None))
        for m, (d, v, *b) in (inputs.get("previous") or {}).items()
    }
    return (
        [LabResult.model_validate(r) for r in inputs["results"]],
        PanelContext.model_validate(inputs["context"]),
        TrainingContext.model_validate(inputs["training"]),
        previous,
        inputs.get("profile"),
    )


async def run_case(
    writer: ReportWriter, registry: MarkerRegistry, inputs: dict[str, Any]
) -> dict[str, Any]:
    results, context, training, previous, profile = parse_inputs(inputs)
    findings = evaluate(results, registry, previous, context, training)
    prompt = render_report_prompt(
        findings, context, training, None, profile, registry, has_previous=bool(previous)
    )
    text = await writer.write(prompt, lambda _s: None, ["eval"])
    return {
        "report_md": with_disclaimer(text),
        "findings": [f.model_dump(mode="json") for f in findings],
    }


def make_target(
    model: BaseChatModel, registry: MarkerRegistry
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    writer = ReportWriter(model)

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(writer, registry, inputs)

    return target
