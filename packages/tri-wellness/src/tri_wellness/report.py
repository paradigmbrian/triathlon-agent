"""The report: evaluate a stored panel, one streaming model call, save the result."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import anthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from tri_core.db.repo import Conn
from tri_wellness import repo
from tri_wellness.labs.evaluate import evaluate
from tri_wellness.labs.training_context import load_training_context
from tri_wellness.prompts.report import REPORT_SYSTEM, render_report_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.repl import Out, text_of

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


def extract_section(md: str, title: str) -> str | None:
    """The body of the level-2 section `## <title>` (an optional numeric prefix is allowed),
    up to the next level-2 heading. None when absent."""
    pattern = re.compile(
        rf"^##[ \t]+(?:\d+\.[ \t]*)?{re.escape(title)}[ \t]*$\n(.*?)(?=^##[ \t]|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(md)
    return m.group(1).strip() if m else None


def athlete_profile(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        "select ftp_watts, run_threshold_pace_sec_per_km, swim_css_sec_per_100m, lthr_bpm, "
        "max_hr_bpm, weight_kg from athlete_profile where id = 1"
    ).fetchone()


class ReportWriter:
    """One streaming call. Shared by the command and the evaluation target."""

    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    async def write(self, prompt: str, out: Out, tags: list[str]) -> str:
        parts: list[str] = []
        async for chunk in self.model.astream(
            [SystemMessage(REPORT_SYSTEM), HumanMessage(prompt)], config={"tags": tags}
        ):
            text = text_of(chunk)
            if text:
                out(text)
                parts.append(text)
        return "".join(parts)


async def run_report(
    model: BaseChatModel,
    connect: ConnectFactory,
    registry: MarkerRegistry,
    panel_id: int | None,
    out: Out,
    out_path: Path | None,
) -> int:
    """0 saved, 1 no panel or API error."""
    with connect() as conn:
        pid = panel_id if panel_id is not None else repo.latest_panel_id(conn)
        if pid is None:
            out("no panels stored; run `tri-wellness ingest <file>` first\n")
            return 1
        panel = repo.get_panel(conn, pid)
        if panel is None:
            out(f"no panel {pid}\n")
            return 1
        results = repo.lab_results_for_panel(conn, pid)
        previous = repo.previous_values(conn, pid)
        training = load_training_context(conn, panel.drawn_on)
        profile = athlete_profile(conn)
        prior = repo.latest_report_before(conn, pid)
    findings = evaluate(results, registry, previous, panel.context, training)
    prompt = render_report_prompt(
        findings,
        panel.context,
        training,
        extract_section(prior.report_md, "Priorities") if prior else None,
        profile,
        registry,
        has_previous=bool(previous),
    )
    tags = [f"panel_id:{pid}", f"ranges_version:{registry.version}"]
    try:
        text = await ReportWriter(model).write(prompt, out, tags)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and rerun.]\n")
        return 1
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
        return 1
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
        return 1
    with connect() as conn:
        report_id = repo.insert_report(conn, pid, registry.version, findings, text)
        conn.commit()
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
    where = f"; written to {out_path}" if out_path else ""
    out(f"\nsaved report {report_id} for panel {pid}{where}\n")
    return 0
