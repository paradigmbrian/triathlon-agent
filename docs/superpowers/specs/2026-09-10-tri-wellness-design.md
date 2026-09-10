# tri-wellness — Functional-Medicine Lab Interpreter (package `tri_wellness`)

**Date:** 2026-09-10
**Status:** Approved design, pending implementation plan
**Purpose:** A LangChain/LangGraph learning project that also produces a useful tool: an agent that ingests the athlete's lab work from PDFs and structured exports, evaluates every marker against curated functional-medicine ranges, and writes an interpretation grounded in the training, sleep and recovery data already synced to Postgres by tri-core. Version 1 is the lab interpreter. Its stored panels are the foundation for a later longitudinal wellness tracker.

Companion specs: `tri-analyze` design (2026-09-06) and `tri-planning` design (2026-09-07). This spec assumes the workspace, tri-core, the Postgres store and the REPL conventions they established.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope of v1 | Lab interpreter: ingest a panel, evaluate, write a report, answer questions about it. | Interpretation has to be right before trends across panels mean anything. The tracker is milestone 4. |
| Lab sources | Mixed: PDF reports from any lab, plus structured exports (CSV/JSON) from services such as Function Health. | Whatever the next panel arrives as. One normalizing step yields a common marker table regardless of source. |
| Where judgment lives | A curated range table in the repo (`markers.yaml`): conventional range, functional optimal range, units, aliases, athlete-specific note, confounders, sources. Drafted from published functional-medicine references, reviewed by Brian. | Inspectable, versioned, testable. The model explains patterns; it does not remember cutoffs. |
| Advice posture | Full functional-medicine style: explanation, lifestyle levers, supplement and dose suggestions, retest plan. Framed for discussion with a practitioner. | Personal tool for one athlete. The framing is a prompt rule, not a legal shield. |
| Interface | Commands plus chat: `ingest` with a review gate, `report` writes a saved interpretation, `chat` for follow-up questions. | Ingestion is a pipeline with a human check, like planning's apply. A report is reread, not scrolled back to. |
| Panel context | A small structured record collected at ingest: fasting, draw time, supplements, diet pattern, symptoms, notes. | Supplements and draw state change how a marker is read; structure lets panels be compared later. |
| Training context | Read automatically from `workouts` and `daily_metrics` around the draw date. | The agent should know that a high CK followed a long ride without being told. |
| Architecture | Hybrid: Python owns normalization, evaluation and the range table; the model owns extraction from messy input and the written interpretation. Ingest is a small LangGraph graph with an interrupt; report is one model call; chat is `create_agent`. | Every deterministic piece is unit-testable without a model. Reuses planning's interrupt pattern and analyze's agent pattern. |
| LLM | `claude-opus-5` via `langchain-anthropic`, same as the other agents. | Native PDF document input, reliable structured output, long reports. |

## 2. Feasibility, verified 2026-09-10

- `langchain-anthropic` 1.7.1 converts a standard `file` content block with base64 data and `mime_type: application/pdf` into an Anthropic `document` block, so PDF extraction needs no PDF library.
- The next migration number is `004`. Existing tables are untouched.
- `langgraph-checkpoint-postgres` and the checkpoint tables already exist from planning; ingest reuses them with its own thread ids.

## 3. System overview

```
  lab PDF / export ──► tri-wellness ingest ─► extract ─► normalize ─► review ─► store ──► Postgres
                        (LangGraph)                        (pure)   interrupt()             lab_panels
                                                                                            lab_results
  Postgres ──────────► tri-wellness report ─► evaluate (pure) ─► one model call ─► lab_reports, stdout
   workouts, daily_metrics, lab_*                  ▲
                                                   │ training context around drawn_on
  Postgres ──────────► tri-wellness chat ───► create_agent: query_training_db, get_panel_findings,
                                                            get_marker_spec, get_marker_history
```

No live MCP tools in v1. Everything the agent needs is in Postgres.

## 4. Package layout

```
packages/tri-wellness/
  pyproject.toml
  README.md
  src/tri_wellness/
    cli.py                  ingest <file>, report [--panel ID] [--out path], chat, panels
    config.py               LANGSMITH_PROJECT default tri_wellness; athlete sex for sex-specific ranges
    repo.py                 lab-table reads and writes
    repl.py                 chat loop; ingest review table and context prompts; YAML edit via $EDITOR
    ranges/
      markers.yaml          the curated range table
      registry.py           loads and validates the YAML into MarkerSpec models; alias index
    labs/
      models.py             RawResult, LabResult, LabPanel, PanelContext, Finding, TrainingContext
      extract/
        __init__.py         sniff(file) -> source kind and parser
        pdf.py              model call with the PDF as a document block, structured output -> list[RawResult]
        exports.py          deterministic parsers keyed by detected format; model fallback
      normalize.py          alias mapping, unit conversion, unmapped list (pure)
      evaluate.py           LabResult + MarkerSpec + previous panel + contexts -> Finding (pure)
      training_context.py   reads workouts and daily_metrics around drawn_on
    graph/
      state.py              IngestState
      graph.py              build_ingest_graph(model, checkpointer)
      nodes/
        extract.py, normalize.py, review.py, store.py
    prompts/
      extract.py            extraction instructions and RawResult schema notes
      report.py             report structure and rules
      chat.py               chat system prompt builder
    tools/
      findings.py           get_panel_findings, get_marker_spec, get_marker_history
  tests/
    fixtures/
      exports/              one small file per supported export format
      extract/              recorded structured-output responses
```

Dependency direction: `tri-wellness` depends on `tri-core` only. Neither analyze nor planning depends on it. The future orchestrator depends on all four.

## 5. Data model, `migrations/004_wellness.sql`

```sql
create table lab_panels (
  id            serial primary key,
  drawn_on      date not null,
  lab_name      text,                  -- Quest, LabCorp, Function Health, ...
  source_file   text,                  -- path as given at ingest
  source_kind   text not null,         -- pdf | export | manual
  context       jsonb not null,        -- PanelContext
  raw_extract   jsonb not null,        -- list[RawResult] exactly as extraction returned them
  created_at    timestamptz not null default now()
);
create index on lab_panels (drawn_on);

create table lab_results (
  panel_id      int not null references lab_panels,
  marker        text not null,         -- canonical key from markers.yaml
  value         numeric not null,      -- canonical unit
  unit          text not null,
  raw_name      text not null,         -- what the lab printed
  raw_value     text not null,         -- verbatim, including "<5"
  raw_unit      text,
  lab_ref_low   numeric,
  lab_ref_high  numeric,
  flag          text,                  -- lab's own H / L, if printed
  primary key (panel_id, marker)
);
create index on lab_results (marker);

create table lab_reports (
  id             serial primary key,
  panel_id       int not null references lab_panels,
  ranges_version text not null,        -- markers.yaml version used
  findings       jsonb not null,       -- list[Finding], what the report was written from
  report_md      text not null,
  created_at     timestamptz not null default now()
);
```

Notes:

- `lab_results` keeps raw and canonical side by side, so a wrong alias or conversion is fixable with an update later, without re-ingesting.
- Unmapped markers live only in `lab_panels.raw_extract`. They surface at review; the fix is an alias in `markers.yaml`.
- Reports are stored because they are reread, and `ranges_version` records which table produced them. Re-running `report` on a panel makes a new row.
- Training context is not stored; it is derived from the existing tables at report time.
- Migrations are applied by Brian with `psql` to both `tri_analyze` and `tri_analyze_test`, per the global read-only rule.

## 6. Models (`labs/models.py`)

```python
class RawResult(BaseModel):            # what extraction returns; no interpretation
    name: str                          # verbatim
    value: str                         # verbatim, e.g. "12.4" or "<5"
    unit: str | None
    ref_low: str | None
    ref_high: str | None
    flag: str | None                   # H, L, HH, LL, or the lab's own text
    page: int | None

class LabResult(BaseModel):            # after normalize
    marker: str                        # canonical key
    value: float
    unit: str                          # canonical
    raw: RawResult
    lab_ref_low: float | None
    lab_ref_high: float | None
    note: str | None                   # e.g. "value '<5' stored as bound 5"

class PanelContext(BaseModel):
    fasting: bool | None
    draw_time: time | None
    supplements: list[str]
    diet_pattern: str | None           # free text, short
    symptoms: list[str]
    notes: str | None

class TrainingContext(BaseModel):      # from training_context.py
    drawn_on: date
    ctl: float | None
    atl: float | None
    tsb: float | None
    tss_7d: float | None
    last_sessions: list[dict]          # date, sport, duration_min, tss, title; up to 3 in the 72 h before
    sleep_2n_avg_sec: int | None
    sleep_30d_avg_sec: int | None
    hrv_2n_avg: int | None
    hrv_30d_avg: int | None

class Finding(BaseModel):              # evaluate output, one per LabResult
    marker: str
    display: str
    system: str
    value: float
    unit: str
    conventional_status: Literal["low", "in_range", "high"]
    functional_status: Literal["low", "suboptimal_low", "optimal", "suboptimal_high", "high"]
    functional_range: tuple[float | None, float | None]
    previous: tuple[date, float] | None
    delta_pct: float | None
    active_confounders: list[str]
    athlete_note: str
```

Status rules: `conventional_status` uses the lab's printed range when present, else the table's conventional range. `functional_status` uses only the table's ranges: `low` below the table's conventional low, `suboptimal_low` between the table's conventional low and functional low, `optimal` inside the functional range, and the mirror on the high side. `direction: low` or `high` in the spec collapses the irrelevant side to `optimal`.

## 7. The ranges table (`ranges/markers.yaml`)

```yaml
version: 2026-09-10.1
markers:
  ferritin:
    display: Ferritin
    system: iron
    unit: ng/mL
    aliases: [ferritin, "ferritin, serum"]
    conversions: {"µg/L": 1.0, "ug/L": 1.0}
    conventional: {low: 30, high: 400}
    functional: {low: 50, high: 150}
    direction: both                    # low | high | both
    athlete_note: >
      Endurance athletes: below 50 impairs adaptation even with normal hemoglobin; below 30 is
      actionable. Ferritin is an acute-phase reactant and rises for 24-72 h after hard or long
      sessions, so read with hs-CRP and training proximity.
    confounders: [recent_hard_session, inflammation]
    sources: ["Weatherby & Ferguson, Blood Chemistry and CBC Analysis", "IFM functional ranges"]
```

- Systems: `iron`, `thyroid`, `metabolic`, `lipids`, `inflammation`, `liver`, `kidney`, `cbc`, `hormones`, `vitamins_minerals`, `electrolytes`.
- Sex-specific ranges are written as `conventional: {male: {...}, female: {...}}` where they differ; `registry.py` resolves them with the `TRI_ATHLETE_SEX` setting. Single-athlete app, so one setting.
- Fields the code depends on: `unit`, `aliases`, `conversions`, `conventional`, `functional`, `direction`, `confounders`. Prose fields go to the report prompt verbatim.
- `registry.py` validates the file when imported: every marker has the required fields, functional range lies within the conventional range, aliases are unique across markers, conversion targets are the canonical unit. A failure names the marker and field. Tests import the registry, so a typo fails the suite.
- Alias matching: lowercase, strip punctuation and parenthesized qualifiers, collapse whitespace, then exact match against the index. No fuzzy matching in v1; a miss is shown at review and fixed with an alias.
- Initial set, around 60 markers: CBC with differential; CMP; lipids with ApoB and Lp(a); fasting glucose, insulin, HbA1c; TSH, free T4, free T3, reverse T3, TPO and Tg antibodies; ferritin, serum iron, TIBC, transferrin saturation; hs-CRP, homocysteine; vitamin D, B12, folate, RBC magnesium, zinc, omega-3 index; total and free testosterone, SHBG, AM cortisol, DHEA-S; CK, uric acid.
- Sources: Weatherby & Ferguson's functional ranges, IFM published optimal ranges, and endurance-athlete literature for the athlete notes (ferritin, CK, cortisol, testosterone, vitamin D). Where sources disagree, the entry uses one and names the alternative in `athlete_note`. Brian reviews the whole file before milestone 1 closes.

## 8. Evaluate (`labs/evaluate.py`, pure)

Inputs: the panel's `LabResult`s, the registry, the previous value per marker (most recent earlier panel that has it), the `PanelContext`, and the `TrainingContext`. Output: `list[Finding]`.

Confounder rules, constants at the top of the module:

| Confounder | Fires when |
|---|---|
| `recent_hard_session` | Any workout in the 72 h before `drawn_on` with TSS above 150 or duration above 120 min |
| `high_acute_load` | ATL on `drawn_on` exceeds CTL by more than 15 |
| `poor_sleep` | Mean of the two nights before the draw is more than 60 min below the 30-day mean |
| `low_hrv` | Mean of the two nights before the draw is more than 10 % below the 30-day mean |
| `not_fasting` | `context.fasting` is false |
| `afternoon_draw` | `context.draw_time` after 10:00, relevant to cortisol and testosterone |
| `inflammation` | hs-CRP in the same panel is above its functional high |

A finding lists only the confounders its spec declares. `delta_pct` is relative to the previous value; `previous` is null on the first panel with that marker.

## 9. The ingest graph

Thread id `ingest:<sha256 of the file>`, so rerunning on the same file resumes at review instead of re-extracting. Postgres checkpointer, same tables as planning.

### 9.1 State

```python
class IngestState(TypedDict):
    source_path: str
    source_kind: Literal["pdf", "export"]
    raw_results: list[RawResult]
    drawn_on: date | None
    lab_name: str | None
    results: list[LabResult]
    unmapped: list[RawResult]
    context: PanelContext | None
    decision: Literal["approve", "reject"] | None
    panel_id: int | None
    last_error: str | None
```

### 9.2 Nodes and edges

```
START -> extract -> normalize -> review -> store -> END
                                   └──(reject)──> END, nothing stored
extract -> END when it produced no rows or no draw date (last_error set)
```

- **extract**: `extract.sniff` picks the path. For `export`, `exports.py` matches the header row or JSON shape against its known formats and parses deterministically; an unknown layout falls through to the model path. For `pdf`, and for unknown exports, one `with_structured_output(ExtractedPanel)` call where `ExtractedPanel` is `{drawn_on, lab_name, results: list[RawResult]}`. The PDF is sent as a `file` content block. The prompt asks for every row that has a numeric or bounded value, names and units verbatim, the printed range and flag, the draw date, and nothing inferred. Page count and result count are logged and traced. The first supported export format is chosen in milestone 2 from a real file Brian provides.
- **normalize**: pure. Each raw name goes through the alias index. Units convert through the marker's `conversions`; an unknown unit keeps the row with `note = "unit?"` and it cannot be stored until edited. A bounded value such as `<5` is stored as the bound with a note. Unmatched names go to `unmapped`.
- **review**: `interrupt({"results", "unmapped", "drawn_on", "lab_name"})`. The REPL prints a table with canonical marker, value, unit, lab range, lab flag and raw name, then the unmapped rows below it, then any duplicate-panel warning. It collects the `PanelContext` with short prompts. Decisions: `approve`, `edit` (opens results, unmapped and context as YAML in `$EDITOR`, same helper planning uses, and re-validates on return), `reject`. Resume is `Command(resume=decision)`.
- **store**: one transaction: insert `lab_panels`, its `lab_results`, and the raw extract. Prints the panel id.

## 10. Report

`tri-wellness report` runs evaluate, then one streaming model call. Input: the findings, the panel context, the training context, the previous report's priorities section if one exists, and the athlete profile. The model never sees a raw value without its status and functional range.

Fixed structure, so reports are comparable across panels:

1. One-line disclaimer, verbatim from the prompt.
2. **Draw conditions**: fasting, timing, active confounders, and how much weight each carries.
3. **By system**: for each system with at least one non-optimal marker, what the pattern across its markers says. Systems that are entirely optimal get one line.
4. **Priorities**: at most three, ranked, with reasoning.
5. **Training implications**: load, intensity, recovery over the coming weeks, written so it could be pasted into a planning intake constraint.
6. **Levers**: nutrition, sleep, stress and training changes tied to specific findings.
7. **Supplements**: compound, dose range, timing, target marker, and what would show it worked. Framed for discussion with a practitioner.
8. **Retest plan**: which markers, when, and under what draw conditions.
9. **Questions for your practitioner.**
10. **Changes since last panel**, when a previous panel exists.

Rules in the prompt: cite the functional range used for every flagged marker; name confounders when they apply; distinguish "pattern suggests" from "marker shows"; no generic wellness advice; do not restate optimal markers beyond the one-line system summary. The report is saved to `lab_reports` with the findings and `ranges_version`, and optionally written to `--out`.

## 11. Chat

`create_agent`, the analyze pattern. Tools bound in fixed order:

1. `query_training_db`: tri-core's read-only SQL tool with its schema doc extended to cover `lab_panels`, `lab_results` and `lab_reports`.
2. `get_panel_findings(panel: int | "latest")`: runs evaluate and returns the findings as compact JSON.
3. `get_marker_spec(marker)`: the YAML entry, resolved for the athlete's sex.
4. `get_marker_history(marker)`: every stored value with draw date, unit and functional status, oldest first.

System prompt, built once per session: athlete profile from `athlete_profile`, the latest report's priorities and retest plan, the same rules as the report prompt, today's date. Conversation memory is an in-process message list, as in analyze. REPL commands: `/panels`, `/report [ID]` reprints a saved report, `/prompt`, `/tools`, `/quit`.

## 12. Commands

- `tri-wellness ingest <file> [--kind pdf|export]`: kind is sniffed from the extension unless given. Runs the graph, pauses at review, stores on approve, prints the panel id.
- `tri-wellness report [--panel ID] [--out path.md]`: defaults to the latest panel.
- `tri-wellness chat`.
- `tri-wellness panels`: date, lab, result count, unmapped count, whether a report exists.

## 13. Error handling

| Failure | Behavior |
|---|---|
| Extraction returns no rows or no draw date | Graph ends before review with the reason in `last_error`; nothing stored. |
| Marker unmapped | Shown at review; approve keeps it only in `raw_extract`. |
| Unit unknown for a mapped marker | Row flagged `unit?` at review; approve is refused until the row is edited or removed. |
| Duplicate panel, same `drawn_on` and `lab_name` | Review warns; approve stores a second panel rather than merging. |
| Ranges file invalid | Registry raises on import naming the marker and field. |
| Anthropic API error | Caught per command and printed. An ingest thread resumes from its checkpoint on rerun. |
| Checkpointer unavailable | `ingest` refuses to start with a clear message. `report`, `chat` and `panels` do not need it. |
| `$EDITOR` returns invalid YAML | Validation errors printed; review re-prompts. |

## 14. Configuration

`tri_core.config` is shared. `tri_wellness.config` adds `TRI_ATHLETE_SEX` (`male` | `female`, required for sex-specific ranges) and `LANGSMITH_PROJECT` default `tri_wellness`. New dependency: `pyyaml` (already used by tri-planning). No new MCP servers.

## 15. Testing

- **Unit, no model, no DB**: registry validation, including a fixture YAML that fails each rule; every alias and conversion in `markers.yaml` round-trips; normalize on fixture raw results including `<5`, unknown units and unmapped names; evaluate at every status boundary and for each confounder rule; report prompt builder output; YAML edit round trip.
- **Extraction fixtures**: a recorded structured-output response per source kind; the deterministic export parser against its fixture file.
- **Graph, `ScriptedChatModel`**: review pauses; approve stores one panel with the expected result rows; reject stores nothing; a second process resumes the same thread at review.
- **DB tests** on `tri_analyze_test` with the rolled-back `db` fixture from `tri_core.testing`: repo reads and writes, `get_marker_history` ordering, training context around a seeded draw date.
- **Live, opt-in `--live`**: real PDF extraction against one redacted panel Brian provides; asserts row count and draw date.
- Definition of done per task: `uv run pytest`, `ruff check`, `ruff format --check`, `mypy` strict on `src/`.

## 16. Observability

LangSmith tracing by env, project `tri_wellness`. Extraction runs carry `source_kind` and `page_count` tags; report runs carry `panel_id` and `ranges_version`. Milestone 3 adds a LangSmith dataset of findings sets and a code evaluator that checks each report cites a functional range for every non-optimal marker.

## 17. Milestones

1. **Ranges and evaluate.** Package scaffold, `004_wellness.sql`, `markers.yaml` drafted, registry, models, normalize, evaluate, training context. All pure and tested. Brian's review of the YAML closes the milestone.
2. **Ingest.** Extraction for PDF and one export format, the graph, review REPL, store. First real panel in the database.
3. **Report and chat.** The report call and prompt, the chat agent and its tools, `panels`, the LangSmith evaluator.
4. **Later, separate spec.** Trends across panels, symptom and supplement logging over time, a per-system fan-out for the report, and findings flowing into planning intake as constraints.

## 18. Out of scope

Multi-athlete; photo or image input; writing to any external system; live MCP tools; diagnosis language beyond functional-range interpretation; scheduled execution; any UI beyond the terminal.

## 19. Open items to verify in milestone 1

- Whether `with_structured_output` over a long PDF returns all rows in one call, or whether large panels need a per-page pass. Decide from the first real panel.
- Which export format ships first; needs a real file.
- Whether the existing `tri_core.db.sql_tool` schema doc is a constant that can be extended, or needs a parameter.
- The exact list of markers in the athlete's usual panel, to prioritize the YAML draft.
