"""Terminal side of ingest: the review table, the decision dialogue, context prompts and the
YAML edit round trip. Plan 3 adds the chat loop here."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, time
from typing import Any

import anthropic
import yaml
from langgraph.types import Command

from tri_wellness.labs.models import (
    BLOCKING_REASONS,
    IngestDecision,
    LabResult,
    PanelContext,
    PanelSummary,
    RawResult,
    Unmapped,
)
from tri_wellness.ranges.registry import MarkerRegistry

Out = Callable[[str], None]
Read = Callable[[], Awaitable[str | None]]
EditFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

REVIEW_PROMPT = "approve / edit / reject <note> / quit"


def _rng(low: Any, high: Any) -> str:
    if low is None and high is None:
        return ""

    def fmt(v: Any) -> str:
        return "" if v is None else f"{float(v):g}"

    return f"{fmt(low)}-{fmt(high)}"


def render_review(payload: dict[str, Any]) -> str:
    results = payload.get("results") or []
    unmapped = payload.get("unmapped") or []
    blocking = [u for u in unmapped if u.get("reason") in BLOCKING_REASONS]
    lines = [
        str(payload.get("source_path") or ""),
        f"drawn {payload.get('drawn_on') or '?'}  lab {payload.get('lab_name') or '?'}",
    ]
    if payload.get("duplicates"):
        ids = ", ".join(str(i) for i in payload["duplicates"])
        lines.append(
            f"warning: panel(s) {ids} already stored for this date and lab; approve stores another"
        )
    if payload.get("last_error"):
        lines.append(f"refused: {payload['last_error']}")
    lines.append(f"{'marker':24} {'value':>10} {'unit':10} {'lab range':12} {'flag':4} raw name")
    for r in results:
        raw = r.get("raw") or {}
        lines.append(
            f"{r['marker']:24} {float(r['value']):>10g} {r['unit']:10} "
            f"{_rng(r.get('lab_ref_low'), r.get('lab_ref_high')):12} {(raw.get('flag') or ''):4} "
            f"{raw.get('name') or ''}"
        )
    if unmapped:
        lines.append("unmapped:")
        for u in unmapped:
            raw = u.get("raw") or {}
            target = f" -> {u['marker']}" if u.get("marker") else ""
            lines.append(
                f"  [{u['reason']:9}] {raw.get('name')} = {raw.get('value')} "
                f"{raw.get('unit') or ''}{target}"
            )
    lines.append(
        f"{len(results)} results, {len(unmapped)} unmapped ({len(blocking)} blocking). "
        f"{REVIEW_PROMPT}"
    )
    return "\n".join(lines)


def parse_decision(line: str) -> tuple[str, str | None] | None:
    word, _, rest = line.strip().partition(" ")
    if word in ("approve", "edit"):
        return word, None
    if word == "reject":
        return "reject", rest.strip() or None
    if word in ("quit", "/quit"):
        return "quit", None
    return None


async def _ask(read: Read, out: Out, prompt: str) -> str | None:
    out(prompt)
    line = await read()
    return None if line is None else line.strip()


def _list(text: str) -> list[str]:
    return [s.strip() for s in text.split(",") if s.strip()]


async def collect_context(read: Read, out: Out) -> PanelContext | None:
    """Six short prompts. Enter skips a field. None on EOF."""
    fasting_raw = await _ask(read, out, "fasting? (y/n, enter = unknown) ")
    if fasting_raw is None:
        return None
    fasting = {"y": True, "yes": True, "n": False, "no": False}.get(fasting_raw.lower())
    draw_time: time | None = None
    while True:
        t = await _ask(read, out, "draw time (HH:MM, enter = unknown) ")
        if t is None:
            return None
        if not t:
            break
        try:
            draw_time = time.fromisoformat(t if len(t.split(":")[0]) == 2 else "0" + t)
            break
        except ValueError:
            out("use HH:MM\n")
    supplements = await _ask(read, out, "supplements (comma-separated, enter = none) ")
    diet = await _ask(read, out, "diet pattern (enter = skip) ")
    symptoms = await _ask(read, out, "symptoms (comma-separated, enter = none) ")
    notes = await _ask(read, out, "notes (enter = none) ")
    if None in (supplements, diet, symptoms, notes):
        return None
    return PanelContext(
        fasting=fasting,
        draw_time=draw_time,
        supplements=_list(supplements or ""),
        diet_pattern=diet or None,
        symptoms=_list(symptoms or ""),
        notes=notes or None,
    )


def _result_row(r: dict[str, Any]) -> dict[str, Any]:
    raw = r.get("raw") or {}
    return {
        "marker": r["marker"],
        "value": r["value"],
        "unit": r["unit"],
        "raw_name": raw.get("name"),
        "raw_value": raw.get("value"),
        "raw_unit": raw.get("unit"),
        "raw_ref_low": raw.get("ref_low"),
        "raw_ref_high": raw.get("ref_high"),
        "lab_ref_low": r.get("lab_ref_low"),
        "lab_ref_high": r.get("lab_ref_high"),
        "flag": raw.get("flag"),
        "note": r.get("note"),
    }


def _unmapped_row(u: dict[str, Any]) -> dict[str, Any]:
    raw = u.get("raw") or {}
    return {
        "reason": u["reason"],
        "marker": u.get("marker"),
        "name": raw.get("name"),
        "value": raw.get("value"),
        "unit": raw.get("unit"),
        "ref_low": raw.get("ref_low"),
        "ref_high": raw.get("ref_high"),
        "flag": raw.get("flag"),
    }


def review_to_yaml(payload: dict[str, Any]) -> str:
    context = payload.get("context") or PanelContext().model_dump(mode="json")
    doc = {
        "drawn_on": payload.get("drawn_on"),
        "lab_name": payload.get("lab_name"),
        "context": context,
        "results": [_result_row(r) for r in payload.get("results") or []],
        "unmapped": [_unmapped_row(u) for u in payload.get("unmapped") or []],
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def review_from_yaml(text: str, registry: MarkerRegistry) -> dict[str, Any]:
    """Parse and validate an edited review document. Raises ValueError naming every bad row."""
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"yaml: {exc}") from exc
    problems: list[str] = []
    results: list[LabResult] = []
    for i, row in enumerate(doc.get("results") or []):
        marker = str(row.get("marker") or "")
        if marker not in registry.markers:
            problems.append(f"results[{i}]: unknown marker '{marker}'")
            continue
        spec = registry.get(marker)
        if row.get("unit") != spec.unit:
            problems.append(
                f"results[{i}] ({marker}): unit must be {spec.unit}, got {row.get('unit')}"
            )
            continue
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"results[{i}] ({marker}): value '{row.get('value')}' is not a number")
            continue
        results.append(
            LabResult(
                marker=marker,
                value=value,
                unit=spec.unit,
                raw=RawResult(
                    name=str(row.get("raw_name") or spec.display),
                    value=str(row.get("raw_value") if row.get("raw_value") is not None else value),
                    unit=row.get("raw_unit"),
                    ref_low=None if row.get("raw_ref_low") is None else str(row["raw_ref_low"]),
                    ref_high=None if row.get("raw_ref_high") is None else str(row["raw_ref_high"]),
                    flag=row.get("flag"),
                ),
                lab_ref_low=row.get("lab_ref_low"),
                lab_ref_high=row.get("lab_ref_high"),
                note=row.get("note"),
            )
        )
    unmapped: list[Unmapped] = []
    for i, row in enumerate(doc.get("unmapped") or []):
        try:
            unmapped.append(
                Unmapped(
                    raw=RawResult(
                        name=str(row.get("name") or ""),
                        value=str(row.get("value") or ""),
                        unit=row.get("unit"),
                        ref_low=row.get("ref_low"),
                        ref_high=row.get("ref_high"),
                        flag=row.get("flag"),
                    ),
                    reason=row.get("reason") or "name",
                    marker=row.get("marker"),
                )
            )
        except ValueError as exc:
            problems.append(f"unmapped[{i}]: {exc}")
    drawn_on: date | None = None
    if doc.get("drawn_on"):
        try:
            drawn_on = date.fromisoformat(str(doc["drawn_on"]))
        except ValueError:
            problems.append(f"drawn_on: '{doc['drawn_on']}' is not YYYY-MM-DD")
    context: PanelContext | None = None
    try:
        parsed_context = PanelContext.model_validate(doc.get("context") or {})
        context = None if parsed_context == PanelContext() else parsed_context
    except ValueError as exc:
        problems.append(f"context: {exc}")
    if problems:
        raise ValueError("\n".join(problems))
    return {
        "results": results,
        "unmapped": unmapped,
        "drawn_on": drawn_on,
        "lab_name": doc.get("lab_name") or None,
        "context": context,
    }


async def review_dialogue(
    payload: dict[str, Any], read: Read, out: Out, edit: EditFn | None
) -> IngestDecision | None:
    out(render_review(payload) + "\n")
    while True:
        line = await read()
        if line is None:
            return None
        parsed = parse_decision(line)
        if parsed is None:
            out(f"{REVIEW_PROMPT}\n")
            continue
        action, note = parsed
        if action == "quit":
            return None
        if action == "reject":
            return IngestDecision(action="reject", note=note)
        if action == "edit":
            if edit is None:
                out("editing is not available here\n")
                continue
            edited = await edit(payload)
            if edited is None:
                out("edit cancelled\n")
                continue
            return IngestDecision(action="edit", **edited)
        blocking = [u for u in payload.get("unmapped") or [] if u.get("reason") in BLOCKING_REASONS]
        if blocking:
            out(f"{len(blocking)} row(s) need a unit or value fix; edit or remove them first\n")
            continue
        payload_context = payload.get("context")
        if payload_context is not None:
            edited_context = PanelContext.model_validate(payload_context)
            if edited_context != PanelContext():
                out("using the context from your edit\n")
                return IngestDecision(action="approve", context=edited_context)
        context = await collect_context(read, out)
        if context is None:
            return None
        return IngestDecision(action="approve", context=context)


@dataclass
class TurnResult:
    interrupt: dict[str, Any] | None = None
    error: str | None = None


async def run_turn(
    graph: Any, payload: dict[str, Any] | Command[Any], thread_id: str, out: Out
) -> TurnResult:
    result = TurnResult()
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        async for data in graph.astream(payload, config=cfg, stream_mode="updates"):
            if not isinstance(data, dict):
                continue
            if "__interrupt__" in data:
                result.interrupt = dict(data["__interrupt__"][0].value)
            elif "extract" in data:
                u = data["extract"] or {}
                pages = f", {u['page_count']} pages" if u.get("page_count") else ""
                out(f"extracted {len(u.get('raw_results') or [])} rows{pages}\n")
                if u.get("last_error"):
                    out(f"ingest failed: {u['last_error']}\n")
            elif "store" in data:
                out(f"stored panel {(data['store'] or {}).get('panel_id')}\n")
    except anthropic.RateLimitError as exc:
        result.error = f"rate limited: {exc}. Wait a moment and rerun; the thread resumes."
    except anthropic.APIStatusError as exc:
        result.error = f"Anthropic API error {exc.status_code}: {exc.message}"
    except anthropic.APIConnectionError as exc:
        result.error = f"connection error talking to Anthropic: {exc}"
    except Exception as exc:
        result.error = f"ingest failed: {type(exc).__name__}: {exc}"
    if result.error:
        out(f"[{result.error}]\n")
    return result


def _pending_payload(snapshot: Any) -> dict[str, Any] | None:
    for task in getattr(snapshot, "tasks", ()) or ():
        for stop in getattr(task, "interrupts", ()) or ():
            return dict(stop.value)
    return None


async def run_ingest(
    graph: Any,
    *,
    source_path: str,
    source_kind: str,
    drawn_on_hint: date | None,
    thread_id: str,
    read: Read,
    out: Out,
    edit: EditFn | None,
) -> int:
    """0 stored (or already stored), 1 extraction or API error, 2 rejected, 3 paused."""
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    values: dict[str, Any] = snap.values or {}
    pending: dict[str, Any] | None = None
    if snap.next == ("review",) and (pending := _pending_payload(snap)) is not None:
        out("resuming the review for this file\n")
    elif values.get("panel_id") is not None:
        out(f"already stored as panel {values['panel_id']}; nothing to do\n")
        return 0
    else:
        turn = await run_turn(
            graph,
            {
                "source_path": source_path,
                "source_kind": source_kind,
                "drawn_on_hint": drawn_on_hint,
            },
            thread_id,
            out,
        )
        if turn.error:
            return 1
        pending = turn.interrupt
    while pending is not None:
        decision = await review_dialogue(pending, read, out, edit)
        if decision is None:
            out("paused at review; rerun the same command to resume\n")
            return 3
        turn = await run_turn(
            graph,
            Command(resume=decision.model_dump(mode="json", exclude_none=True)),
            thread_id,
            out,
        )
        if turn.error:
            return 1
        pending = turn.interrupt
    values = (await graph.aget_state(cfg)).values or {}
    if values.get("panel_id") is not None:
        return 0
    if values.get("decision") == "reject":
        out("rejected; nothing stored\n")
        return 2
    return 1


def render_panels(summaries: list[PanelSummary]) -> str:
    if not summaries:
        return "no panels stored; run `tri-wellness ingest <file>`"
    lines = [f"{'id':>4}  {'drawn':10}  {'lab':20}  {'results':>7}  {'unmapped':>8}  report"]
    for s in summaries:
        lines.append(
            f"{s.id:>4}  {s.drawn_on.isoformat():10}  {(s.lab_name or '-'):20.20}  "
            f"{s.result_count:>7}  {s.unmapped_count:>8}  {'yes' if s.has_report else 'no'}"
        )
    return "\n".join(lines)
