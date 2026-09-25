"""Report prompt: fixed structure, fixed rules, and the blocks that turn findings and contexts
into text the model can reason over. Every value the model sees carries its status and range."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tri_wellness.labs.models import Finding, PanelContext, TrainingContext
from tri_wellness.labs.normalize import parse_value
from tri_wellness.ranges.registry import MarkerRegistry

PROMPT_VERSION = "2"  # bump when REPORT_SYSTEM or REPORT_RULES changes; names the eval experiment

DISCLAIMER = (
    "This is an educational interpretation of lab values against functional-medicine ranges "
    "for one athlete, prepared for discussion with a qualified practitioner; it is not a "
    "diagnosis or a prescription."
)

SECTION_TITLES: tuple[str, ...] = (
    "Draw conditions",
    "By system",
    "Priorities",
    "Training implications",
    "Levers",
    "Supplements",
    "Retest plan",
    "Questions for your practitioner",
)
CHANGES_TITLE = "Changes since last panel"

REPORT_RULES = """\
Rules:
- Cite the functional range you used for every flagged marker, in the marker's canonical unit,
  the first time you discuss it (for example "ferritin 42 ng/mL against 50-150").
- Name a confounder whenever it applies to a marker, and say how much weight it carries.
- Distinguish "marker shows" (the number) from "pattern suggests" (your inference across
  markers). Never present an inference as a measurement.
- No generic wellness advice. Every lever, supplement and retest ties to a named finding.
- Do not restate optimal markers beyond the one-line system summary.
- Use only the ranges and notes given; do not recall cutoffs from memory."""

REPORT_SYSTEM = f"""\
You are a functional-medicine practitioner who works with one endurance athlete. You write a
lab interpretation from findings that Python has already evaluated against a curated range
table. You explain patterns; you do not re-judge the numbers. The report is for the athlete to
take to their practitioner: it names what to discuss, not what to take.

Write markdown with exactly this structure, these level-2 headings, in this order.
Do not write a disclaimer or a preamble; a fixed one is placed above your text. Start with the
first heading.

## {SECTION_TITLES[0]}
Fasting, timing, active confounders, and how much weight each carries.
## {SECTION_TITLES[1]}
One level-3 heading per system that has at least one non-optimal marker, describing what the
pattern across its markers says; systems that are entirely optimal get one line each. A marker
whose status is indeterminate is reported as the lab printed it, with what the bound rules out.
## {SECTION_TITLES[2]}
At most three, ranked, with reasoning. Any marker whose conventional status is low or high
comes first, and its item opens with "discuss with your practitioner first".
## {SECTION_TITLES[3]}
Load, intensity and recovery over the coming weeks, written so it could be pasted into a
training-plan constraint.
## {SECTION_TITLES[4]}
Nutrition, sleep, stress and training changes tied to specific findings.
## {SECTION_TITLES[5]}
Per item: the compound, the marker it targets, and what a retest would show if it worked.
No dose, no timing, no duration; those are the practitioner's call.
## {SECTION_TITLES[6]}
Which markers, when, and under what draw conditions.
## {SECTION_TITLES[7]}
## {CHANGES_TITLE}
Only when the prompt says a previous panel exists.

{REPORT_RULES}"""


def with_disclaimer(report: str) -> str:
    """The saved report: the fixed disclaimer, a blank line, then the model's text (minus its own
    copy of the disclaimer, if it wrote one despite the prompt), ending in one newline."""
    body = report.strip()
    if body.startswith(DISCLAIMER):
        body = body[len(DISCLAIMER) :].lstrip()
    return f"{DISCLAIMER}\n\n{body}\n"


def _g(v: Any) -> str:
    return f"{float(v):g}"


def format_range(low: float | None, high: float | None) -> str:
    if low is not None and high is not None:
        return f"{_g(low)}-{_g(high)}"
    if high is not None:
        return f"up to {_g(high)}"
    if low is not None:
        return f"{_g(low)} or above"
    return "no range"


def profile_block(profile: dict[str, Any] | None, sex: str) -> str:
    if not profile:
        return f"Athlete: {sex}; thresholds: not available (run `tri sync`)."
    parts = [f"Athlete: {sex}"]
    if profile.get("weight_kg") is not None:
        parts.append(f"{float(profile['weight_kg']):g} kg")
    if profile.get("ftp_watts") is not None:
        parts.append(f"FTP {profile['ftp_watts']} W")
    if profile.get("lthr_bpm") is not None:
        parts.append(f"LTHR {profile['lthr_bpm']} bpm")
    pace = profile.get("run_threshold_pace_sec_per_km")
    if pace is not None:
        parts.append(f"run threshold {int(pace) // 60}:{int(pace) % 60:02d}/km")
    return "; ".join(parts) + "."


def context_block(ctx: PanelContext) -> str:
    fasting = {True: "fasted", False: "not fasted", None: "fasting unknown"}[ctx.fasting]
    lines = [
        "Draw context: "
        + fasting
        + (f", drawn at {ctx.draw_time.strftime('%H:%M')}" if ctx.draw_time else ", time unknown")
        + ".",
        "  supplements: " + (", ".join(ctx.supplements) or "none reported"),
        "  diet pattern: " + (ctx.diet_pattern or "not given"),
        "  symptoms: " + (", ".join(ctx.symptoms) or "none reported"),
    ]
    if ctx.notes:
        lines.append("  notes: " + ctx.notes)
    return "\n".join(lines)


def _mins(sec: int | None) -> str:
    return "-" if sec is None else f"{round(sec / 60)} min"


def training_block(t: TrainingContext) -> str:
    def n(v: float | None) -> str:
        return "-" if v is None else f"{v:g}"

    lines = [
        f"Training context around {t.drawn_on.isoformat()}: CTL {n(t.ctl)}, ATL {n(t.atl)}, "
        f"TSB {n(t.tsb)}, TSS over the previous 7 days {n(t.tss_7d)}.",
        f"  sleep {_mins(t.sleep_2n_avg_sec)} vs {_mins(t.sleep_30d_avg_sec)} (two nights before "
        f"the draw vs 30-day mean); HRV {t.hrv_2n_avg if t.hrv_2n_avg is not None else '-'} vs "
        f"{t.hrv_30d_avg if t.hrv_30d_avg is not None else '-'}.",
    ]
    if t.last_sessions:
        lines.append("  sessions in the 72 h before the draw, hardest first:")
        for s in t.last_sessions:
            tss = "-" if s.get("tss") is None else f"{float(s['tss']):g} TSS"
            lines.append(
                f"    {s.get('date')} {s.get('sport')} {s.get('duration_min')} min, {tss}: "
                f"{s.get('title')}"
            )
    else:
        lines.append("  no completed sessions in the 72 h before the draw.")
    return "\n".join(lines)


def _shown(f: Finding) -> str:
    """The value as the lab printed it: raw_value verbatim for a bounded row whose value was
    not unit-converted, else '<bound><value>'; the plain value otherwise."""
    if f.bound:
        parsed = parse_value(f.raw_value)
        if parsed is not None and parsed[0] == f.value:
            return f.raw_value
        return f"{f.bound}{_g(f.value)}"
    return _g(f.value)


def _finding_line(f: Finding) -> str:
    status: str = f.functional_status
    if status == "indeterminate":
        status = f"indeterminate (reported as {f.raw_value})"
    line = (
        f"- {f.display}: {_shown(f)} {f.unit} — {status} "
        f"(functional {format_range(*f.functional_range)}; conventional {f.conventional_status})"
    )
    if f.previous is not None:
        prev_date, prev_value = f.previous
        delta = "" if f.delta_pct is None else f" ({f.delta_pct:+.1f}%)"
        line += f"; previous {_g(prev_value)} on {prev_date.isoformat()}{delta}"
    if f.active_confounders:
        line += "; confounders: " + ", ".join(f.active_confounders)
    return line


def findings_block(findings: list[Finding], registry: MarkerRegistry) -> str:
    by_system: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_system[f.system].append(f)
    lines = [f"Findings (ranges version {registry.version}):"]
    for system, fs in by_system.items():
        lines.append(f"## {system}")
        flagged = [f for f in fs if f.functional_status != "optimal"]
        optimal = [f for f in fs if f.functional_status == "optimal"]
        for f in flagged:
            lines.append(_finding_line(f))
            if f.athlete_note:
                lines.append(f"  note: {f.athlete_note}")
            lines.append("  sources: " + "; ".join(registry.get(f.marker).sources))
        if optimal:
            lines.append(
                "optimal: "
                + ", ".join(
                    f"{f.display} {_shown(f)} {f.unit} ({format_range(*f.functional_range)})"
                    for f in optimal
                )
            )
    return "\n".join(lines)


def render_report_prompt(
    findings: list[Finding],
    context: PanelContext,
    training: TrainingContext,
    previous_priorities: str | None,
    profile: dict[str, Any] | None,
    registry: MarkerRegistry,
    *,
    has_previous: bool,
) -> str:
    parts = [
        profile_block(profile, registry.sex),
        context_block(context),
        training_block(training),
        findings_block(findings, registry),
    ]
    if previous_priorities:
        parts.append("Previous report priorities:\n" + previous_priorities)
    else:
        parts.append("Previous report priorities: none.")
    if has_previous:
        parts.append(
            f"A previous panel exists: include the section '## {CHANGES_TITLE}' and use the "
            "previous values and deltas given above."
        )
    else:
        parts.append("This is the first panel: no changes section.")
    parts.append("Write the report now.")
    return "\n\n".join(parts)
