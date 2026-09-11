# tri-wellness Plan 3 of 3: Report and Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tri-wellness report` (evaluate a stored panel, one streaming model call with a fixed ten-section structure, saved to `lab_reports`), `tri-wellness chat` (a `create_agent` loop over the read-only SQL tool and three findings tools), `tri-wellness panels`, and a LangSmith dataset of findings sets with code evaluators that check every report cites a functional range for every non-optimal marker. This is spec milestone 3 and completes v1.

**Architecture:** Python assembles everything the model needs (findings from Plan 1's `evaluate`, the panel context, the training context, the previous report's priorities, the athlete profile) into one prompt; the model writes prose. The report is one streaming call in `report.py`, shared with the evaluation target through `ReportWriter`. Chat is the tri-analyze pattern: `create_agent` with tools bound in a fixed order, an in-process `InMemorySaver` for conversation memory, a system prompt rendered once per session. The findings tools are thin wrappers over Plan 1's `repo` and `evaluate`.

**Tech Stack:** `langchain.agents.create_agent`, `langchain-anthropic` (streaming, prompt caching middleware), `langsmith` (`aevaluate`), typer, rich. Depends on Plans 1 and 2 (`tri_wellness.labs.*`, `ranges.registry`, `repo`, `repl`, `graph.llm`, `testing`).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-wellness-design.md` (§3 overview, §4 layout, §10 report, §11 chat, §12 commands, §13 error handling, §15 testing, §16 observability, §17 milestone 3, §19 item 3).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- `tri-wellness` depends on `tri-core` only; the chat REPL and agent constructor are copied from tri-analyze, not imported.
- The report structure is spec §10's ten sections in that order, as `##` headings with these exact titles: `Draw conditions`, `By system`, `Priorities`, `Training implications`, `Levers`, `Supplements`, `Retest plan`, `Questions for your practitioner`, and `Changes since last panel` when a previous panel exists. The first non-empty line is the disclaimer, verbatim.
- Prompt rules (spec §10): cite the functional range used for every flagged marker; name confounders when they apply; distinguish "pattern suggests" from "marker shows"; no generic wellness advice; do not restate optimal markers beyond the one-line system summary. The model never sees a raw value without its status and functional range.
- Chat tools in this fixed order (spec §11): `query_training_db`, `get_panel_findings`, `get_marker_spec`, `get_marker_history`. REPL commands `/panels`, `/report [ID]`, `/prompt`, `/tools`, `/quit`.
- Report runs carry LangSmith tags `panel_id:<id>` and `ranges_version:<version>` (spec §16). `report`, `chat` and `panels` do not need the checkpointer (spec §13).
- Re-running `report` on a panel makes a new `lab_reports` row (spec §5).
- **Execute in a sibling worktree** on branch `feat/tri-wellness-03` from `main` after Plan 2 is merged.
- Definition of done per task: `uv run ruff format packages/tri-wellness && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited is copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`make_query_tool` gains `extra_doc: str = ""`** (spec §19 item 3: `SCHEMA_DOC` is a module constant with no parameter). The wellness tables are documented in `tri_wellness.tools.findings.WELLNESS_SCHEMA_DOC` and appended at bind time. Existing callers pass one argument and are unchanged.
- **Optimal markers appear in the prompt as one compact line per system with their functional range**, so the rule "never a raw value without its status and range" holds for them too, while the report is told to give optimal systems one line.
- **"Previous report's priorities section"** is the `## Priorities` section of the most recent report of the most recent earlier panel (`repo.latest_report_before(conn, panel_id)`, added here). The same `extract_section` helper feeds the chat prompt's priorities and retest plan.
- **The athlete profile in the prompt** is `athlete_profile`'s thresholds and weight (the analyze pattern) plus the configured sex from the registry; there is no wellness-specific profile in v1.
- **`/report [ID]` takes a panel id** and prints that panel's latest saved report; with no id, the latest panel's. A report id is not what the athlete remembers.
- **Chat commands receive the rest of the line** (`Callable[[str], Awaitable[str]]`), unlike analyze's no-argument commands, because `/report 3` needs an argument.
- **Findings JSON for the tools omits `athlete_note`** (get_marker_spec returns it) to keep `get_panel_findings` compact; everything else in `Finding` is included, plus the panel header and training context.
- **Evaluators are code only, no LLM judge** (spec §16 asks for "a code evaluator"): `cites_functional_ranges`, `has_required_sections`, `names_active_confounders`. Cases are stored as `LabResult` inputs, not findings, so the dataset stays valid when `markers.yaml` changes; the target runs `evaluate` with the current registry before writing.
- **`MAX_TOKENS` stays at Plan 2's 32000** for the report model; a ten-section report is long.

---

## File Structure

```
packages/tri-core/src/tri_core/db/sql_tool.py      make_query_tool(url, extra_doc="")
packages/tri-core/tests/test_sql_tool.py           one new test
packages/tri-wellness/src/tri_wellness/
  repo.py                 + latest_report_before()
  report.py               extract_section(), athlete_profile(), ReportWriter, run_report()
  agent.py                build_agent()
  prompts/report.py       PROMPT_VERSION, DISCLAIMER, SECTION_TITLES, CHANGES_TITLE, REPORT_RULES,
                          REPORT_SYSTEM, profile_block(), context_block(), training_block(),
                          findings_block(), render_report_prompt()
  prompts/chat.py         render_chat_prompt()
  tools/__init__.py
  tools/findings.py       WELLNESS_SCHEMA_DOC, make_findings_tools()
  repl.py                 + text_of(), render_panels(), TurnPrinter, run_chat_turn(), chat_loop()
  evals/__init__.py, cases.py, target.py, evaluators.py, run.py
  cli.py                  + report, chat, panels, eval
  testing.py              + seed_panel(), REPORT_OK (a canned report that passes the evaluators)
packages/tri-wellness/tests/
  test_report_prompt.py, test_report.py (db), test_tools.py (db), test_chat.py, test_panels.py,
  test_evals.py, test_cli.py (+ three tests)
```

Responsibilities: `prompts/` renders text and never touches a database. `report.py` is the one place a report is produced (CLI and evaluation target both use `ReportWriter`). `tools/findings.py` is the only tool code. `repl.py` keeps every terminal concern. `evals/` is self-contained and imports only `report`, `prompts` and `labs`.

---

### Task 1: SQL tool schema extension, `panels`

**Files:**
- Modify: `packages/tri-core/src/tri_core/db/sql_tool.py:150-165` (`make_query_tool`), `packages/tri-core/tests/test_sql_tool.py`, `packages/tri-wellness/src/tri_wellness/repl.py` (append `render_panels`), `packages/tri-wellness/src/tri_wellness/cli.py` (append `panels`), `packages/tri-wellness/tests/test_cli.py`
- Create: `packages/tri-wellness/src/tri_wellness/tools/__init__.py`, `packages/tri-wellness/src/tri_wellness/tools/findings.py` (the doc constant only; the tools arrive in Task 3)
- Test: `packages/tri-wellness/tests/test_panels.py`

**Interfaces:**
- Produces: `tri_core.db.sql_tool.make_query_tool(url: str, extra_doc: str = "") -> BaseTool`; `tri_wellness.tools.findings.WELLNESS_SCHEMA_DOC: str`; `tri_wellness.repl.render_panels(summaries: list[PanelSummary]) -> str`; `tri-wellness panels`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-core/tests/test_sql_tool.py`:
```python


def test_make_query_tool_extra_doc_is_appended():
    from tri_core.db.sql_tool import SCHEMA_DOC, make_query_tool

    plain = make_query_tool("postgresql://x/y")
    assert plain.description.endswith(SCHEMA_DOC)
    extended = make_query_tool("postgresql://x/y", extra_doc="lab_panels: id, drawn_on")
    assert extended.description.endswith("lab_panels: id, drawn_on")
    assert SCHEMA_DOC in extended.description
```

`packages/tri-wellness/tests/test_panels.py`:
```python
from datetime import date

from tri_wellness.labs.models import PanelSummary
from tri_wellness.repl import render_panels
from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC


def test_render_panels_table():
    rows = [
        PanelSummary(id=3, drawn_on=date(2026, 8, 20), lab_name="Quest", result_count=42, unmapped_count=2, has_report=True),
        PanelSummary(id=1, drawn_on=date(2026, 3, 1), lab_name=None, result_count=30, unmapped_count=0, has_report=False),
    ]
    text = render_panels(rows)
    lines = text.splitlines()
    assert lines[0].split() == ["id", "drawn", "lab", "results", "unmapped", "report"]
    assert "3" in lines[1] and "2026-08-20" in lines[1] and "Quest" in lines[1] and "42" in lines[1] and "yes" in lines[1]
    assert "2026-03-01" in lines[2] and "-" in lines[2] and "no" in lines[2]
    assert render_panels([]) == "no panels stored; run `tri-wellness ingest <file>`"


def test_schema_doc_names_the_lab_tables():
    for table in ("lab_panels", "lab_results", "lab_reports"):
        assert table in WELLNESS_SCHEMA_DOC
    assert "marker" in WELLNESS_SCHEMA_DOC and "ferritin" in WELLNESS_SCHEMA_DOC
```

Append to `packages/tri-wellness/tests/test_cli.py`:
```python


def test_help_lists_panels():
    result = runner.invoke(app, ["--help"])
    assert "panels" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-core/tests/test_sql_tool.py packages/tri-wellness/tests/test_panels.py packages/tri-wellness/tests/test_cli.py -q`
Expected: `TypeError: make_query_tool() got an unexpected keyword argument 'extra_doc'`; `ImportError: cannot import name 'render_panels'`; `panels` missing from help.

- [ ] **Step 3: Extend the SQL tool**

In `packages/tri-core/src/tri_core/db/sql_tool.py` replace the `make_query_tool` signature and the description line:
```python
def make_query_tool(url: str, extra_doc: str = "") -> BaseTool:
    """The read-only SQL tool. `extra_doc` documents tables an agent adds (appended after
    SCHEMA_DOC)."""

    @tool("query_training_db")
    def query_training_db(sql: str) -> str:
        """Run one read-only SQL SELECT against the athlete's training database and return JSON.

        Use this for anything about past workouts, planned vs actual, weekly volume, training
        load (CTL/ATL/TSB), sleep, HRV, readiness, and the athlete's zones and thresholds.
        Do arithmetic in SQL (sums, averages, group by week), not in your head.
        Rows are capped at 200; aggregate rather than listing raw rows for long windows.
        """
        return json.dumps(run_readonly_query(url, sql), default=str)

    doc = SCHEMA_DOC + ("\n" + extra_doc if extra_doc else "")
    query_training_db.description = (query_training_db.description or "") + "\n" + doc
    return query_training_db
```

- [ ] **Step 4: Write the schema doc, the panels renderer and the command**

`packages/tri-wellness/src/tri_wellness/tools/__init__.py`: empty.

`packages/tri-wellness/src/tri_wellness/tools/findings.py` (Task 3 appends the tools):
```python
"""Chat tools over the lab tables: the schema doc for query_training_db and three findings
tools (get_panel_findings, get_marker_spec, get_marker_history)."""

from __future__ import annotations

WELLNESS_SCHEMA_DOC = """\
lab_panels (wellness agent; one row per lab draw): id, drawn_on date, lab_name, source_kind
  ('pdf'|'export'|'manual'), context jsonb (fasting bool, draw_time, supplements [], diet_pattern,
  symptoms [], notes), raw_extract jsonb (every printed row, mapped or not), created_at.
lab_results (one row per mapped marker per panel): panel_id, marker text (canonical key such as
  ferritin, hs_crp, vitamin_d, testosterone_total; see get_marker_spec), value numeric in the
  canonical unit, unit, raw_name (what the lab printed), raw_value, lab_ref_low, lab_ref_high,
  flag (the lab's H/L).
lab_reports: id, panel_id, ranges_version, findings jsonb (list of Finding: marker, value,
  functional_status, functional_range, previous, delta_pct, active_confounders), report_md,
  created_at. Several reports per panel are possible; the newest id is current.

Examples:
  -- every ferritin value, oldest first
  select p.drawn_on, r.value, r.unit from lab_results r join lab_panels p on p.id = r.panel_id
  where r.marker = 'ferritin' order by 1;
  -- load and sleep in the week before a draw
  select metric_date, tss_day, ctl, atl, sleep_seconds, hrv_overnight_avg from daily_metrics
  where metric_date between date '2026-08-13' and date '2026-08-20' order by 1;
  -- sessions in the 72 h before a draw
  select workout_date, sport, title, actual_duration_sec, actual_tss from workouts
  where completed and workout_date between date '2026-08-17' and date '2026-08-19' order by 1;
"""
```

Append to `packages/tri-wellness/src/tri_wellness/repl.py`:
```python


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
```
and add `PanelSummary` to the `tri_wellness.labs.models` import at the top of `repl.py`.

Append to `packages/tri-wellness/src/tri_wellness/cli.py` (before the `if __name__` block):
```python


def _settings_or_exit() -> Any:
    try:
        return get_wellness_settings()
    except ValidationError:
        console.print("TRI_ATHLETE_SEX must be set to male or female in .env", style="red")
        raise typer.Exit(code=2) from None


@app.command()
def panels() -> None:
    """List stored panels: date, lab, result count, unmapped count, whether a report exists."""
    from tri_core.db.connection import connect
    from tri_wellness import repo
    from tri_wellness.repl import render_panels

    settings = _settings_or_exit()
    with connect(settings.database_url) as conn:
        console.print(render_panels(repo.list_panels(conn)), markup=False, highlight=False)
```
and refactor `_ingest` to use `_settings_or_exit()` (it raises `typer.Exit`, so `_ingest`'s own `except ValidationError` block goes away; `asyncio.run` propagates `typer.Exit` as-is).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-core packages/tri-wellness -q`
Expected: all pass. `uv run tri-wellness panels` against the real database prints the panel from Plan 2.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): panels command; query tool takes extra schema doc"
```

---

### Task 2: Report prompt, `ReportWriter`, `run_report`, `tri-wellness report`

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/prompts/report.py`, `packages/tri-wellness/src/tri_wellness/report.py`
- Modify: `packages/tri-wellness/src/tri_wellness/repo.py` (append `latest_report_before`), `packages/tri-wellness/src/tri_wellness/repl.py` (append `text_of`), `packages/tri-wellness/src/tri_wellness/testing.py` (append `seed_panel`), `packages/tri-wellness/src/tri_wellness/cli.py` (append `report`), `packages/tri-wellness/tests/test_repo.py` (one test)
- Test: `packages/tri-wellness/tests/test_report_prompt.py`, `packages/tri-wellness/tests/test_report.py` (db)

**Interfaces:**
- Consumes: Plan 1 `evaluate`, `load_training_context`, `repo.*`, `Finding`, `PanelContext`, `TrainingContext`, `MarkerRegistry`; Plan 2 `make_model`.
- Produces: `PROMPT_VERSION = "1"`, `DISCLAIMER`, `SECTION_TITLES: tuple[str, ...]`, `CHANGES_TITLE`, `REPORT_RULES`, `REPORT_SYSTEM`; `profile_block(profile) -> str`, `context_block(ctx) -> str`, `training_block(t) -> str`, `findings_block(findings, registry) -> str`; `render_report_prompt(findings, context, training, previous_priorities, profile, registry, has_previous) -> str`; `extract_section(md, title) -> str | None`; `athlete_profile(conn) -> dict[str, Any] | None`; `ReportWriter(model).write(prompt, out, tags) -> str`; `run_report(model, connect, registry, panel_id, out, out_path) -> int`; `repo.latest_report_before(conn, panel_id) -> StoredReport | None`; `repl.text_of(msg) -> str`; `testing.seed_panel(conn, drawn_on, rows, lab="Quest", context=None) -> int` where `rows` is `[(marker, value, unit), ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/tri-wellness/tests/test_repo.py`:
```python


def test_latest_report_before(wdb):
    p1 = panel(wdb, D1, [lr("ferritin", 35.0)])
    p2 = panel(wdb, D2, [lr("ferritin", 40.0)])
    p3 = panel(wdb, D3, [lr("ferritin", 48.0)])
    assert repo.latest_report_before(wdb, p1) is None
    assert repo.latest_report_before(wdb, p2) is None  # p1 has no report yet
    repo.insert_report(wdb, p1, "v", [], "# one")
    r1b = repo.insert_report(wdb, p1, "v", [], "# one again")
    repo.insert_report(wdb, p3, "v", [], "# three")
    got = repo.latest_report_before(wdb, p2)
    assert got is not None and got.id == r1b and got.report_md == "# one again"
    assert repo.latest_report_before(wdb, p3).panel_id == p1  # p2 has none; falls back to p1
```

`packages/tri-wellness/tests/test_report_prompt.py`:
```python
from datetime import date, time

import pytest

from tri_wellness.labs.evaluate import evaluate
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, TrainingContext
from tri_wellness.prompts.report import (
    CHANGES_TITLE,
    DISCLAIMER,
    REPORT_RULES,
    REPORT_SYSTEM,
    SECTION_TITLES,
    findings_block,
    render_report_prompt,
)
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import extract_section

D = date(2026, 8, 20)


@pytest.fixture(scope="module")
def reg():
    return load_registry("male", MARKERS_PATH)


def lr(marker, value, unit):
    return LabResult(marker=marker, value=value, unit=unit, raw=RawResult(name=marker, value=str(value), unit=unit))


@pytest.fixture
def findings(reg):
    results = [
        lr("ferritin", 42.0, "ng/mL"),
        lr("hs_crp", 1.8, "mg/L"),
        lr("hemoglobin", 15.1, "g/dL"),
        lr("tsh", 1.5, "mIU/L"),
    ]
    hard = {"date": "2026-08-19", "sport": "bike", "duration_min": 180, "tss": 210, "title": "long ride"}
    training = TrainingContext(drawn_on=D, ctl=62.0, atl=80.0, tsb=-18.0, tss_7d=520.0, last_sessions=[hard], sleep_2n_avg_sec=24000, sleep_30d_avg_sec=27000, hrv_2n_avg=52, hrv_30d_avg=60)
    return evaluate(results, reg, {"ferritin": (date(2026, 3, 1), 35.0)}, PanelContext(fasting=True, draw_time=time(7, 30)), training), training


def test_system_prompt_has_structure_and_rules():
    assert DISCLAIMER in REPORT_SYSTEM
    for title in SECTION_TITLES:
        assert f"## {title}" in REPORT_SYSTEM
    assert CHANGES_TITLE in REPORT_SYSTEM
    assert "pattern suggests" in REPORT_RULES and "no generic" in REPORT_RULES.lower()
    assert REPORT_RULES in REPORT_SYSTEM


def test_findings_block_groups_by_system_and_never_shows_a_bare_value(reg, findings):
    fs, _ = findings
    text = findings_block(fs, reg)
    assert text.index("## iron") < text.index("## inflammation")
    assert "Ferritin: 42 ng/mL" in text and "suboptimal_low" in text and "functional 50-150" in text
    assert "previous 35 on 2026-03-01 (+20.0%)" in text
    assert "confounders: recent_hard_session, inflammation" in text
    assert "hs-CRP: 1.8 mg/L" in text and "functional -1" in text  # one-sided range
    # optimal markers: one compact line per system, still with their range
    assert "optimal: Hemoglobin 15.1 g/dL (14-15.5)" in text
    assert "optimal: TSH 1.5 mIU/L (1-2)" in text
    # athlete note and sources travel with flagged markers only
    assert "acute-phase reactant" in text
    assert "Weatherby" in text
    assert text.count("note:") == 2


def test_render_report_prompt_sections(reg, findings):
    fs, training = findings
    ctx = PanelContext(fasting=False, draw_time=time(14, 0), supplements=["iron 25 mg"], symptoms=["fatigue"], notes="week 3 of build")
    profile = {"ftp_watts": 260, "weight_kg": 74.5, "lthr_bpm": 165, "run_threshold_pace_sec_per_km": 255, "swim_css_sec_per_100m": None, "max_hr_bpm": 188}
    text = render_report_prompt(fs, ctx, training, "1. Ferritin first.\n2. Sleep.", profile, reg, has_previous=True)
    assert "Athlete:" in text and "male" in text and "260 W" in text and "74.5 kg" in text
    assert "not fasted" in text and "14:00" in text and "iron 25 mg" in text and "fatigue" in text and "week 3 of build" in text
    assert "CTL 62" in text and "ATL 80" in text and "TSB -18" in text and "520" in text
    assert "long ride" in text and "210" in text
    assert "sleep 400 min vs 450 min" in text and "HRV 52 vs 60" in text
    assert "Previous report priorities:" in text and "Ferritin first" in text
    assert f"include the section '## {CHANGES_TITLE}'" in text
    first = render_report_prompt(fs, ctx, training, None, None, reg, has_previous=False)
    assert "first panel" in first and CHANGES_TITLE not in first
    assert "thresholds: not available" in first


def test_extract_section():
    md = "line\n\n## Draw conditions\nfasted\n\n## Priorities\n1. A\n2. B\n\n## Levers\nx\n"
    assert extract_section(md, "Priorities") == "1. A\n2. B"
    assert extract_section(md, "Levers") == "x"
    assert extract_section(md, "Missing") is None
    assert extract_section("## 3. Priorities\nA\n## Next\n", "Priorities") == "A"
    assert extract_section("### Priorities\nA", "Priorities") is None  # only level-2 headings
```

`packages/tri-wellness/tests/test_report.py`:
```python
from datetime import date

import pytest
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel
from tri_wellness import repo
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.report import ReportWriter, run_report
from tri_wellness.testing import REPORT_OK, seed_daily_metrics, seed_panel

pytestmark = pytest.mark.db
D1, D2 = date(2031, 1, 15), date(2031, 4, 15)


@pytest.fixture
def reg():
    return load_registry("male", MARKERS_PATH)


def connect_factory(nocommit):
    import contextlib

    return lambda: contextlib.nullcontext(nocommit)


async def test_writer_streams_and_returns_full_text():
    model = ScriptedChatModel(script=[AIMessage(content="# hello\n\nworld")])
    chunks = []
    text = await ReportWriter(model).write("prompt", chunks.append, ["panel_id:1"])
    assert text == "# hello\n\nworld" and "".join(chunks) == text


async def test_run_report_evaluates_saves_and_writes_file(nocommit, reg, tmp_path):
    seed_daily_metrics(nocommit, [{"metric_date": D2, "ctl": 60.0, "atl": 80.0, "tsb": -20.0}])
    p1 = seed_panel(nocommit, D1, [("ferritin", 35.0, "ng/mL")])
    repo.insert_report(nocommit, p1, "old", [], "## Priorities\n1. Iron.\n\n## Retest plan\nMarch")
    p2 = seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    out = []
    path = tmp_path / "report.md"
    code = await run_report(model, connect_factory(nocommit), reg, None, out.append, path)
    assert code == 0
    assert path.read_text() == REPORT_OK
    saved = repo.latest_report_for_panel(nocommit, p2)
    assert saved is not None and saved.report_md == REPORT_OK and saved.ranges_version == reg.version
    fer = next(f for f in saved.findings if f.marker == "ferritin")
    assert fer.previous == (D1, 35.0) and fer.delta_pct == 20.0
    assert fer.active_confounders == [] and "high_acute_load" not in fer.active_confounders
    joined = "".join(out)
    assert REPORT_OK in joined and f"saved report {saved.id} for panel {p2}" in joined
    # the prompt carried the previous priorities: check what the model received
    # (ScriptedChatModel does not record; covered by test_report_prompt) and that a second run
    # adds a row rather than replacing
    model2 = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    assert await run_report(model2, connect_factory(nocommit), reg, p2, out.append, None) == 0
    assert repo.latest_report_for_panel(nocommit, p2).id > saved.id


async def test_run_report_without_panels_or_with_bad_id(nocommit, reg):
    out = []
    assert await run_report(ScriptedChatModel(script=[]), connect_factory(nocommit), reg, None, out.append, None) == 1
    assert any("no panels" in s for s in out)
    assert await run_report(ScriptedChatModel(script=[]), connect_factory(nocommit), reg, 999999, out.append, None) == 1
    assert any("no panel 999999" in s for s in out)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_report_prompt.py packages/tri-wellness/tests/test_report.py packages/tri-wellness/tests/test_repo.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.prompts.report'`; `AttributeError: module 'tri_wellness.repo' has no attribute 'latest_report_before'`.

- [ ] **Step 3: Repo, seed and text helpers**

Append to `packages/tri-wellness/src/tri_wellness/repo.py`:
```python


def latest_report_before(conn: Conn, panel_id: int) -> StoredReport | None:
    """The newest report of the most recent earlier panel that has one (earlier by
    (drawn_on, id))."""
    row = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select x.* from lab_reports x
        join lab_panels p on p.id = x.panel_id
        cross join me
        where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        order by p.drawn_on desc, p.id desc, x.id desc
        limit 1
        """,
        (panel_id,),
    ).fetchone()
    return _report(row) if row else None
```

Append to `packages/tri-wellness/src/tri_wellness/testing.py`:
```python


def seed_panel(
    conn: Conn,
    drawn_on: date,
    rows: list[tuple[str, float, str]],
    lab: str | None = "Quest",
    context: PanelContext | None = None,
) -> int:
    """One stored panel from (marker, value, unit) rows; the raw row is synthesized."""
    results = [
        LabResult(
            marker=m, value=v, unit=u, raw=RawResult(name=m, value=str(v), unit=u)
        )
        for m, v, u in rows
    ]
    return repo.insert_panel(
        conn,
        drawn_on=drawn_on,
        lab_name=lab,
        source_file=None,
        source_kind="manual",
        context=context or PanelContext(fasting=True),
        raw_extract=[r.raw for r in results],
        results=results,
    )


REPORT_OK = """\
This is an educational interpretation of lab values against functional-medicine ranges for one \
athlete, prepared for discussion with a qualified practitioner; it is not a diagnosis or a \
prescription.

## Draw conditions
Fasted, 07:30 draw. Active confounders: recent hard session (long ride, 210 TSS, the day \
before), which raises ferritin, hs-CRP and CK for 24-72 h; weight it heavily for those three.

## By system
### Iron
Ferritin shows 42 ng/mL against a functional range of 50-150 (conventional in range, 30-400). \
With hs-CRP mildly up, the pattern suggests true stores are lower still; the inflammation \
confounder applies to ferritin as well as the recent hard session.
### Inflammation
hs-CRP shows 1.8 mg/L against a functional high of 1 (conventional under 3). The recent hard \
session confounder applies.
### Thyroid
All optimal.
### CBC
All optimal.

## Priorities
1. Iron stores: ferritin 42 (functional 50-150) with a mild hs-CRP rise.
2. Recovery: the draw followed a 210 TSS ride; retest rested before acting on CK.

## Training implications
Hold intensity for two weeks; keep long rides under 3 h until ferritin is retested.

## Levers
Red meat or heme iron three times a week, paired with vitamin C; no coffee within an hour of \
iron-rich meals.

## Supplements
Iron bisglycinate 25 mg every other morning for 8 weeks, target ferritin above 50; retest \
shows it worked. Discuss with your practitioner.

## Retest plan
Ferritin, hs-CRP, CBC in 8 weeks, fasted, 48 h after the last hard session.

## Questions for your practitioner
1. Is a full iron panel with transferrin saturation warranted now?

## Changes since last panel
Ferritin 35 -> 42 (+20.0%) since 2031-01-15.
"""
```
with `from datetime import date`, `from tri_wellness import repo` and `from tri_wellness.labs.models import LabResult, PanelContext, RawResult` added to the module's imports.

Append to `packages/tri-wellness/src/tri_wellness/repl.py`:
```python


def text_of(msg: BaseMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)
```
with `from langchain_core.messages import BaseMessage` added to its imports.

- [ ] **Step 4: Write the prompt**

`packages/tri-wellness/src/tri_wellness/prompts/report.py`:
```python
"""Report prompt: fixed structure, fixed rules, and the blocks that turn findings and contexts
into text the model can reason over. Every value the model sees carries its status and range."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from tri_wellness.labs.models import Finding, PanelContext, TrainingContext
from tri_wellness.ranges.registry import MarkerRegistry

PROMPT_VERSION = "1"  # bump when REPORT_SYSTEM or REPORT_RULES changes; names the eval experiment

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
table. You explain patterns; you do not re-judge the numbers.

Write markdown with exactly this structure, these level-2 headings, in this order:

{DISCLAIMER}

## {SECTION_TITLES[0]}
Fasting, timing, active confounders, and how much weight each carries.
## {SECTION_TITLES[1]}
One level-3 heading per system that has at least one non-optimal marker, describing what the
pattern across its markers says; systems that are entirely optimal get one line each.
## {SECTION_TITLES[2]}
At most three, ranked, with reasoning.
## {SECTION_TITLES[3]}
Load, intensity and recovery over the coming weeks, written so it could be pasted into a
training-plan constraint.
## {SECTION_TITLES[4]}
Nutrition, sleep, stress and training changes tied to specific findings.
## {SECTION_TITLES[5]}
Compound, dose range, timing, target marker, and what would show it worked. Framed for
discussion with a practitioner.
## {SECTION_TITLES[6]}
Which markers, when, and under what draw conditions.
## {SECTION_TITLES[7]}
## {CHANGES_TITLE}
Only when the prompt says a previous panel exists.

The first line of your answer is the disclaimer above, verbatim.

{REPORT_RULES}"""


def _g(v: Any) -> str:
    return f"{float(v):g}"


def _range(low: float | None, high: float | None) -> str:
    return f"{'' if low is None else _g(low)}-{'' if high is None else _g(high)}"


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


def _finding_line(f: Finding) -> str:
    line = (
        f"- {f.display}: {_g(f.value)} {f.unit} — {f.functional_status} "
        f"(functional {_range(*f.functional_range)}; conventional {f.conventional_status})"
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
                    f"{f.display} {_g(f.value)} {f.unit} ({_range(*f.functional_range)})"
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
```

- [ ] **Step 5: Write the report module and the command**

`packages/tri-wellness/src/tri_wellness/report.py`:
```python
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
```

Append to `packages/tri-wellness/src/tri_wellness/cli.py`:
```python


@app.command()
def report(
    panel: int | None = typer.Option(None, "--panel", help="Panel id (default: latest)"),
    out: Path | None = typer.Option(None, "--out", help="Also write the markdown here"),
) -> None:
    """Evaluate a stored panel and write the interpretation (saved to lab_reports)."""
    raise typer.Exit(code=asyncio.run(_report(panel, out)))


async def _report(panel: int | None, out_path: Path | None) -> int:
    from tri_core.db.connection import connect
    from tri_wellness.graph.llm import make_model
    from tri_wellness.ranges.registry import load_registry
    from tri_wellness.report import run_report

    settings = _settings_or_exit()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    url = settings.database_url
    return await run_report(
        make_model(settings),
        lambda: connect(url),
        load_registry(settings.tri_athlete_sex),
        panel,
        _out,
        out_path,
    )
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass. In `test_run_report_evaluates_saves_and_writes_file`, `has_previous` is true (ferritin has a previous value) and the prior priorities come from panel 1's report; the ATL 80 vs CTL 60 row on D2 fires `high_acute_load`, which ferritin does not declare, hence the empty confounder list. `uv run tri-wellness report --out /tmp/report.md` against the real panel from Plan 2 prints the streamed report and saves it.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): report prompt, streaming report writer, report command"
```

---

### Task 3: Findings tools (`tools/findings.py`)

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/tools/findings.py` (append the tools)
- Test: `packages/tri-wellness/tests/test_tools.py` (db)

**Interfaces:**
- Consumes: Plan 1 `repo`, `evaluate`, `functional_status`, `load_training_context`, `MarkerRegistry`; Task 2 `ConnectFactory`.
- Produces: `make_findings_tools(connect: ConnectFactory, registry: MarkerRegistry) -> list[BaseTool]` returning, in order, `get_panel_findings(panel: str = "latest")`, `get_marker_spec(marker: str)`, `get_marker_history(marker: str)`; each returns a JSON string, errors as `{"error": "..."}`.

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_tools.py`:
```python
import contextlib
import json
from datetime import date

import pytest

from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import seed_daily_metrics, seed_panel
from tri_wellness.tools.findings import make_findings_tools

pytestmark = pytest.mark.db
D1, D2 = date(2031, 1, 15), date(2031, 4, 15)


@pytest.fixture
def tools(nocommit):
    reg = load_registry("male", MARKERS_PATH)
    return make_findings_tools(lambda: contextlib.nullcontext(nocommit), reg)


def test_tool_names_and_order(tools):
    assert [t.name for t in tools] == ["get_panel_findings", "get_marker_spec", "get_marker_history"]
    assert "latest" in tools[0].description and "alias" in tools[1].description


def test_get_panel_findings_latest_and_by_id(nocommit, tools):
    seed_daily_metrics(nocommit, [{"metric_date": D2, "ctl": 60.0, "atl": 80.0, "tsb": -20.0}])
    p1 = seed_panel(nocommit, D1, [("ferritin", 35.0, "ng/mL")])
    p2 = seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL"), ("cortisol_am", 12.0, "ug/dL")])
    findings_tool = tools[0]
    out = json.loads(findings_tool.invoke({"panel": "latest"}))
    assert out["panel"]["id"] == p2 and out["panel"]["drawn_on"] == "2031-04-15"
    assert out["panel"]["context"]["fasting"] is True
    assert out["training"]["atl"] == 80.0 and out["ranges_version"]
    by_marker = {f["marker"]: f for f in out["findings"]}
    fer = by_marker["ferritin"]
    assert fer["functional_status"] == "suboptimal_low" and fer["functional_range"] == [50.0, 150.0]
    assert fer["previous"] == ["2031-01-15", 35.0] and fer["delta_pct"] == 20.0
    assert "athlete_note" not in fer and fer["display"] == "Ferritin"
    assert by_marker["cortisol_am"]["active_confounders"] == ["high_acute_load"]
    first = json.loads(findings_tool.invoke({"panel": str(p1)}))
    assert first["panel"]["id"] == p1 and first["findings"][0]["previous"] is None
    assert "error" in json.loads(findings_tool.invoke({"panel": "999999"}))
    assert "error" in json.loads(findings_tool.invoke({"panel": "x"}))


def test_get_panel_findings_without_panels(tools):
    assert "no panels" in json.loads(tools[0].invoke({"panel": "latest"}))["error"]


def test_get_marker_spec_by_key_or_alias(tools):
    spec = json.loads(tools[1].invoke({"marker": "Ferritin, Serum"}))
    assert spec["key"] == "ferritin" and spec["unit"] == "ng/mL"
    assert spec["conventional"] == {"low": 30.0, "high": 400.0}
    assert spec["functional"] == {"low": 50.0, "high": 150.0}
    assert spec["sex"] == "male" and "acute-phase" in spec["athlete_note"]
    assert spec["confounders"] == ["recent_hard_session", "inflammation"] and spec["sources"]
    assert json.loads(tools[1].invoke({"marker": "hs_crp"}))["key"] == "hs_crp"
    assert "error" in json.loads(tools[1].invoke({"marker": "unobtainium"}))


def test_get_marker_history_oldest_first_with_status(nocommit, tools):
    seed_panel(nocommit, D2, [("ferritin", 42.0, "ng/mL")])
    seed_panel(nocommit, D1, [("ferritin", 25.0, "ng/mL")])
    out = json.loads(tools[2].invoke({"marker": "ferritin"}))
    assert out["marker"] == "ferritin" and out["unit"] == "ng/mL"
    assert out["functional_range"] == [50.0, 150.0]
    assert [(h["drawn_on"], h["value"], h["functional_status"]) for h in out["history"]] == [
        ("2031-01-15", 25.0, "low"),
        ("2031-04-15", 42.0, "suboptimal_low"),
    ]
    assert json.loads(tools[2].invoke({"marker": "TSH"}))["history"] == []
    assert "error" in json.loads(tools[2].invoke({"marker": "unobtainium"}))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_tools.py -q`
Expected: `ImportError: cannot import name 'make_findings_tools'`.

- [ ] **Step 3: Write the tools**

Append to `packages/tri-wellness/src/tri_wellness/tools/findings.py`:
```python


import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from langchain_core.tools import BaseTool, tool

from tri_core.db.repo import Conn
from tri_wellness import repo
from tri_wellness.labs.evaluate import evaluate, functional_status
from tri_wellness.labs.training_context import load_training_context
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

ConnectFactory = Callable[[], AbstractContextManager[Conn]]

_FINDING_EXCLUDE = {"athlete_note"}


def _dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _resolve(registry: MarkerRegistry, marker: str) -> MarkerSpec | None:
    if marker in registry.markers:
        return registry.get(marker)
    return registry.lookup(marker)


def make_findings_tools(connect: ConnectFactory, registry: MarkerRegistry) -> list[BaseTool]:
    @tool("get_panel_findings")
    def get_panel_findings(panel: str = "latest") -> str:
        """Evaluate one stored lab panel against the functional ranges and return JSON.

        `panel` is a panel id or "latest". The answer has: panel (id, drawn_on, lab_name,
        context: fasting, draw_time, supplements, symptoms, notes), training (CTL, ATL, TSB,
        sessions and sleep/HRV around the draw), ranges_version, and findings: one per marker
        with value, unit, conventional_status, functional_status, functional_range, previous
        (date, value), delta_pct and active_confounders. Call this before answering anything
        about a panel's results; do not read lab_results directly for interpretation.
        """
        with connect() as conn:
            if panel == "latest":
                pid = repo.latest_panel_id(conn)
                if pid is None:
                    return _dump({"error": "no panels stored"})
            else:
                try:
                    pid = int(panel)
                except ValueError:
                    return _dump({"error": f"panel must be an id or 'latest', got {panel!r}"})
            stored = repo.get_panel(conn, pid)
            if stored is None:
                return _dump({"error": f"no panel {pid}"})
            results = repo.lab_results_for_panel(conn, pid)
            previous = repo.previous_values(conn, pid)
            training = load_training_context(conn, stored.drawn_on)
        findings = evaluate(results, registry, previous, stored.context, training)
        return _dump(
            {
                "panel": {
                    "id": stored.id,
                    "drawn_on": stored.drawn_on.isoformat(),
                    "lab_name": stored.lab_name,
                    "context": stored.context.model_dump(mode="json"),
                },
                "training": training.model_dump(mode="json"),
                "ranges_version": registry.version,
                "findings": [
                    f.model_dump(mode="json", exclude=_FINDING_EXCLUDE) for f in findings
                ],
            }
        )

    @tool("get_marker_spec")
    def get_marker_spec(marker: str) -> str:
        """The curated range-table entry for one marker, by canonical key or any printed alias
        (for example "ferritin" or "Ferritin, Serum"): display, system, unit, conventional and
        functional ranges resolved for this athlete's sex, direction, athlete_note, confounders
        and sources. JSON. Use it to explain why a marker is flagged and what the note says.
        """
        spec = _resolve(registry, marker)
        if spec is None:
            return _dump({"error": f"unknown marker {marker!r}"})
        return _dump({"sex": registry.sex, **spec.model_dump(mode="json")})

    @tool("get_marker_history")
    def get_marker_history(marker: str) -> str:
        """Every stored value of one marker (key or alias), oldest first: panel_id, drawn_on,
        value, functional_status, with the marker's unit and functional_range. JSON. Use it for
        trend questions instead of writing SQL.
        """
        spec = _resolve(registry, marker)
        if spec is None:
            return _dump({"error": f"unknown marker {marker!r}"})
        with connect() as conn:
            rows = repo.marker_history(conn, spec.key)
        return _dump(
            {
                "marker": spec.key,
                "unit": spec.unit,
                "functional_range": [spec.functional.low, spec.functional.high],
                "history": [
                    {
                        "panel_id": pid,
                        "drawn_on": drawn.isoformat(),
                        "value": value,
                        "functional_status": functional_status(value, spec),
                    }
                    for pid, drawn, value, _unit in rows
                ],
            }
        )

    return [get_panel_findings, get_marker_spec, get_marker_history]
```
(Move the imports up to the module import block.)

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_tools.py -q`
Expected: 5 passed. `cortisol_am` declares `high_acute_load` among its confounders and the seeded ATL 80 vs CTL 60 fires it. `Finding.previous` serialises as a two-element list.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): get_panel_findings, get_marker_spec, get_marker_history tools"
```

---

### Task 4: Chat (`prompts/chat.py`, `agent.py`, chat REPL, `tri-wellness chat`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/prompts/chat.py`, `packages/tri-wellness/src/tri_wellness/agent.py`
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py` (append `TurnPrinter`, `run_chat_turn`, `chat_loop`), `packages/tri-wellness/src/tri_wellness/cli.py` (append `chat`), `packages/tri-wellness/tests/test_cli.py`
- Test: `packages/tri-wellness/tests/test_chat.py`

**Interfaces:**
- Consumes: Task 1 `WELLNESS_SCHEMA_DOC`, `make_query_tool(url, extra_doc)`, `render_panels`; Task 2 `extract_section`, `athlete_profile`, `profile_block`, `REPORT_RULES`; Task 3 `make_findings_tools`; Plan 2 `make_model`, `Out`, `Read`.
- Produces: `render_chat_prompt(profile, sex, panels: list[PanelSummary], latest_report: StoredReport | None, today: date, tool_names: list[str]) -> str`; `build_agent(model, tools, system_prompt, checkpointer=None)`; `TurnPrinter`; `run_chat_turn(agent, text, thread_id, out) -> str`; `chat_loop(agent, *, read, out, thread_id="wellness", commands: dict[str, Callable[[str], Awaitable[str]]])`; `tri-wellness chat`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_chat.py`:
```python
import contextlib
from datetime import date, datetime

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.agent import build_agent
from tri_wellness.labs.models import PanelSummary, StoredReport
from tri_wellness.prompts.chat import render_chat_prompt
from tri_wellness.prompts.report import REPORT_RULES
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.repl import chat_loop, run_chat_turn
from tri_wellness.tools.findings import make_findings_tools


def summaries():
    return [
        PanelSummary(id=2, drawn_on=date(2026, 8, 20), lab_name="Quest", result_count=40, unmapped_count=1, has_report=True),
        PanelSummary(id=1, drawn_on=date(2026, 3, 1), lab_name="Quest", result_count=38, unmapped_count=0, has_report=True),
    ]


def report():
    return StoredReport(
        id=5,
        panel_id=2,
        ranges_version="2026-09-11.1",
        findings=[],
        report_md="disclaimer\n\n## Priorities\n1. Iron.\n\n## Retest plan\nFerritin in 8 weeks.\n\n## Levers\nx",
        created_at=datetime(2026, 8, 21, 9, 0),
    )


def test_render_chat_prompt_contents():
    text = render_chat_prompt(
        {"ftp_watts": 260, "weight_kg": 74.5},
        "male",
        summaries(),
        report(),
        date(2026, 9, 11),
        ["query_training_db", "get_panel_findings", "get_marker_spec", "get_marker_history"],
    )
    assert "Today is 2026-09-11" in text and "Athlete: male" in text and "260 W" in text
    assert "panel 2: 2026-08-20 Quest, 40 results, report yes" in text
    assert "panel 1: 2026-03-01" in text
    assert "Latest report (panel 2, 2026-08-21)" in text
    assert "1. Iron." in text and "Ferritin in 8 weeks." in text and "## Levers" not in text
    assert "get_panel_findings" in text and "get_marker_history" in text
    assert REPORT_RULES in text
    bare = render_chat_prompt(None, "female", [], None, date(2026, 9, 11), ["query_training_db"])
    assert "no panels stored" in bare and "no report yet" in bare and "thresholds: not available" in bare


def no_db():
    def boom():
        raise AssertionError("this tool must not touch the database")

    return boom


async def test_agent_answers_with_a_findings_tool():
    reg = load_registry("male", MARKERS_PATH)
    tools = make_findings_tools(no_db(), reg)
    model = ScriptedChatModel(
        script=[
            tool_call("get_marker_spec", {"marker": "ferritin"}),
            AIMessage(content="Ferritin's functional range is 50-150 ng/mL."),
        ]
    )
    agent = build_agent(model, tools, "sys")
    out = []
    text = await run_chat_turn(agent, "what is the ferritin range?", "t1", out.append)
    assert text == "Ferritin's functional range is 50-150 ng/mL."
    printed = "".join(out)
    assert "→ get_marker_spec" in printed and "← get_marker_spec" in printed
    msgs = agent.get_state({"configurable": {"thread_id": "t1"}}).values["messages"]
    assert [type(m).__name__ for m in msgs] == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert isinstance(msgs[2], ToolMessage) and '"key": "ferritin"' in msgs[2].content


async def test_chat_loop_dispatches_commands_with_arguments():
    model = ScriptedChatModel(script=[AIMessage(content="hi")])
    agent = build_agent(model, [], "sys")
    lines = iter(["/panels", "/report 2", "/nope", "hello", "/quit"])

    async def read():
        return next(lines, None)

    seen = []

    async def panels(arg: str) -> str:
        seen.append(("panels", arg))
        return "PANELS"

    async def show(arg: str) -> str:
        seen.append(("report", arg))
        return f"REPORT {arg}"

    out = []
    await chat_loop(agent, read=read, out=out.append, thread_id="t2", commands={"panels": panels, "report": show})
    text = "".join(out)
    assert seen == [("panels", ""), ("report", "2")]
    assert "PANELS" in text and "REPORT 2" in text and "unknown command: /nope" in text and "hi" in text
    assert model.calls == 1
    msgs = agent.get_state({"configurable": {"thread_id": "t2"}}).values["messages"]
    assert isinstance(msgs[0], HumanMessage) and msgs[0].content == "hello"
```

Append to `packages/tri-wellness/tests/test_cli.py`:
```python


def test_help_lists_report_and_chat():
    result = runner.invoke(app, ["--help"])
    assert "report" in result.output and "chat" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_chat.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.agent'`.

- [ ] **Step 3: Write the prompt, the agent and the REPL additions**

`packages/tri-wellness/src/tri_wellness/prompts/chat.py`:
```python
"""Chat system prompt, rendered once per session: profile, panels, the latest report's
priorities and retest plan, the tools, and the same rules the report follows."""

from __future__ import annotations

from datetime import date
from typing import Any

from tri_wellness.labs.models import PanelSummary, StoredReport
from tri_wellness.prompts.report import REPORT_RULES, profile_block
from tri_wellness.report import extract_section

TOOL_GUIDE = """\
Tools, in the order to reach for them:
- get_panel_findings(panel): the evaluated findings for a panel ("latest" or an id). Always
  call it before discussing a panel's results; it carries each marker's status, functional
  range, previous value and confounders.
- get_marker_spec(marker): the range-table entry, athlete note and sources for one marker.
- get_marker_history(marker): every stored value with its functional status, oldest first.
- query_training_db(sql): read-only SQL over workouts, daily_metrics, athlete_profile and the
  lab tables, for load, sleep and HRV around a draw or anything the tools above do not cover."""


def _panels_block(panels: list[PanelSummary]) -> str:
    if not panels:
        return "Panels: no panels stored yet (run `tri-wellness ingest <file>`)."
    lines = ["Panels, newest first:"]
    for p in panels:
        lines.append(
            f"- panel {p.id}: {p.drawn_on.isoformat()} {p.lab_name or '-'}, "
            f"{p.result_count} results, report {'yes' if p.has_report else 'no'}"
        )
    return "\n".join(lines)


def _report_block(report: StoredReport | None) -> str:
    if report is None:
        return "Latest report: no report yet (run `tri-wellness report`)."
    head = f"Latest report (panel {report.panel_id}, {report.created_at.date().isoformat()}):"
    parts = [head]
    for title in ("Priorities", "Retest plan"):
        body = extract_section(report.report_md, title)
        if body:
            parts.append(f"{title}:\n{body}")
    return "\n\n".join(parts)


def render_chat_prompt(
    profile: dict[str, Any] | None,
    sex: str,
    panels: list[PanelSummary],
    latest_report: StoredReport | None,
    today: date,
    tool_names: list[str],
) -> str:
    return "\n\n".join(
        [
            "You are a functional-medicine practitioner who works with one endurance athlete. "
            "You answer questions about the athlete's lab panels using the tools below. Python "
            "has already evaluated every marker against a curated range table; you explain "
            "patterns and answer follow-ups, you do not re-judge numbers from memory.",
            f"Today is {today.isoformat()}.",
            profile_block(profile, sex),
            _panels_block(panels),
            _report_block(latest_report),
            "Tools bound this session: " + ", ".join(tool_names) + ".",
            TOOL_GUIDE,
            REPORT_RULES,
        ]
    )
```

`packages/tri-wellness/src/tri_wellness/agent.py`:
```python
"""The chat agent: a tool-calling loop with in-process conversation memory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> Any:
    """model <-> tools until the model stops calling tools. The stable prefix (system prompt
    and tool schemas) is served from Anthropic's prompt cache."""
    return create_agent(
        model,
        list(tools),
        system_prompt=system_prompt,
        middleware=[AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")],
        checkpointer=checkpointer or InMemorySaver(),
    )
```

Append to `packages/tri-wellness/src/tri_wellness/repl.py`:
```python


ChatCommand = Callable[[str], Awaitable[str]]


class TurnPrinter:
    """Renders agent stream events: text streams inline, tool activity gets its own lines."""

    def __init__(self, out: Out) -> None:
        self.out = out
        self.final_text = ""

    def on_event(self, mode: str, data: Any) -> None:
        if mode == "messages":
            chunk, meta = data
            if (
                isinstance(chunk, AIMessageChunk | AIMessage)
                and meta.get("langgraph_node") == "model"
            ):
                text = text_of(chunk)
                if text:
                    self.out(text)
                    self.final_text += text
            return
        if mode == "updates" and isinstance(data, dict):
            for node, payload in data.items():
                for msg in (payload or {}).get("messages", []):
                    if node == "model" and isinstance(msg, AIMessage):
                        for tc in msg.tool_calls:
                            self.out(f"\n→ {tc['name']}({tc['args']})\n")
                        if not msg.tool_calls:
                            self.final_text = text_of(msg) or self.final_text
                            self.out("\n")
                    elif node == "tools" and isinstance(msg, ToolMessage):
                        self.out(f"← {msg.name}: {len(text_of(msg))} chars\n")


async def run_chat_turn(agent: Any, text: str, thread_id: str, out: Out) -> str:
    printer = TurnPrinter(out)
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        async for mode, data in agent.astream(
            {"messages": [HumanMessage(text)]}, config=cfg, stream_mode=["messages", "updates"]
        ):
            printer.on_event(mode, data)
    except anthropic.RateLimitError as exc:
        out(f"\n[rate limited: {exc}. Wait a moment and try again.]\n")
    except anthropic.APIStatusError as exc:
        out(f"\n[Anthropic API error {exc.status_code}: {exc.message}]\n")
    except anthropic.APIConnectionError as exc:
        out(f"\n[connection error talking to Anthropic: {exc}]\n")
    return printer.final_text


async def chat_loop(
    agent: Any,
    *,
    read: Read,
    out: Out,
    thread_id: str = "wellness",
    commands: dict[str, ChatCommand] | None = None,
) -> None:
    commands = dict(commands or {})
    names = ", ".join(sorted(["quit", *commands]))
    out(f"tri-wellness chat. Ask about your labs, /quit to exit, /<command> for: {names}\n")
    while True:
        line = await read()
        if line is None:
            out("\n")
            return
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            name, _, arg = line[1:].partition(" ")
            if name == "quit":
                return
            handler = commands.get(name)
            if handler is None:
                out(f"unknown command: /{name}\n")
                continue
            out(await handler(arg.strip()) + "\n")
            continue
        await run_chat_turn(agent, line, thread_id, out)
```
with `AIMessage`, `AIMessageChunk`, `HumanMessage`, `ToolMessage` added to the `langchain_core.messages` import in `repl.py`.

Append to `packages/tri-wellness/src/tri_wellness/cli.py`:
```python


@app.command()
def chat() -> None:
    """Ask questions about stored panels and reports."""
    asyncio.run(_chat())


async def _chat() -> None:
    from datetime import date

    from langchain_core.tools import BaseTool

    from tri_core.db.connection import connect
    from tri_core.db.sql_tool import make_query_tool
    from tri_wellness import repo
    from tri_wellness.agent import build_agent
    from tri_wellness.graph.llm import make_model
    from tri_wellness.prompts.chat import render_chat_prompt
    from tri_wellness.ranges.registry import load_registry
    from tri_wellness.repl import chat_loop, render_panels
    from tri_wellness.report import athlete_profile
    from tri_wellness.tools.findings import WELLNESS_SCHEMA_DOC, make_findings_tools

    settings = _settings_or_exit()
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        raise typer.Exit(code=2)
    url = settings.database_url
    registry = load_registry(settings.tri_athlete_sex)
    tools: list[BaseTool] = [
        make_query_tool(url, WELLNESS_SCHEMA_DOC),
        *make_findings_tools(lambda: connect(url), registry),
    ]
    with connect(url) as conn:
        profile = athlete_profile(conn)
        panels = repo.list_panels(conn)
        latest = repo.latest_panel_id(conn)
        latest_report = repo.latest_report_for_panel(conn, latest) if latest else None
    prompt = render_chat_prompt(
        profile, registry.sex, panels, latest_report, date.today(), [t.name for t in tools]
    )
    agent = build_agent(make_model(settings), tools, prompt)

    async def read() -> str | None:
        try:
            return await asyncio.to_thread(console.input, "[bold cyan]you>[/] ")
        except EOFError:
            return None

    async def cmd_panels(_: str) -> str:
        with connect(url) as conn:
            return render_panels(repo.list_panels(conn))

    async def cmd_report(arg: str) -> str:
        with connect(url) as conn:
            if arg:
                try:
                    pid: int | None = int(arg)
                except ValueError:
                    return "usage: /report [panel id]"
            else:
                pid = repo.latest_panel_id(conn)
            if pid is None:
                return "no panels stored"
            saved = repo.latest_report_for_panel(conn, pid)
        if saved is None:
            return f"no report for panel {pid}; run `tri-wellness report --panel {pid}`"
        return f"report {saved.id} for panel {pid} ({saved.created_at.date()}):\n\n{saved.report_md}"

    async def cmd_prompt(_: str) -> str:
        return prompt

    async def cmd_tools(_: str) -> str:
        return "\n".join(f"- {t.name}: {t.description.splitlines()[0]}" for t in tools)

    await chat_loop(
        agent,
        read=read,
        out=_out,
        commands={
            "panels": cmd_panels,
            "report": cmd_report,
            "prompt": cmd_prompt,
            "tools": cmd_tools,
        },
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass. Then `uv run tri-wellness chat`, `/prompt`, `/tools`, "What did my last panel say about iron?" and watch for `→ get_panel_findings({'panel': 'latest'})` before the answer.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): chat agent with findings tools, prompt and REPL commands"
```

---

### Task 5: LangSmith dataset and code evaluators (`evals/`, `tri-wellness eval`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/evals/__init__.py`, `evals/cases.py`, `evals/target.py`, `evals/evaluators.py`, `evals/run.py`
- Modify: `packages/tri-wellness/src/tri_wellness/cli.py` (append `eval`)
- Test: `packages/tri-wellness/tests/test_evals.py`

**Interfaces:**
- Consumes: Task 2 `ReportWriter`, `render_report_prompt`, `SECTION_TITLES`, `CHANGES_TITLE`, `DISCLAIMER`, `PROMPT_VERSION`; Plan 1 `evaluate`, `load_registry`.
- Produces: `EvalCase(name, results, context, training, previous, profile)` with `.inputs()`; `CASES: list[EvalCase]`; `parse_inputs(inputs) -> (results, context, training, previous, profile)`; `run_case(writer, registry, inputs) -> {"report_md", "findings"}`; `make_target(model, registry)`; evaluators `cites_functional_ranges`, `has_required_sections`, `names_active_confounders` (each `(inputs, outputs) -> {"key", "score", "comment"}`); `DATASET_NAME = "tri_wellness_reports"`, `case_examples()`, `ensure_dataset()`, `pass_rates()`, `render_pass_rates()`, `run_eval(settings, model, *, prefix, recreate, log) -> dict[str, float]`; `tri-wellness eval [--prefix] [--recreate-dataset]` (exit 1 when any evaluator is below 100 %).

- [ ] **Step 1: Write the failing test**

`packages/tri-wellness/tests/test_evals.py`:
```python
from langchain_core.messages import AIMessage

from tri_core.testing import ScriptedChatModel
from tri_wellness.evals.cases import CASES
from tri_wellness.evals.evaluators import (
    cites_functional_ranges,
    has_required_sections,
    names_active_confounders,
)
from tri_wellness.evals.run import DATASET_NAME, case_examples, pass_rates, render_pass_rates
from tri_wellness.evals.target import make_target, parse_inputs
from tri_wellness.labs.evaluate import evaluate
from tri_wellness.prompts.report import DISCLAIMER
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.testing import REPORT_OK


def case(name):
    return next(c for c in CASES if c.name == name)


def test_cases_are_valid_and_cover_the_rules():
    reg = load_registry("male", MARKERS_PATH)
    assert len({c.name for c in CASES}) == len(CASES) >= 4
    flagged_total = 0
    for c in CASES:
        results, context, training, previous, _ = parse_inputs(c.inputs())
        findings = evaluate(results, reg, previous, context, training)
        assert len(findings) == len(results), c.name
        flagged_total += sum(f.functional_status != "optimal" for f in findings)
    assert flagged_total >= 6
    assert any(not parse_inputs(c.inputs())[3] for c in CASES)  # a first-panel case
    assert any(parse_inputs(c.inputs())[3] for c in CASES)  # a case with a previous panel
    assert all(f.functional_status == "optimal" for f in evaluate(*_parts(case("all_optimal"), reg)))
    examples = case_examples()
    assert len(examples) == len(CASES) and examples[0]["metadata"]["case"] == CASES[0].name
    assert DATASET_NAME == "tri_wellness_reports"


def _parts(c, reg):
    results, context, training, previous, _ = parse_inputs(c.inputs())
    return results, reg, previous, context, training


async def test_target_writes_and_code_evaluators_pass_on_a_good_report():
    reg = load_registry("male", MARKERS_PATH)
    c = case("iron_after_long_ride")
    model = ScriptedChatModel(script=[AIMessage(content=REPORT_OK)])
    out = await make_target(model, reg)(c.inputs())
    assert out["report_md"] == REPORT_OK and model.calls == 1
    assert {f["marker"] for f in out["findings"]} == {"ferritin", "hs_crp", "hemoglobin", "tsh"}
    assert cites_functional_ranges(c.inputs(), out) == {"key": "cites_functional_ranges", "score": 1, "comment": "ok"}
    assert has_required_sections(c.inputs(), out)["score"] == 1
    assert names_active_confounders(c.inputs(), out)["score"] == 1


def test_evaluators_catch_a_bad_report():
    reg = load_registry("male", MARKERS_PATH)
    c = case("iron_after_long_ride")
    findings = evaluate(*_parts(c, reg))
    bad = "Looks fine.\n\n## Priorities\n1. Eat well.\n"
    out = {"report_md": bad, "findings": [f.model_dump(mode="json") for f in findings]}
    r = cites_functional_ranges(c.inputs(), out)
    assert r["score"] == 0 and "Ferritin" in r["comment"] and "50-150" in r["comment"]
    s = has_required_sections(c.inputs(), out)
    assert s["score"] == 0 and "disclaimer" in s["comment"] and "Draw conditions" in s["comment"]
    assert "Changes since last panel" in s["comment"]
    n = names_active_confounders(c.inputs(), out)
    assert n["score"] == 0 and "recent_hard_session" in n["comment"]


def test_sections_evaluator_requires_changes_only_with_a_previous_panel():
    reg = load_registry("male", MARKERS_PATH)
    first = case("lipids_metabolic_first_panel")
    findings = evaluate(*_parts(first, reg))
    md = REPORT_OK.split("## Changes since last panel")[0]
    out = {"report_md": md, "findings": [f.model_dump(mode="json") for f in findings]}
    assert has_required_sections(first.inputs(), out)["score"] == 1
    with_changes = {"report_md": REPORT_OK, "findings": out["findings"]}
    r = has_required_sections(first.inputs(), with_changes)
    assert r["score"] == 0 and "no previous panel" in r["comment"]
    assert DISCLAIMER.split(";")[0] in REPORT_OK


def test_pass_rates_and_rendering():
    class R:
        def __init__(self, key, score):
            self.key, self.score = key, score

    rows = [
        {"evaluation_results": {"results": [R("cites_functional_ranges", 1), R("has_required_sections", 0)]}},
        {"evaluation_results": {"results": [R("cites_functional_ranges", 1), R("has_required_sections", 1)]}},
    ]
    rates = pass_rates(rows)
    assert rates == {"cites_functional_ranges": 1.0, "has_required_sections": 0.5}
    text = render_pass_rates(rates, 2)
    assert "2 examples" in text and "has_required_sections" in text and "50%" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-wellness/tests/test_evals.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.evals'`.

- [ ] **Step 3: Write the cases and the target**

`packages/tri-wellness/src/tri_wellness/evals/__init__.py`: empty.

`packages/tri-wellness/src/tri_wellness/evals/cases.py`:
```python
"""The findings sets behind the LangSmith dataset, stored as LabResult inputs so they stay valid
when markers.yaml changes: the target evaluates them with the current registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DRAWN = "2026-08-20"
PROFILE: dict[str, Any] = {"ftp_watts": 260, "weight_kg": 74.5, "lthr_bpm": 165}
FASTED_AM: dict[str, Any] = {"fasting": True, "draw_time": "07:30:00", "supplements": [], "symptoms": []}


def result(marker: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "marker": marker,
        "value": value,
        "unit": unit,
        "raw": {"name": marker, "value": str(value), "unit": unit},
    }


def training(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "drawn_on": DRAWN,
        "ctl": 60.0,
        "atl": 62.0,
        "tsb": -2.0,
        "tss_7d": 380.0,
        "last_sessions": [],
        "sleep_2n_avg_sec": 27000,
        "sleep_30d_avg_sec": 27000,
        "hrv_2n_avg": 60,
        "hrv_30d_avg": 60,
    }
    base.update(over)
    return base


LONG_RIDE = {"date": "2026-08-19", "sport": "bike", "duration_min": 180, "tss": 210, "title": "long ride"}


@dataclass(frozen=True)
class EvalCase:
    name: str
    results: list[dict[str, Any]]
    context: dict[str, Any]
    training: dict[str, Any]
    previous: dict[str, list[Any]] = field(default_factory=dict)  # marker -> [date, value]
    profile: dict[str, Any] | None = None

    def inputs(self) -> dict[str, Any]:
        return {
            "results": self.results,
            "context": self.context,
            "training": self.training,
            "previous": self.previous,
            "profile": self.profile,
        }


CASES: list[EvalCase] = [
    EvalCase(
        name="iron_after_long_ride",
        results=[
            result("ferritin", 42.0, "ng/mL"),
            result("hs_crp", 1.8, "mg/L"),
            result("hemoglobin", 15.1, "g/dL"),
            result("tsh", 1.5, "mIU/L"),
        ],
        context=FASTED_AM,
        training=training(last_sessions=[LONG_RIDE]),
        previous={"ferritin": ["2026-03-01", 35.0]},
        profile=PROFILE,
    ),
    EvalCase(
        name="overreaching_hormones",
        results=[
            result("testosterone_total", 480.0, "ng/dL"),
            result("cortisol_am", 19.0, "ug/dL"),
            result("free_t3", 2.8, "pg/mL"),
            result("reverse_t3", 19.0, "ng/dL"),
            result("tsh", 2.4, "mIU/L"),
            result("ferritin", 80.0, "ng/mL"),
        ],
        context={**FASTED_AM, "symptoms": ["flat legs", "poor sleep"]},
        training=training(ctl=70.0, atl=92.0, tsb=-22.0, tss_7d=640.0, sleep_2n_avg_sec=21000, hrv_2n_avg=48),
        previous={"testosterone_total": ["2026-03-01", 610.0], "free_t3": ["2026-03-01", 3.4]},
        profile=PROFILE,
    ),
    EvalCase(
        name="all_optimal",
        results=[
            result("ferritin", 90.0, "ng/mL"),
            result("hs_crp", 0.4, "mg/L"),
            result("vitamin_d", 62.0, "ng/mL"),
            result("hba1c", 5.1, "%"),
        ],
        context=FASTED_AM,
        training=training(),
        previous={"ferritin": ["2026-03-01", 70.0]},
        profile=PROFILE,
    ),
    EvalCase(
        name="lipids_metabolic_first_panel",
        results=[
            result("ldl", 128.0, "mg/dL"),
            result("apob", 96.0, "mg/dL"),
            result("triglycerides", 140.0, "mg/dL"),
            result("insulin", 7.5, "uIU/mL"),
            result("glucose", 94.0, "mg/dL"),
            result("hdl", 58.0, "mg/dL"),
        ],
        context={"fasting": False, "draw_time": "13:15:00", "supplements": [], "symptoms": []},
        training=training(),
        profile=None,
    ),
]
```

`packages/tri-wellness/src/tri_wellness/evals/target.py`:
```python
"""The function under evaluation: evaluate the case's results with the current registry, render
the prompt, write the report. No database."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from langchain_core.language_models import BaseChatModel

from tri_wellness.labs.evaluate import evaluate
from tri_wellness.labs.models import LabResult, PanelContext, TrainingContext
from tri_wellness.prompts.report import render_report_prompt
from tri_wellness.ranges.registry import MarkerRegistry
from tri_wellness.report import ReportWriter


def parse_inputs(
    inputs: dict[str, Any],
) -> tuple[
    list[LabResult], PanelContext, TrainingContext, dict[str, tuple[date, float]], dict[str, Any] | None
]:
    previous = {
        m: (date.fromisoformat(str(d)), float(v)) for m, (d, v) in (inputs.get("previous") or {}).items()
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
    return {"report_md": text, "findings": [f.model_dump(mode="json") for f in findings]}


def make_target(
    model: BaseChatModel, registry: MarkerRegistry
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    writer = ReportWriter(model)

    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return await run_case(writer, registry, inputs)

    return target
```

- [ ] **Step 4: Write the evaluators and the runner**

`packages/tri-wellness/src/tri_wellness/evals/evaluators.py`:
```python
"""Code evaluators over a report: every non-optimal marker cites its functional range, the fixed
structure is present, and active confounders are named. No model."""

from __future__ import annotations

import re
from typing import Any

from tri_wellness.labs.models import Finding
from tri_wellness.prompts.report import CHANGES_TITLE, DISCLAIMER, SECTION_TITLES


def _result(key: str, ok: bool, problems: list[str]) -> dict[str, Any]:
    return {"key": key, "score": int(ok), "comment": "; ".join(problems) or "ok"}


def _findings(outputs: dict[str, Any]) -> list[Finding]:
    return [Finding.model_validate(f) for f in outputs.get("findings", [])]


def _g(v: float) -> str:
    return f"{v:g}"


def _range_text(f: Finding) -> str:
    low, high = f.functional_range
    return f"{'' if low is None else _g(low)}-{'' if high is None else _g(high)}"


def _mentions_bound(report: str, v: float) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(_g(v))}(?![\d.])", report) is not None


def cites_functional_ranges(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "")
    problems: list[str] = []
    for f in _findings(outputs):
        if f.functional_status == "optimal":
            continue
        low, high = f.functional_range
        named = f.display.lower() in report.lower() or f.marker in report
        bounds_ok = all(_mentions_bound(report, v) for v in (low, high) if v is not None)
        if not (named and bounds_ok):
            problems.append(f"{f.display}: functional range {_range_text(f)} not cited")
    return _result("cites_functional_ranges", not problems, problems)


def has_required_sections(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "")
    problems: list[str] = []
    first = next((ln.strip() for ln in report.splitlines() if ln.strip()), "")
    if first != DISCLAIMER:
        problems.append("first line is not the disclaimer")
    headings = [m.group(1).strip() for m in re.finditer(r"^##[ \t]+(.+?)[ \t]*$", report, re.M)]
    positions = {h.lower(): i for i, h in enumerate(headings)}
    last = -1
    for title in SECTION_TITLES:
        i = positions.get(title.lower())
        if i is None:
            problems.append(f"missing section '{title}'")
        elif i < last:
            problems.append(f"section '{title}' out of order")
        else:
            last = i
    has_previous = bool(inputs.get("previous"))
    has_changes = CHANGES_TITLE.lower() in positions
    if has_previous and not has_changes:
        problems.append(f"missing section '{CHANGES_TITLE}'")
    if has_changes and not has_previous:
        problems.append(f"'{CHANGES_TITLE}' present but there is no previous panel")
    return _result("has_required_sections", not problems, problems)


def names_active_confounders(inputs: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    report = str(outputs.get("report_md") or "").lower()
    problems: list[str] = []
    seen: set[str] = set()
    for f in _findings(outputs):
        if f.functional_status == "optimal":
            continue
        for c in f.active_confounders:
            if c in seen:
                continue
            seen.add(c)
            if c not in report and c.replace("_", " ") not in report:
                problems.append(f"{c} applies to {f.display} but is not named")
    return _result("names_active_confounders", not problems, problems)
```

`packages/tri-wellness/src/tri_wellness/evals/run.py`:
```python
"""Create the LangSmith dataset from the cases and run an experiment over it. Needs
LANGSMITH_API_KEY; the experiment is named by PROMPT_VERSION."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langsmith import Client, aevaluate

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


async def run_eval(
    settings: WellnessSettings,
    model: BaseChatModel,
    *,
    prefix: str | None = None,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> dict[str, float]:
    client = Client(api_key=settings.langsmith_api_key)
    ensure_dataset(client, recreate=recreate)
    registry = load_registry(settings.tri_athlete_sex)
    results = await aevaluate(
        make_target(model, registry),
        data=DATASET_NAME,
        evaluators=[cites_functional_ranges, has_required_sections, names_active_confounders],
        experiment_prefix=prefix or f"report-v{PROMPT_VERSION}",
        metadata={
            "prompt_version": PROMPT_VERSION,
            "ranges_version": registry.version,
            "model": settings.tri_model,
        },
        client=client,
        max_concurrency=2,
    )
    rows: list[Any] = [row async for row in results]
    rates = pass_rates([dict(r) for r in rows])
    log(f"experiment: {results.experiment_name}")
    log(render_pass_rates(rates, len(rows)))
    return rates
```

Append to `packages/tri-wellness/src/tri_wellness/cli.py`:
```python


@app.command("eval")
def eval_cmd(
    prefix: str | None = typer.Option(
        None, "--prefix", help="Experiment name prefix (default report-v<PROMPT_VERSION>)"
    ),
    recreate: bool = typer.Option(
        False, "--recreate-dataset", help="Delete and re-create the LangSmith dataset"
    ),
) -> None:
    """Run the report prompt over the LangSmith dataset and print the pass rate per evaluator
    (exit 1 when any evaluator is below 100%)."""
    raise typer.Exit(code=asyncio.run(_eval(prefix=prefix, recreate=recreate)))


async def _eval(*, prefix: str | None, recreate: bool) -> int:
    from tri_wellness.evals.run import run_eval
    from tri_wellness.graph.llm import make_model

    settings = _settings_or_exit()
    if not settings.langsmith_api_key:
        console.print("LANGSMITH_API_KEY is not set in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    rates = await run_eval(
        settings, make_model(settings), prefix=prefix, recreate=recreate, log=lambda m: _out(m + "\n")
    )
    return 0 if rates and all(r == 1.0 for r in rates.values()) else 1
```

- [ ] **Step 5: Run the tests, then the experiment (Brian)**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass. For `test_evaluators_catch_a_bad_report`: the iron case's ferritin finding carries `recent_hard_session` (long ride, 210 TSS) and `inflammation` (hs-CRP 1.8 above 1.0); the bad report names neither.

Then, with `LANGSMITH_API_KEY` set:
```bash
uv run tri-wellness eval
```
Record the experiment name and the three pass rates in the README (Task 6). A `cites_functional_ranges` miss usually means the model wrote the range in a different unit or rounded a bound; fix the prompt rule, bump `PROMPT_VERSION`, rerun.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): LangSmith report dataset, code evaluators, eval command"
```

---

### Task 6: README, root README, docs sync

**Files:**
- Modify: `packages/tri-wellness/README.md`, `README.md`

- [ ] **Step 1: Package README**

Replace the `## After Plan 2` heading with `## After Plan 3 (v1 complete)` and append:
```markdown
- `tri-wellness report [--panel ID] [--out path.md]`: evaluates the panel (findings, previous
  values, training context around the draw), renders one prompt and streams one model call.
  Fixed structure: disclaimer, Draw conditions, By system, Priorities, Training implications,
  Levers, Supplements, Retest plan, Questions for your practitioner, and Changes since last
  panel when there is one. Saved to `lab_reports` with the findings and the ranges version;
  re-running makes a new row.
- `tri-wellness chat`: `create_agent` over `query_training_db` (schema extended with the lab
  tables), `get_panel_findings`, `get_marker_spec` and `get_marker_history`. The system prompt
  carries the athlete profile, the panel list, the latest report's priorities and retest plan,
  and the report rules. `/panels`, `/report [ID]`, `/prompt`, `/tools`, `/quit`.
- `tri-wellness panels`: one line per stored panel.
- `tri-wellness eval`: runs the report prompt over the LangSmith dataset
  `tri_wellness_reports` (four findings sets in `evals/cases.py`) with three code evaluators:
  every non-optimal marker cites its functional range, the ten-section structure is present,
  active confounders are named. Latest run: _experiment name and pass rates_.

Prompt versions: `prompts/report.py` `PROMPT_VERSION` names the experiment; bump it whenever
`REPORT_SYSTEM` or `REPORT_RULES` changes.
```
Replace the italic placeholder with the numbers from Task 5 step 5, or "not run yet".

- [ ] **Step 2: Root README**

In the Run block add:
```
uv run tri-wellness report [--panel ID] [--out path.md]   # interpret a stored panel; saved to lab_reports
uv run tri-wellness chat                                   # ask about panels and reports
uv run tri-wellness panels                                 # list stored panels
uv run tri-wellness eval [--recreate-dataset]              # LangSmith report evaluators
```
In the Layout block change the tri-wellness line to `packages/tri-wellness/  src/tri_wellness/{config,cli,repo,repl,report,agent,testing,ranges,labs,graph,prompts,tools,evals}`.

Under Status add: `- tri-wellness milestone 3 (2026-09): report, chat and panels commands; LangSmith report evaluators (pass rates in the package README).` and in the package table change the command column to `tri-wellness ingest \| report \| chat \| panels \| eval`.

- [ ] **Step 3: Copy docs to the vault and commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/packages/tri-wellness $V/docs/superpowers/plans
cp packages/tri-wellness/README.md $V/packages/tri-wellness/readme.md
cp README.md $V/readme.md
cp docs/superpowers/plans/2026-09-11-tri-wellness-03-report-and-chat.md $V/docs/superpowers/plans/
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "docs(wellness): plan 3 READMEs and evaluator pass rates"
```

---

## Layout after this plan

```
packages/tri-wellness/src/tri_wellness/
  cli.py          ingest, report, chat, panels, eval
  report.py       extract_section, athlete_profile, ReportWriter, run_report
  agent.py        build_agent
  repl.py         review REPL (Plan 2) + text_of, render_panels, TurnPrinter, run_chat_turn, chat_loop
  prompts/{extract,report,chat}.py
  tools/findings.py
  evals/{cases,target,evaluators,run}.py
packages/tri-core/src/tri_core/db/sql_tool.py   make_query_tool(url, extra_doc="")
```

What milestone 4 (a separate spec) builds on: `repo.marker_history` and `lab_reports.findings` for trends; `Finding`'s JSON shape for planning-intake constraints; `ReportWriter` for a per-system fan-out.

## Self-review notes

- Spec §10: input set (findings, panel context, training context, previous priorities, athlete profile) in `run_report`; every value the model sees carries status and range (`findings_block`, including the optimal lines); the ten sections and the four rules in `REPORT_SYSTEM`/`REPORT_RULES`; saved with findings and `ranges_version`; `--out`.
- Spec §11: `create_agent`, the four tools in order (`_chat` builds the list in that order and `test_tool_names_and_order` pins the findings three), the SQL tool's schema doc extended (`WELLNESS_SCHEMA_DOC`), system prompt built once per session with profile, latest priorities and retest plan, the report rules and today's date, in-process memory (`InMemorySaver`), the five REPL commands.
- Spec §12: `report`, `chat`, `panels` signatures; `eval` is the milestone-3 evaluator entry point.
- Spec §13: API errors caught and printed in `run_report` and `run_chat_turn`; none of the three commands opens the checkpointer.
- Spec §15: report prompt builder tests; DB tests for `run_report`, the tools and `latest_report_before`; agent loop with `ScriptedChatModel`; evaluators against a good and a bad report.
- Spec §16: report tags; the LangSmith dataset of findings sets and a code evaluator for functional-range citations (plus two more).
- Spec §19 item 3 answered: `extra_doc` parameter on `make_query_tool`.
- Type consistency: `ReportWriter.write(prompt, out, tags)` is called the same way in `run_report` and `run_case`; `render_report_prompt(..., has_previous=)` keyword-only in both; `make_findings_tools(connect, registry)` in `_chat` and the tests; `chat_loop` commands take one string argument everywhere; `REPORT_OK` satisfies all three evaluators for the `iron_after_long_ride` case: ferritin 50-150 and the hs-CRP high of 1 are cited next to the marker names, the nine headings are in order with the disclaimer first, and both active confounders appear as "recent hard session" and "inflammation".
