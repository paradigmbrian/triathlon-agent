# tri-wellness Plan 2 of 3: Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `tri-wellness ingest <file>`: extraction from a PDF (one structured-output model call with the PDF as a document block) or a structured export (deterministic parser, model fallback), the pure normalize step from Plan 1, a review interrupt with a terminal table, context prompts and a YAML editor, and a store step that writes one panel in one transaction. First real panel in the database. This is spec milestone 2.

**Architecture:** A four-node LangGraph graph (`extract -> normalize -> review -> store`) with a Postgres checkpointer, thread id `ingest:<sha256 of the file>`, so rerunning on the same file resumes at review instead of re-extracting. Nodes are closures over `GraphDeps` (model, connection factory, registry). The review node is the only `interrupt()`; edit and a refused approve loop back to it. The REPL owns rendering, the decision dialogue, context collection and `$EDITOR`; the graph owns validation of what comes back.

**Tech Stack:** langgraph (StateGraph, `interrupt`, `Command`), `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`), `langchain-anthropic` (`with_structured_output`, base64 `file` content block -> Anthropic `document`), typer, rich, PyYAML. Depends on Plan 1 (`tri_wellness.labs.{models,normalize}`, `tri_wellness.ranges.registry`, `tri_wellness.repo`, `tri_wellness.testing`).

**Spec:** `docs/superpowers/specs/2026-09-10-tri-wellness-design.md` (§3 overview, §4 layout, §9 ingest graph, §12 commands, §13 error handling, §15 testing, §16 observability, §17 milestone 2, §19 open items 1 and 2).

## Global Constraints

- Python `>=3.12,<3.13`, uv-managed, commands run from the repository root as `uv run ...`.
- `tri-wellness` depends on `tri-core` only. The REPL and graph plumbing are copied from tri-planning where the spec says "the same helper planning uses"; nothing imports `tri_planning`.
- No new dependencies. No PDF library: page count is a byte-level regex, extraction is the model.
- Thread id is exactly `ingest:<sha256 hex of the file bytes>` (spec §9). Checkpoint tables are the ones `scripts/setup_checkpointer.py` creates; `ingest` refuses to start when `checkpointer_ready` is false (spec §13).
- Extraction runs carry LangSmith tags `source_kind:<pdf|export>` and `page_count:<n>` (spec §16).
- Review decisions are `approve`, `edit`, `reject` (spec §9.2). Approve is refused while any unmapped row has reason `unit` or `value` (Plan 1's `Unmapped.reason`; spec §13 "approve is refused until the row is edited or removed"). Rows with reason `name` or `duplicate` are allowed through and live only in `raw_extract`.
- Duplicate panel (same `drawn_on` and `lab_name`): review warns; approve stores a second panel (spec §13).
- Anthropic API errors are caught per command and printed; the thread resumes from its checkpoint on rerun (spec §13).
- **Execute in a sibling worktree** on branch `feat/tri-wellness-02` from `main` after Plan 1 is merged. Brian runs `scripts/setup_checkpointer.py` against both databases if the checkpoint tables are missing (they exist from planning).
- Definition of done per task: `uv run ruff format packages/tri-wellness && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
- No "LangChain lesson:" framing in docstrings.
- Every markdown file created or edited is copied to `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/<same relative path>`.

### Spec deviations decided in this plan

- **`IngestState` gains `drawn_on_hint`, `page_count` and typed `unmapped: list[Unmapped]`.** Spec §9.1 lists `unmapped: list[RawResult]`; Plan 1's normalize returns `Unmapped(raw, reason, marker)` so the review table can say why a row failed. `drawn_on_hint` carries `--drawn-on` from the command line into extract (spec §13 "no draw date" would otherwise be a dead end for exports without a date column). `page_count` is what the trace tag and the log line report.
- **The review decision is a model, `IngestDecision`,** not the bare string spec §9.2 writes (`Command(resume=decision)`). Approve must carry the `PanelContext` the REPL collected; edit carries the replaced results, unmapped rows, draw date, lab name and context. `IngestState.decision` stays `"approve" | "reject" | None` as the spec has it.
- **Edit and a refused approve loop back to review** (`review -> review` edge when `decision` is `None`). Spec §9.2 says edit "re-validates on return"; the node returns the edited state and the next super-step interrupts again with the edited table, so the athlete sees what will be stored before approving. A refused approve (blocking unmapped rows, or no context) sets `last_error`, which the next interrupt payload shows.
- **`extract` clears `decision` and `panel_id`** so rerunning a rejected file on the same thread starts clean; a stored file is not re-ingested (`ingest` says which panel it is and exits 0).
- **Export formats.** Spec §19 item 2 says the first format is chosen from a real file. Until Brian provides one, `exports.py` ships one deterministic parser, `generic_csv`: a CSV whose header has a name column (`name`, `marker`, `test`, `biomarker`, `analyte`) and a value column (`value`, `result`), with optional `unit`/`units`, `ref_low`/`low`, `ref_high`/`high`, `flag`, a date column (`drawn_on`, `collected`, `collection_date`, `date`) and `lab`. Any other layout (including JSON) falls through to the model with the file text in the prompt. A second parser keyed on the real file's header is a one-function addition.
- **PDF page count** is `len(re.findall(rb"/Type\s*/Page[^s]", data))`; good enough for a tag and a log line, and zero dependencies.
- **`MAX_TOKENS = 32000`** for the extraction model (a 200-row panel is roughly 12k output tokens as JSON). The report model in Plan 3 uses the same constructor.
- **`run_ingest` exit codes**: `0` stored (or already stored), `1` extraction or API error, `2` rejected, `3` paused (EOF or `/quit` at review; rerun resumes).
- **`$EDITOR` YAML** is one document with `drawn_on`, `lab_name`, `context`, `results` (one mapping per row: `marker`, `value`, `unit`, `raw_name`, `raw_value`, `raw_unit`, `raw_ref_low`, `raw_ref_high`, `lab_ref_low`, `lab_ref_high`, `flag`, `note`) and `unmapped` (one mapping per row: `reason`, `marker`, and the raw fields). Moving a row from `unmapped` to `results` with a `marker`, `value` and the canonical `unit` is how an unknown unit is fixed. `review_from_yaml` validates every result against the registry (marker exists, unit is the canonical unit, value numeric) and names the row on failure.

---

## File Structure

```
packages/tri-wellness/src/tri_wellness/
  labs/models.py            + ExtractedPanel, IngestDecision, IngestKind
  labs/extract/
    __init__.py             sniff(), file_sha256(), count_pdf_pages()
    structured.py           extract_structured(): the one model call, shared by pdf and fallback
    pdf.py                  extract_pdf(): PDF bytes as a file block
    exports.py              detect_format(), parse_generic_csv(), parse_export(), extract_export_with_model()
  prompts/
    __init__.py
    extract.py              EXTRACT_SYSTEM, render_extract_prompt()
  graph/
    __init__.py
    state.py                IngestState
    deps.py                 GraphDeps, make_deps()
    llm.py                  make_model()
    checkpointer.py         open_checkpointer(), checkpointer_ready(), make_serde(), SETUP_HINT
    graph.py                build_ingest_graph(), after_extract(), after_review()
    nodes/
      __init__.py
      extract.py            make_extract_node()
      normalize.py          make_normalize_node()
      review.py             make_review_node(), blocking_rows()
      store.py              make_store_node()
  repl.py                   render_review(), parse_decision(), collect_context(), review_to_yaml(),
                            review_from_yaml(), review_dialogue(), run_turn(), run_ingest()
  cli.py                    + ingest command, edit_in_editor()
  testing.py                + NoCommit, RecordingScriptedModel, EXTRACTED (fixture loader)
packages/tri-wellness/tests/
  conftest.py               + nocommit, make_deps, tiny_pdf fixtures
  fixtures/extract/pdf_panel.json, pdf_panel_bad_unit.json
  fixtures/exports/generic.csv, unknown.csv
  test_ingest_models.py, test_extract.py, test_exports.py, test_graph.py, test_repl.py,
  test_cli.py, test_checkpointer.py, test_live_pdf.py
```

Responsibilities: `extract/` turns a file into an `ExtractedPanel` and knows nothing about markers. `graph/nodes` are thin: each calls one Plan 1 or `extract/` function and maps the result onto state. `repl.py` is the only module that formats for a terminal or reads from one. `cli.py` wires settings, checkpointer, model and editor together.

---

### Task 1: Ingest models, state and graph plumbing

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/labs/models.py` (append)
- Create: `packages/tri-wellness/src/tri_wellness/graph/__init__.py`, `graph/state.py`, `graph/deps.py`, `graph/llm.py`, `graph/checkpointer.py`, `graph/nodes/__init__.py`, `prompts/__init__.py`
- Modify: `packages/tri-wellness/src/tri_wellness/testing.py` (append `NoCommit`), `packages/tri-wellness/tests/conftest.py`
- Test: `packages/tri-wellness/tests/test_ingest_models.py`, `packages/tri-wellness/tests/test_checkpointer.py`

**Interfaces:**
- Consumes: Plan 1 `RawResult`, `LabResult`, `Unmapped`, `PanelContext`; `MarkerRegistry`, `load_registry`; `WellnessSettings`.
- Produces: `IngestKind = Literal["pdf", "export"]`; `ExtractedPanel(drawn_on: date | None, lab_name: str | None, results: list[RawResult])`; `IngestDecision(action, context, note, results, unmapped, drawn_on, lab_name)`; `IngestState`; `GraphDeps(model, connect, registry)`; `make_deps(settings, model)`; `make_model(settings)`; `open_checkpointer(url)`, `checkpointer_ready(url)`, `make_serde()`, `SETUP_HINT`; `NoCommit`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_ingest_models.py`:
```python
from datetime import date, time

import pytest
from pydantic import ValidationError

from tri_wellness.labs.models import ExtractedPanel, IngestDecision, PanelContext, RawResult


def test_extracted_panel_defaults_to_nothing_inferred():
    p = ExtractedPanel()
    assert p.drawn_on is None and p.lab_name is None and p.results == []
    p2 = ExtractedPanel.model_validate(
        {"drawn_on": "2026-08-20", "lab_name": "Quest", "results": [{"name": "Ferritin", "value": "42"}]}
    )
    assert p2.drawn_on == date(2026, 8, 20) and p2.results[0].unit is None


def test_ingest_decision_shapes():
    a = IngestDecision(action="approve", context=PanelContext(fasting=True, draw_time=time(7, 0)))
    assert a.results is None and a.note is None
    r = IngestDecision.model_validate({"action": "reject", "note": "wrong file"})
    assert r.note == "wrong file"
    e = IngestDecision.model_validate(
        {"action": "edit", "drawn_on": "2026-08-21", "unmapped": [], "results": None}
    )
    assert e.drawn_on == date(2026, 8, 21) and e.unmapped == [] and e.results is None
    with pytest.raises(ValidationError):
        IngestDecision(action="maybe")
    round_trip = IngestDecision.model_validate(a.model_dump(mode="json", exclude_none=True))
    assert round_trip == a


def test_raw_result_is_what_the_state_carries():
    assert RawResult(name="x", value="1").model_dump()["page"] is None
```

`packages/tri-wellness/tests/test_checkpointer.py`:
```python
import logging
from datetime import time

from tri_wellness.graph.checkpointer import make_serde
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped


def test_serde_round_trips_state_models_without_unregistered_warning(caplog):
    from langgraph.checkpoint.serde import jsonplus

    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    raw = RawResult(name="Ferritin", value="42", unit="ng/mL")
    result = LabResult(marker="ferritin", value=42.0, unit="ng/mL", raw=raw)
    unmapped = Unmapped(raw=RawResult(name="ESR", value="4"), reason="name")
    ctx = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["iron"])
    state = {"raw_results": [raw], "results": [result], "unmapped": [unmapped], "context": ctx}
    serde = make_serde()
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed(state))
    assert back == state
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_ingest_models.py packages/tri-wellness/tests/test_checkpointer.py -q`
Expected: `ImportError: cannot import name 'ExtractedPanel'` and `ModuleNotFoundError: No module named 'tri_wellness.graph'`.

- [ ] **Step 3: Append the models**

Append to `packages/tri-wellness/src/tri_wellness/labs/models.py`:
```python


IngestKind = Literal["pdf", "export"]


class ExtractedPanel(BaseModel):
    """What extraction returns for one file. Nothing inferred: a missing draw date stays None."""

    drawn_on: date | None = None
    lab_name: str | None = None
    results: list[RawResult] = Field(default_factory=list)


class IngestDecision(BaseModel):
    """The athlete's answer at review. approve carries the panel context; edit carries every
    field it replaced; reject carries a note."""

    action: Literal["approve", "edit", "reject"]
    context: PanelContext | None = None
    note: str | None = None
    results: list[LabResult] | None = None
    unmapped: list[Unmapped] | None = None
    drawn_on: date | None = None
    lab_name: str | None = None
```

- [ ] **Step 4: Write the graph plumbing**

`packages/tri-wellness/src/tri_wellness/graph/__init__.py`, `graph/nodes/__init__.py`, `prompts/__init__.py`: empty files.

`packages/tri-wellness/src/tri_wellness/graph/state.py`:
```python
"""Ingest graph state. Every key is last-write-wins; there is no conversation."""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from tri_wellness.labs.models import IngestKind, LabResult, PanelContext, RawResult, Unmapped


class IngestState(TypedDict, total=False):
    source_path: str
    source_kind: IngestKind
    drawn_on_hint: date | None
    page_count: int | None
    raw_results: list[RawResult]
    drawn_on: date | None
    lab_name: str | None
    results: list[LabResult]
    unmapped: list[Unmapped]
    context: PanelContext | None
    decision: Literal["approve", "reject"] | None
    panel_id: int | None
    last_error: str | None
```

`packages/tri-wellness/src/tri_wellness/graph/deps.py`:
```python
"""What the nodes need from the outside world, injected once at build time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from tri_core.db.connection import connect as core_connect
from tri_core.db.repo import Conn
from tri_wellness.config import WellnessSettings
from tri_wellness.ranges.registry import MarkerRegistry, load_registry

ConnectFactory = Callable[[], AbstractContextManager[Conn]]


@dataclass
class GraphDeps:
    model: BaseChatModel
    connect: ConnectFactory
    registry: MarkerRegistry


def make_deps(settings: WellnessSettings, model: BaseChatModel) -> GraphDeps:
    url = settings.database_url
    return GraphDeps(
        model=model,
        connect=lambda: core_connect(url),
        registry=load_registry(settings.tri_athlete_sex),
    )
```

`packages/tri-wellness/src/tri_wellness/graph/llm.py`:
```python
"""Model construction. One constructor for extraction, the report and chat."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from tri_core.config import Settings

MAX_TOKENS = 32000  # a 200-row panel is roughly 12k output tokens as JSON; reports are long


def make_model(settings: Settings) -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.tri_model, max_tokens=MAX_TOKENS, api_key=settings.anthropic_api_key
    )
```

`packages/tri-wellness/src/tri_wellness/graph/checkpointer.py`:
```python
"""Postgres-backed checkpointing so a paused review survives process exit. Same tables as
planning and nutrition; ingest threads are keyed `ingest:<sha256>`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped

STATE_TYPES: tuple[type, ...] = (RawResult, LabResult, Unmapped, PanelContext)

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


@asynccontextmanager
async def open_checkpointer(url: str) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url, serde=make_serde()) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])
```

Append to `packages/tri-wellness/src/tri_wellness/testing.py`:
```python


class NoCommit:
    """The rolled-back test connection; commit/close are no-ops so nodes can call them."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self) -> NoCommit:
        return self

    def __exit__(self, *exc: object) -> None:
        return None
```

Replace `packages/tri-wellness/tests/conftest.py` with:
```python
from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from tri_wellness.testing import NoCommit

TINY_PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
    b"4 0 obj << /Type /Page /Parent 2 0 R >> endobj\n%%EOF\n"
)


@pytest.fixture
def wdb(db):
    """The rolled-back test connection, skipped until 005_wellness.sql is applied."""
    if db.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied to the test database")
    return db


@pytest.fixture
def nocommit(wdb):
    return NoCommit(wdb)


@pytest.fixture
def make_deps(nocommit):
    from tri_wellness.graph.deps import GraphDeps
    from tri_wellness.ranges.registry import load_registry

    registry = load_registry("male")

    def _make(model) -> GraphDeps:
        return GraphDeps(
            model=model, connect=lambda: contextlib.nullcontext(nocommit), registry=registry
        )

    return _make


@pytest.fixture
def tiny_pdf(tmp_path) -> Path:
    p = tmp_path / "panel.pdf"
    p.write_bytes(TINY_PDF)
    return p
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-wellness -q`
Expected: Plan 1's tests still pass plus 4 new ones.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): ingest models, state, deps, model and checkpointer plumbing"
```

---

### Task 2: Extraction (`labs/extract/`, `prompts/extract.py`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/labs/extract/__init__.py`, `labs/extract/structured.py`, `labs/extract/pdf.py`, `labs/extract/exports.py`, `prompts/extract.py`, `tests/fixtures/extract/pdf_panel.json`, `tests/fixtures/extract/pdf_panel_bad_unit.json`, `tests/fixtures/exports/generic.csv`, `tests/fixtures/exports/unknown.csv`
- Modify: `packages/tri-wellness/src/tri_wellness/testing.py` (append `RecordingScriptedModel`, `load_extracted`)
- Test: `packages/tri-wellness/tests/test_extract.py`, `packages/tri-wellness/tests/test_exports.py`

**Interfaces:**
- Consumes: `ExtractedPanel`, `RawResult`, `IngestKind` (Task 1); `tri_core.testing.ScriptedChatModel`.
- Produces: `sniff(path: Path, kind: IngestKind | None = None) -> IngestKind`; `file_sha256(path) -> str`; `count_pdf_pages(data: bytes) -> int`; `extract_structured(model, prompt: str, attachment: dict[str, Any] | None, tags: list[str], config) -> ExtractedPanel`; `extract_pdf(model, path, drawn_on_hint, config) -> tuple[ExtractedPanel, int]`; `detect_format(path) -> str | None`; `parse_export(path) -> ExtractedPanel | None`; `extract_export_with_model(model, path, drawn_on_hint, config) -> ExtractedPanel`; `EXTRACT_SYSTEM`; `render_extract_prompt(kind, drawn_on_hint, body: str | None) -> str`; `RecordingScriptedModel`; `load_extracted(name) -> dict`.

- [ ] **Step 1: Write the fixtures**

`packages/tri-wellness/tests/fixtures/extract/pdf_panel.json` (a recorded `ExtractedPanel`, the shape `with_structured_output` returns; six rows across two pages, one unmapped, one bounded):
```json
{
  "drawn_on": "2026-08-20",
  "lab_name": "Quest Diagnostics",
  "results": [
    {"name": "Ferritin", "value": "42", "unit": "ng/mL", "ref_low": "30", "ref_high": "400", "flag": null, "page": 1},
    {"name": "Iron, Total", "value": "95", "unit": "mcg/dL", "ref_low": "50", "ref_high": "180", "flag": null, "page": 1},
    {"name": "hs-CRP", "value": "<0.3", "unit": "mg/L", "ref_low": null, "ref_high": "3.0", "flag": null, "page": 1},
    {"name": "Glucose", "value": "92", "unit": "mg/dL", "ref_low": "65", "ref_high": "99", "flag": null, "page": 2},
    {"name": "TSH", "value": "1.52", "unit": "mIU/L", "ref_low": "0.40", "ref_high": "4.50", "flag": null, "page": 2},
    {"name": "Sed Rate, Westergren", "value": "4", "unit": "mm/h", "ref_low": "0", "ref_high": "15", "flag": null, "page": 2}
  ]
}
```
Note `Iron, Total` is printed in `mcg/dL`: not in `iron_serum.conversions` in Plan 1 (`ug/dL`, `µg/dL`, `umol/L`, `µmol/L`), so in Plan 1's normalize it is an `unit` row. **Add `"mcg/dL": 1.0` to `iron_serum.conversions`, `zinc.conversions` and `tibc.conversions` in `markers.yaml`** in this task (labs print `mcg` as often as `ug`); after that the fixture normalizes to five results and one `name` row (`Sed Rate`).

`packages/tri-wellness/tests/fixtures/extract/pdf_panel_bad_unit.json`: the same document with the ferritin row's unit changed to `"furlongs"` (so normalize reports it as reason `unit`).

`packages/tri-wellness/tests/fixtures/exports/generic.csv`:
```csv
name,value,unit,ref_low,ref_high,flag,collected,lab
Ferritin,42,ng/mL,30,400,,2026-08-20,Function Health
hs-CRP,<0.3,mg/L,,3.0,,2026-08-20,Function Health
Glucose,92,mg/dL,65,99,,2026-08-20,Function Health
Vitamin D,38,ng/mL,30,100,L,2026-08-20,Function Health
```

`packages/tri-wellness/tests/fixtures/exports/unknown.csv`:
```csv
foo,bar,baz
1,2,3
```

- [ ] **Step 2: Write the failing tests**

`packages/tri-wellness/tests/test_extract.py`:
```python
import base64
import hashlib
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from tri_core.testing import tool_call
from tri_wellness.labs.extract import count_pdf_pages, file_sha256, sniff
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import EXTRACT_SYSTEM, render_extract_prompt
from tri_wellness.testing import RecordingScriptedModel, load_extracted


def test_sniff_by_extension_and_override(tmp_path):
    assert sniff(Path("a.PDF")) == "pdf"
    assert sniff(Path("a.csv")) == "export"
    assert sniff(Path("a.json")) == "export"
    assert sniff(Path("a.txt"), "export") == "export"
    with pytest.raises(ValueError, match="--kind"):
        sniff(Path("a.txt"))


def test_sha_and_page_count(tiny_pdf):
    assert file_sha256(tiny_pdf) == hashlib.sha256(tiny_pdf.read_bytes()).hexdigest()
    assert count_pdf_pages(tiny_pdf.read_bytes()) == 2
    assert count_pdf_pages(b"not a pdf") == 0


def test_render_extract_prompt_mentions_hint_and_rules():
    p = render_extract_prompt("pdf", None, None)
    assert "verbatim" in p and "draw date" in p.lower()
    assert "2026-08-20" in render_extract_prompt("pdf", date(2026, 8, 20), None)
    body = render_extract_prompt("export", None, "name,value\nFerritin,42")
    assert "Ferritin,42" in body
    assert "ExtractedPanel" in EXTRACT_SYSTEM


async def test_extract_pdf_sends_document_block_and_parses(tiny_pdf):
    fixture = load_extracted("pdf_panel")
    model = RecordingScriptedModel(script=[tool_call("ExtractedPanel", fixture)])
    panel, pages = await extract_pdf(model, tiny_pdf, None, None)
    assert isinstance(panel, ExtractedPanel)
    assert panel.model_dump(mode="json") == fixture
    assert pages == 2 and model.calls == 1
    messages = model.received[0]
    assert isinstance(messages[0], SystemMessage) and messages[0].content == EXTRACT_SYSTEM
    human = messages[1]
    assert isinstance(human, HumanMessage) and isinstance(human.content, list)
    text_block, file_block = human.content
    assert text_block["type"] == "text" and "verbatim" in text_block["text"]
    assert file_block == {
        "type": "file",
        "source_type": "base64",
        "mime_type": "application/pdf",
        "data": base64.b64encode(tiny_pdf.read_bytes()).decode(),
    }
```

`packages/tri-wellness/tests/test_exports.py`:
```python
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage

from tri_core.testing import tool_call
from tri_wellness.labs.extract.exports import (
    detect_format,
    extract_export_with_model,
    parse_export,
)
from tri_wellness.testing import RecordingScriptedModel, load_extracted

FIX = Path(__file__).parent / "fixtures" / "exports"


def test_detect_generic_csv():
    assert detect_format(FIX / "generic.csv") == "generic_csv"
    assert detect_format(FIX / "unknown.csv") is None


def test_parse_generic_csv():
    panel = parse_export(FIX / "generic.csv")
    assert panel is not None
    assert panel.drawn_on == date(2026, 8, 20) and panel.lab_name == "Function Health"
    assert [r.name for r in panel.results] == ["Ferritin", "hs-CRP", "Glucose", "Vitamin D"]
    crp = panel.results[1]
    assert (crp.value, crp.unit, crp.ref_low, crp.ref_high, crp.flag) == ("<0.3", "mg/L", None, "3.0", None)
    assert panel.results[3].flag == "L"
    assert all(r.page is None for r in panel.results)


def test_parse_generic_csv_without_date_or_lab(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("Test,Result,Units\nFerritin,42,ng/mL\n")
    panel = parse_export(p)
    assert panel is not None and panel.drawn_on is None and panel.lab_name is None
    assert panel.results[0].unit == "ng/mL" and panel.results[0].ref_low is None


def test_unknown_layout_returns_none():
    assert parse_export(FIX / "unknown.csv") is None


async def test_model_fallback_puts_file_text_in_prompt():
    fixture = load_extracted("pdf_panel")
    model = RecordingScriptedModel(script=[tool_call("ExtractedPanel", fixture)])
    panel = await extract_export_with_model(model, FIX / "unknown.csv", date(2026, 8, 20), None)
    assert panel.results[0].name == "Ferritin"
    human = model.received[0][1]
    assert isinstance(human, HumanMessage) and isinstance(human.content, list)
    assert len(human.content) == 1 and "foo,bar,baz" in human.content[0]["text"]
    assert "2026-08-20" in human.content[0]["text"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_extract.py packages/tri-wellness/tests/test_exports.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.labs.extract'`.

- [ ] **Step 4: Write the test doubles**

Append to `packages/tri-wellness/src/tri_wellness/testing.py`:
```python


import json
from pathlib import Path

from langchain_core.language_models import BaseChatModel  # noqa: F401  (re-export for tests)
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from tri_core.testing import ScriptedChatModel

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def load_extracted(name: str) -> dict[str, Any]:
    """A recorded ExtractedPanel from tests/fixtures/extract/<name>.json."""
    with (FIXTURES / "extract" / f"{name}.json").open(encoding="utf-8") as fh:
        return dict(json.load(fh))


class RecordingScriptedModel(ScriptedChatModel):
    """ScriptedChatModel that also keeps every message list it was called with."""

    received: list[list[BaseMessage]] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.received = [*self.received, list(messages)]
        return super()._generate(messages, stop, run_manager, **kwargs)
```
(Move the `import json` and `from pathlib import Path` lines up to the module's import block; ruff's isort rule will insist.) `parents[2]` from `src/tri_wellness/testing.py` is `packages/tri-wellness` (parents[0] is `tri_wellness`, parents[1] is `src`).

- [ ] **Step 5: Write the prompt and the extractors**

`packages/tri-wellness/src/tri_wellness/prompts/extract.py`:
```python
"""Extraction instructions. The model transcribes; it does not interpret."""

from __future__ import annotations

from datetime import date

from tri_wellness.labs.models import IngestKind

EXTRACT_SYSTEM = """\
You transcribe laboratory reports into structured rows and return an ExtractedPanel.

results: one RawResult per printed test that has a numeric or bounded value ("<5", ">200",
"<=0.9"). Copy name, value, unit, reference range and flag exactly as printed, character for
character; do not rename tests, do not convert units, do not fill in a range or flag the report
does not print. value is the printed number or bound as text, never rounded. ref_low and ref_high
are the printed reference range split into its two ends; a one-sided range such as "<3.0" gives
ref_high "3.0" and ref_low null; ">39" gives ref_low "39". flag is the lab's own marker (H, L,
HH, LL, A, or its text). page is the page the row appears on, starting at 1.

drawn_on: the specimen collection date (labels such as "Collected", "Drawn", "Specimen
collected"), as YYYY-MM-DD; null when the report does not print one. Do not use the report or
received date. lab_name: the laboratory that ran the tests, as printed, or null.

Skip rows that are only text ("Negative", "Not detected", "See note"): they carry no numeric
or bounded value. Skip calculated summary lines the report labels as such only when they have no
value. Never invent a row, never merge two tests, never skip a page. Return every row."""


def render_extract_prompt(kind: IngestKind, drawn_on_hint: date | None, body: str | None) -> str:
    lines = [
        f"Source kind: {kind}. Transcribe every result row verbatim into an ExtractedPanel.",
        "Include the draw date and lab name when the document prints them.",
    ]
    if drawn_on_hint is not None:
        lines.append(
            f"If the document prints no collection date, the athlete says the draw date was "
            f"{drawn_on_hint.isoformat()}; use it only in that case."
        )
    if body is not None:
        lines += ["", "The document is this text:", "", body]
    return "\n".join(lines)
```

`packages/tri-wellness/src/tri_wellness/labs/extract/__init__.py`:
```python
"""sniff(file) -> source kind, plus the file-level helpers the graph and CLI share."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tri_wellness.labs.models import IngestKind

_PAGE = re.compile(rb"/Type\s*/Page[^s]")
_EXPORT_SUFFIXES = frozenset({".csv", ".tsv", ".json"})


def sniff(path: Path, kind: IngestKind | None = None) -> IngestKind:
    if kind is not None:
        return kind
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _EXPORT_SUFFIXES:
        return "export"
    raise ValueError(f"cannot tell the source kind from '{path.name}'; pass --kind pdf|export")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_pdf_pages(data: bytes) -> int:
    """Page objects in the file. A regex over the bytes; good enough for a tag and a log line."""
    return len(_PAGE.findall(data))
```

`packages/tri-wellness/src/tri_wellness/labs/extract/structured.py`:
```python
"""The one structured-output call every extraction path uses."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs

from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import EXTRACT_SYSTEM


async def extract_structured(
    model: BaseChatModel,
    prompt: str,
    attachment: dict[str, Any] | None,
    tags: list[str],
    config: RunnableConfig | None,
) -> ExtractedPanel:
    """`attachment` is a standard content block (a base64 `file` block for PDFs) sent after the
    prompt text; langchain-anthropic turns it into an Anthropic `document` block."""
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if attachment is not None:
        content.append(attachment)
    structured = model.with_structured_output(ExtractedPanel)
    cfg = merge_configs(config, {"tags": tags})
    out = await structured.ainvoke(
        [SystemMessage(EXTRACT_SYSTEM), HumanMessage(content=content)], config=cfg
    )
    assert isinstance(out, ExtractedPanel)
    return out
```

`packages/tri-wellness/src/tri_wellness/labs/extract/pdf.py`:
```python
"""PDF extraction: the file goes to the model as a document block; no PDF library."""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from tri_wellness.labs.extract import count_pdf_pages
from tri_wellness.labs.extract.structured import extract_structured
from tri_wellness.labs.models import ExtractedPanel
from tri_wellness.prompts.extract import render_extract_prompt


async def extract_pdf(
    model: BaseChatModel, path: Path, drawn_on_hint: date | None, config: RunnableConfig | None
) -> tuple[ExtractedPanel, int]:
    data = path.read_bytes()
    pages = count_pdf_pages(data)
    attachment = {
        "type": "file",
        "source_type": "base64",
        "mime_type": "application/pdf",
        "data": base64.b64encode(data).decode("ascii"),
    }
    panel = await extract_structured(
        model,
        render_extract_prompt("pdf", drawn_on_hint, None),
        attachment,
        ["source_kind:pdf", f"page_count:{pages}"],
        config,
    )
    return panel, pages
```

`packages/tri-wellness/src/tri_wellness/labs/extract/exports.py`:
```python
"""Structured exports: deterministic parsers keyed by detected format, model fallback.

One format ships: `generic_csv`, a CSV with a name column and a value column. When Brian
provides a real Function Health export, add a parser keyed on its header next to it.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from tri_wellness.labs.extract.structured import extract_structured
from tri_wellness.labs.models import ExtractedPanel, RawResult
from tri_wellness.prompts.extract import render_extract_prompt

NAME_COLS = ("name", "marker", "test", "biomarker", "analyte", "test name")
VALUE_COLS = ("value", "result")
UNIT_COLS = ("unit", "units")
LOW_COLS = ("ref_low", "reference low", "low", "range low", "ref low")
HIGH_COLS = ("ref_high", "reference high", "high", "range high", "ref high")
FLAG_COLS = ("flag", "abnormal")
DATE_COLS = ("drawn_on", "collected", "collection date", "collection_date", "date")
LAB_COLS = ("lab", "lab_name", "laboratory")
MAX_FALLBACK_CHARS = 200_000


def _norm(h: str) -> str:
    return h.strip().lower()


def _col(header: list[str], candidates: tuple[str, ...]) -> str | None:
    by_norm = {_norm(h): h for h in header}
    return next((by_norm[c] for c in candidates if c in by_norm), None)


def _read_header(path: Path) -> list[str] | None:
    if path.suffix.lower() not in (".csv", ".tsv"):
        return None
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t" if path.suffix.lower() == ".tsv" else ",")
        return next(reader, None)


def detect_format(path: Path) -> str | None:
    header = _read_header(path)
    if header and _col(header, NAME_COLS) and _col(header, VALUE_COLS):
        return "generic_csv"
    return None


def _cell(row: dict[str, str], col: str | None) -> str | None:
    if col is None:
        return None
    v = row.get(col, "").strip()
    return v or None


def parse_generic_csv(text: str, delimiter: str = ",") -> ExtractedPanel:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = list(reader.fieldnames or [])
    name, value = _col(header, NAME_COLS), _col(header, VALUE_COLS)
    assert name is not None and value is not None
    unit, low, high = _col(header, UNIT_COLS), _col(header, LOW_COLS), _col(header, HIGH_COLS)
    flag, dcol, lcol = _col(header, FLAG_COLS), _col(header, DATE_COLS), _col(header, LAB_COLS)
    results: list[RawResult] = []
    drawn_on: date | None = None
    lab_name: str | None = None
    for row in reader:
        n, v = _cell(row, name), _cell(row, value)
        if not n or not v:
            continue
        results.append(
            RawResult(
                name=n,
                value=v,
                unit=_cell(row, unit),
                ref_low=_cell(row, low),
                ref_high=_cell(row, high),
                flag=_cell(row, flag),
            )
        )
        if drawn_on is None and (d := _cell(row, dcol)):
            try:
                drawn_on = date.fromisoformat(d[:10])
            except ValueError:
                drawn_on = None
        if lab_name is None:
            lab_name = _cell(row, lcol)
    return ExtractedPanel(drawn_on=drawn_on, lab_name=lab_name, results=results)


def parse_export(path: Path) -> ExtractedPanel | None:
    """Deterministic parse, or None when the layout is unknown (the caller falls back to the
    model)."""
    if detect_format(path) == "generic_csv":
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        return parse_generic_csv(path.read_text(encoding="utf-8-sig"), delimiter)
    return None


async def extract_export_with_model(
    model: BaseChatModel, path: Path, drawn_on_hint: date | None, config: RunnableConfig | None
) -> ExtractedPanel:
    body = path.read_text(encoding="utf-8-sig", errors="replace")[:MAX_FALLBACK_CHARS]
    return await extract_structured(
        model,
        render_extract_prompt("export", drawn_on_hint, body),
        None,
        ["source_kind:export", "page_count:0"],
        config,
    )
```

Also in `packages/tri-wellness/src/tri_wellness/ranges/markers.yaml` add `"mcg/dL": 1.0` to the `conversions` of `iron_serum`, `tibc` and `zinc`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest packages/tri-wellness -q`
Expected: all pass (Plan 1 plus 9 new). If `test_extract_pdf_sends_document_block_and_parses` fails because `model.received` is empty: `with_structured_output` on `ScriptedChatModel` routes through `bind_tools` (returns `self`) and then `_generate`, so the override must be on `_generate`, not `invoke`.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): PDF and export extraction with structured output"
```

---

### Task 3: Nodes and the graph

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py`, `nodes/normalize.py`, `nodes/review.py`, `nodes/store.py`, `graph/graph.py`
- Test: `packages/tri-wellness/tests/test_graph.py` (db-marked)

**Interfaces:**
- Consumes: Task 1 state and deps; Task 2 `extract_pdf`, `parse_export`, `extract_export_with_model`; Plan 1 `normalize`, `repo.insert_panel`, `repo.find_duplicate_panels`.
- Produces: `make_extract_node(deps)`, `make_normalize_node(deps)`, `make_review_node(deps)`, `make_store_node(deps)`; `blocking_rows(unmapped) -> list[Unmapped]`; `after_extract(state) -> str`, `after_review(state) -> str`; `build_ingest_graph(deps, checkpointer) -> CompiledGraph` (name `tri-wellness-ingest`). The review interrupt payload is `{"source_path", "drawn_on" (ISO or None), "lab_name", "results": [LabResult json], "unmapped": [Unmapped json], "context": PanelContext json or None (set after an edit that supplied one), "duplicates": [panel ids], "last_error"}`; resume is `Command(resume=IngestDecision json)`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_graph.py`:
```python
import uuid
from datetime import date
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness import repo
from tri_wellness.graph.graph import after_extract, after_review, build_ingest_graph
from tri_wellness.graph.nodes.review import blocking_rows
from tri_wellness.labs.models import RawResult, Unmapped
from tri_wellness.testing import load_extracted

pytestmark = pytest.mark.db
FIX = Path(__file__).parent / "fixtures"
CTX = {"fasting": True, "draw_time": "07:30:00", "supplements": ["vitamin d"], "symptoms": []}
APPROVE = Command(resume={"action": "approve", "context": CTX})


def cfg():
    return {"configurable": {"thread_id": f"ingest:test-{uuid.uuid4()}"}}


def pdf_input(tiny_pdf, **over):
    base = {"source_path": str(tiny_pdf), "source_kind": "pdf", "drawn_on_hint": None}
    base.update(over)
    return base


def scripted(name="pdf_panel", **over):
    fixture = {**load_extracted(name), **over}
    return ScriptedChatModel(script=[tool_call("ExtractedPanel", fixture)])


def test_routing_functions():
    assert after_extract({"last_error": "no rows"}) == "__end__"
    assert after_extract({"last_error": None, "raw_results": []}) == "normalize"
    assert after_review({"decision": "approve"}) == "store"
    assert after_review({"decision": "reject"}) == "__end__"
    assert after_review({"decision": None}) == "review"


def test_blocking_rows_are_unit_and_value_only():
    rows = [
        Unmapped(raw=RawResult(name="a", value="1"), reason="name"),
        Unmapped(raw=RawResult(name="b", value="1"), reason="unit", marker="ferritin"),
        Unmapped(raw=RawResult(name="c", value="x"), reason="value", marker="tsh"),
        Unmapped(raw=RawResult(name="d", value="1"), reason="duplicate", marker="tsh"),
    ]
    assert [u.raw.name for u in blocking_rows(rows)] == ["b", "c"]


async def test_pdf_ingest_pauses_at_review_with_nothing_stored(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert payload["drawn_on"] == "2026-08-20" and payload["lab_name"] == "Quest Diagnostics"
    assert [r["marker"] for r in payload["results"]] == [
        "ferritin", "iron_serum", "hs_crp", "glucose", "tsh"
    ]
    assert [(u["raw"]["name"], u["reason"]) for u in payload["unmapped"]] == [
        ("Sed Rate, Westergren", "name")
    ]
    assert payload["duplicates"] == [] and payload["last_error"] is None
    assert payload["context"] is None
    snap = await graph.aget_state(c)
    assert snap.next == ("review",)
    assert snap.values["page_count"] == 2 and snap.values["decision"] is None
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


async def test_approve_stores_one_panel_with_context_and_raw_extract(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(APPROVE, c)
    pid = out["panel_id"]
    assert isinstance(pid, int) and out["decision"] == "approve"
    panel = repo.get_panel(nocommit, pid)
    assert panel is not None
    assert (panel.drawn_on, panel.lab_name, panel.source_kind) == (date(2026, 8, 20), "Quest Diagnostics", "pdf")
    assert panel.source_file == str(tiny_pdf)
    assert panel.context.fasting is True and panel.context.supplements == ["vitamin d"]
    assert len(panel.raw_extract) == 6  # every extracted row, mapped or not
    assert [r.marker for r in repo.list_results(nocommit, pid)] == [
        "ferritin", "glucose", "hs_crp", "iron_serum", "tsh"
    ]
    assert (await graph.aget_state(c)).next == ()


async def test_reject_stores_nothing_and_ends(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(Command(resume={"action": "reject", "note": "wrong file"}), c)
    assert out["decision"] == "reject" and out.get("panel_id") is None
    assert (await graph.aget_state(c)).next == ()
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


async def test_approve_refused_until_unit_row_is_edited_away(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted("pdf_panel_bad_unit")), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    payload = out["__interrupt__"][0].value
    assert [(u["reason"], u["marker"]) for u in payload["unmapped"]] == [
        ("unit", "ferritin"), ("name", None)
    ]
    out = await graph.ainvoke(APPROVE, c)
    assert "__interrupt__" in out
    again = out["__interrupt__"][0].value
    assert "unit" in again["last_error"] and again["unmapped"] == payload["unmapped"]
    remaining = [u for u in payload["unmapped"] if u["reason"] == "name"]
    out = await graph.ainvoke(Command(resume={"action": "edit", "unmapped": remaining}), c)
    edited = out["__interrupt__"][0].value
    assert edited["last_error"] is None and [u["reason"] for u in edited["unmapped"]] == ["name"]
    out = await graph.ainvoke(APPROVE, c)
    assert out["panel_id"] is not None
    assert len(repo.get_panel(nocommit, out["panel_id"]).raw_extract) == 6


async def test_approve_without_context_is_refused(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    await graph.ainvoke(pdf_input(tiny_pdf), c)
    out = await graph.ainvoke(Command(resume={"action": "approve"}), c)
    assert "context" in out["__interrupt__"][0].value["last_error"]


async def test_edit_replaces_results_and_date(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted()), InMemorySaver())
    c = cfg()
    out = await graph.ainvoke(pdf_input(tiny_pdf), c)
    results = out["__interrupt__"][0].value["results"][:2]
    results[0]["value"] = 43.0
    out = await graph.ainvoke(
        Command(resume={"action": "edit", "results": results, "drawn_on": "2026-08-21"}), c
    )
    payload = out["__interrupt__"][0].value
    assert payload["drawn_on"] == "2026-08-21" and len(payload["results"]) == 2
    out = await graph.ainvoke(APPROVE, c)
    stored = repo.list_results(nocommit, out["panel_id"])
    assert [(r.marker, r.value) for r in stored] == [("ferritin", 43.0), ("iron_serum", 95.0)]
    assert repo.get_panel(nocommit, out["panel_id"]).drawn_on == date(2026, 8, 21)


async def test_extraction_with_no_rows_ends_before_review(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted(results=[])), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf), cfg())
    assert "__interrupt__" not in out and "no rows" in out["last_error"]


async def test_missing_draw_date_uses_hint_or_ends(nocommit, make_deps, tiny_pdf):
    graph = build_ingest_graph(make_deps(scripted(drawn_on=None)), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf), cfg())
    assert "__interrupt__" not in out and "draw date" in out["last_error"]
    graph = build_ingest_graph(make_deps(scripted(drawn_on=None)), InMemorySaver())
    out = await graph.ainvoke(pdf_input(tiny_pdf, drawn_on_hint=date(2026, 8, 22)), cfg())
    assert out["__interrupt__"][0].value["drawn_on"] == "2026-08-22"


async def test_export_path_is_deterministic_and_warns_on_duplicate(nocommit, make_deps):
    model = ScriptedChatModel(script=[])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    c = cfg()
    src = {"source_path": str(FIX / "exports" / "generic.csv"), "source_kind": "export"}
    out = await graph.ainvoke(src, c)
    payload = out["__interrupt__"][0].value
    assert model.calls == 0
    assert [r["marker"] for r in payload["results"]] == ["ferritin", "hs_crp", "glucose", "vitamin_d"]
    assert payload["lab_name"] == "Function Health"
    first = (await graph.ainvoke(APPROVE, c))["panel_id"]
    c2 = cfg()
    out = await graph.ainvoke(src, c2)
    assert out["__interrupt__"][0].value["duplicates"] == [first]
    second = (await graph.ainvoke(APPROVE, c2))["panel_id"]
    assert second != first  # a second panel, not a merge


async def test_second_graph_on_the_same_checkpointer_resumes_at_review(nocommit, make_deps, tiny_pdf):
    saver = InMemorySaver()
    c = cfg()
    await build_ingest_graph(make_deps(scripted()), saver).ainvoke(pdf_input(tiny_pdf), c)
    graph2 = build_ingest_graph(make_deps(ScriptedChatModel(script=[])), saver)
    assert (await graph2.aget_state(c)).next == ("review",)
    out = await graph2.ainvoke(APPROVE, c)
    assert out["panel_id"] is not None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_graph.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.graph.graph'`.

- [ ] **Step 3: Write the nodes**

`packages/tri-wellness/src/tri_wellness/graph/nodes/extract.py`:
```python
"""Extract node: file -> ExtractedPanel. Ends the run (last_error) when there is nothing to
review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.extract.exports import extract_export_with_model, parse_export
from tri_wellness.labs.extract.pdf import extract_pdf


def make_extract_node(deps: GraphDeps) -> Any:
    async def extract(state: IngestState, config: RunnableConfig) -> dict[str, Any]:
        path = Path(state["source_path"])
        hint = state.get("drawn_on_hint")
        pages: int | None = None
        if state["source_kind"] == "pdf":
            panel, pages = await extract_pdf(deps.model, path, hint, config)
        else:
            parsed = parse_export(path)
            panel = parsed or await extract_export_with_model(deps.model, path, hint, config)
        drawn_on = panel.drawn_on or hint
        error: str | None = None
        if not panel.results:
            error = f"extraction returned no rows for {path.name}"
        elif drawn_on is None:
            error = f"extraction found no draw date in {path.name}; rerun with --drawn-on"
        return {
            "raw_results": panel.results,
            "drawn_on": drawn_on,
            "lab_name": panel.lab_name,
            "page_count": pages,
            "results": [],
            "unmapped": [],
            "context": None,
            "decision": None,
            "panel_id": None,
            "last_error": error,
        }

    return extract
```

`packages/tri-wellness/src/tri_wellness/graph/nodes/normalize.py`:
```python
"""Normalize node: raw rows -> canonical results and the rows that need review. Pure."""

from __future__ import annotations

from typing import Any

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.normalize import normalize


def make_normalize_node(deps: GraphDeps) -> Any:
    def normalize_node(state: IngestState) -> dict[str, Any]:
        out = normalize(list(state.get("raw_results") or []), deps.registry)
        return {"results": out.results, "unmapped": out.unmapped}

    return normalize_node
```

`packages/tri-wellness/src/tri_wellness/graph/nodes/review.py`:
```python
"""Review node: pause until the athlete decides. Edit and a refused approve return with
`decision` None, which routes back here for another look at the (edited) table.

`interrupt(value)` stops the run with the value exposed as `__interrupt__`; on
`Command(resume=x)` the node runs again from the top and `interrupt()` returns x. The duplicate
lookup before it is a read, so replaying it is harmless.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from tri_wellness import repo
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState
from tri_wellness.labs.models import IngestDecision, Unmapped

BLOCKING_REASONS = frozenset({"unit", "value"})


def blocking_rows(unmapped: list[Unmapped]) -> list[Unmapped]:
    return [u for u in unmapped if u.reason in BLOCKING_REASONS]


def make_review_node(deps: GraphDeps) -> Any:
    def review(state: IngestState) -> dict[str, Any]:
        drawn_on = state.get("drawn_on")
        context = state.get("context")
        unmapped = list(state.get("unmapped") or [])
        duplicates: list[int] = []
        if drawn_on is not None:
            with deps.connect() as conn:
                duplicates = repo.find_duplicate_panels(conn, drawn_on, state.get("lab_name"))
        raw = interrupt(
            {
                "source_path": state["source_path"],
                "drawn_on": drawn_on.isoformat() if drawn_on else None,
                "lab_name": state.get("lab_name"),
                "results": [r.model_dump(mode="json") for r in state.get("results") or []],
                "unmapped": [u.model_dump(mode="json") for u in unmapped],
                "context": context.model_dump(mode="json") if context else None,
                "duplicates": duplicates,
                "last_error": state.get("last_error"),
            }
        )
        decision = IngestDecision.model_validate(raw)
        if decision.action == "reject":
            return {"decision": "reject", "last_error": None}
        if decision.action == "edit":
            update: dict[str, Any] = {"decision": None, "last_error": None}
            for field in ("results", "unmapped", "drawn_on", "lab_name", "context"):
                value = getattr(decision, field)
                if value is not None:
                    update[field] = value
            return update
        blocking = blocking_rows(unmapped)
        if blocking:
            names = ", ".join(u.raw.name for u in blocking)
            return {
                "decision": None,
                "last_error": f"{len(blocking)} row(s) need a unit or value fix before approve "
                f"(edit or remove): {names}",
            }
        if decision.context is None:
            return {"decision": None, "last_error": "approve needs the panel context"}
        if drawn_on is None:
            return {"decision": None, "last_error": "approve needs a draw date (edit drawn_on)"}
        return {"decision": "approve", "context": decision.context, "last_error": None}

    return review
```

`packages/tri-wellness/src/tri_wellness/graph/nodes/store.py`:
```python
"""Store node: one transaction, one panel, its result rows and the raw extract."""

from __future__ import annotations

from typing import Any

from tri_wellness import repo
from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.state import IngestState


def make_store_node(deps: GraphDeps) -> Any:
    def store(state: IngestState) -> dict[str, Any]:
        drawn_on, context = state.get("drawn_on"), state.get("context")
        assert drawn_on is not None and context is not None
        with deps.connect() as conn:
            panel_id = repo.insert_panel(
                conn,
                drawn_on=drawn_on,
                lab_name=state.get("lab_name"),
                source_file=state["source_path"],
                source_kind=state["source_kind"],
                context=context,
                raw_extract=list(state.get("raw_results") or []),
                results=list(state.get("results") or []),
            )
            conn.commit()
        return {"panel_id": panel_id, "last_error": None}

    return store
```

- [ ] **Step 4: Write the graph**

`packages/tri-wellness/src/tri_wellness/graph/graph.py`:
```python
"""The ingest graph.

START -> extract -> normalize -> review -> store -> END
                 └─(no rows / no date)─> END          review -> review (edit, refused approve)
                                                      review -> END (reject)
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from tri_wellness.graph.deps import GraphDeps
from tri_wellness.graph.nodes.extract import make_extract_node
from tri_wellness.graph.nodes.normalize import make_normalize_node
from tri_wellness.graph.nodes.review import make_review_node
from tri_wellness.graph.nodes.store import make_store_node
from tri_wellness.graph.state import IngestState


def after_extract(state: IngestState) -> str:
    return END if state.get("last_error") else "normalize"


def after_review(state: IngestState) -> str:
    decision = state.get("decision")
    if decision == "approve":
        return "store"
    if decision == "reject":
        return END
    return "review"


def build_ingest_graph(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any]) -> Any:
    g: StateGraph[IngestState] = StateGraph(IngestState)
    g.add_node("extract", make_extract_node(deps))
    g.add_node("normalize", make_normalize_node(deps))
    g.add_node("review", make_review_node(deps))
    g.add_node("store", make_store_node(deps))
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", after_extract, ["normalize", END])
    g.add_edge("normalize", "review")
    g.add_conditional_edges("review", after_review, ["store", "review", END])
    g.add_edge("store", END)
    return g.compile(checkpointer=checkpointer, name="tri-wellness-ingest")
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_graph.py -q`
Expected: 12 passed. Notes: `list_results` orders by marker, hence `ferritin, glucose, hs_crp, iron_serum, tsh` in the approve test while the interrupt payload keeps extraction order. In `test_approve_refused_until_unit_row_is_edited_away` the refused approve is a fresh super-step that interrupts again; `out` from `ainvoke` therefore carries `__interrupt__` and the new `last_error`.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): ingest graph with extract, normalize, review interrupt and store"
```

---

### Task 4: Review REPL (`repl.py`)

**Files:**
- Create: `packages/tri-wellness/src/tri_wellness/repl.py`
- Test: `packages/tri-wellness/tests/test_repl.py` (the `run_ingest` tests are db-marked)

**Interfaces:**
- Consumes: Task 3 graph and interrupt payload; `IngestDecision`, `PanelContext`, `LabResult`, `RawResult`, `Unmapped`; `MarkerRegistry`.
- Produces: `Out = Callable[[str], None]`, `Read = Callable[[], Awaitable[str | None]]`, `EditFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]`; `render_review(payload) -> str`; `parse_decision(line) -> tuple[str, str | None] | None` (`("approve" | "edit" | "reject" | "quit", note)`); `collect_context(read, out) -> PanelContext | None`; `review_to_yaml(payload) -> str`; `review_from_yaml(text, registry) -> dict[str, Any]` (keys `results`, `unmapped`, `drawn_on`, `lab_name`, `context`; raises `ValueError` naming rows); `review_dialogue(payload, read, out, edit) -> IngestDecision | None`; `run_turn(graph, payload, thread_id, out) -> TurnResult(interrupt, error)`; `run_ingest(graph, *, source_path, source_kind, drawn_on_hint, thread_id, read, out, edit) -> int` (0 stored, 1 error, 2 rejected, 3 paused). Plan 3 appends the chat loop to this module.

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_repl.py`:
```python
from datetime import date, time
from pathlib import Path

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver

from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness import repo
from tri_wellness.graph.graph import build_ingest_graph
from tri_wellness.labs.models import LabResult, PanelContext, RawResult, Unmapped
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.repl import (
    collect_context,
    parse_decision,
    render_review,
    review_dialogue,
    review_from_yaml,
    review_to_yaml,
    run_ingest,
)
from tri_wellness.testing import load_extracted


def lr(marker, value, unit, name=None, low=None, high=None, flag=None, note=None):
    return LabResult(
        marker=marker,
        value=value,
        unit=unit,
        raw=RawResult(name=name or marker, value=str(value), unit=unit, flag=flag),
        lab_ref_low=low,
        lab_ref_high=high,
        note=note,
    )


def payload(**over):
    base = {
        "source_path": "/labs/aug.pdf",
        "drawn_on": "2026-08-20",
        "lab_name": "Quest",
        "results": [
            lr("ferritin", 42.0, "ng/mL", "Ferritin, Serum", 30.0, 400.0).model_dump(mode="json"),
            lr("hs_crp", 0.3, "mg/L", "hs-CRP", None, 3.0, note="value '<0.3' stored as bound 0.3").model_dump(mode="json"),
        ],
        "unmapped": [
            Unmapped(raw=RawResult(name="Sed Rate", value="4", unit="mm/h"), reason="name").model_dump(mode="json"),
        ],
        "context": None,
        "duplicates": [],
        "last_error": None,
    }
    base.update(over)
    return base


def reads(lines):
    it = iter(lines)

    async def read():
        return next(it, None)

    return read


def test_render_review_table_unmapped_duplicates_and_error():
    text = render_review(payload(duplicates=[7], last_error="approve needs the panel context"))
    assert "/labs/aug.pdf" in text and "2026-08-20" in text and "Quest" in text
    assert "ferritin" in text and "42" in text and "ng/mL" in text and "30-400" in text
    assert "Ferritin, Serum" in text and "hs-CRP" in text and "-3" in text  # one-sided lab range
    assert "[name" in text and "Sed Rate" in text
    assert "panel(s) 7" in text and "approve needs the panel context" in text
    assert "2 results, 1 unmapped (0 blocking)" in text
    blocked = payload(unmapped=[{"raw": {"name": "Zinc", "value": "90", "unit": "furlongs", "ref_low": None, "ref_high": None, "flag": None, "page": None}, "reason": "unit", "marker": "zinc"}])
    assert "1 blocking" in render_review(blocked) and "-> zinc" in render_review(blocked)


def test_parse_decision():
    assert parse_decision("approve") == ("approve", None)
    assert parse_decision("  edit ") == ("edit", None)
    assert parse_decision("reject wrong file") == ("reject", "wrong file")
    assert parse_decision("reject") == ("reject", None)
    assert parse_decision("/quit") == ("quit", None) and parse_decision("quit") == ("quit", None)
    assert parse_decision("yes") is None


async def test_collect_context_prompts_and_parses():
    out = []
    ctx = await collect_context(reads(["y", "7:30", "iron, vitamin d", "", "fatigue", "slept badly"]), out.append)
    assert ctx == PanelContext(
        fasting=True,
        draw_time=time(7, 30),
        supplements=["iron", "vitamin d"],
        diet_pattern=None,
        symptoms=["fatigue"],
        notes="slept badly",
    )
    assert any("fasting" in s for s in out)


async def test_collect_context_reasks_bad_time_and_handles_eof():
    out = []
    ctx = await collect_context(reads(["n", "half seven", "07:30", "", "", "", ""]), out.append)
    assert ctx is not None and ctx.fasting is False and ctx.draw_time == time(7, 30)
    assert sum(s.startswith("draw time") for s in out) == 2 and "use HH:MM\n" in out
    assert await collect_context(reads(["y"]), out.append) is None


def test_yaml_round_trip_and_validation():
    reg = load_registry("male", MARKERS_PATH)
    text = review_to_yaml(payload())
    assert "marker: ferritin" in text and "raw_name: Ferritin, Serum" in text and "reason: name" in text
    back = review_from_yaml(text, reg)
    assert [r.model_dump(mode="json") for r in back["results"]] == payload()["results"]
    assert [u.model_dump(mode="json") for u in back["unmapped"]] == payload()["unmapped"]
    assert back["drawn_on"] == date(2026, 8, 20) and back["lab_name"] == "Quest"
    assert back["context"] == PanelContext()  # the empty template counts as no edit
    # an unmapped row moved into results with a marker, value and the canonical unit
    doc = yaml.safe_load(text)
    row = doc["unmapped"].pop()
    doc["results"].insert(
        0,
        {"marker": "uric_acid", "value": 5.1, "unit": "mg/dL", "raw_name": row["name"], "raw_value": row["value"]},
    )
    fixed = review_from_yaml(yaml.safe_dump(doc), reg)
    assert fixed["unmapped"] == [] and fixed["results"][0].marker == "uric_acid"
    assert fixed["results"][0].raw.name == "Sed Rate" and fixed["results"][0].raw.value == "4"
    with pytest.raises(ValueError, match=r"results\[0\].*marker"):
        review_from_yaml(text.replace("marker: ferritin", "marker: ferritine"), reg)
    with pytest.raises(ValueError, match=r"results\[0\].*unit"):
        review_from_yaml(text.replace("unit: ng/mL", "unit: ug/L", 1), reg)
    with pytest.raises(ValueError, match=r"results\[1\].*value"):
        review_from_yaml(text.replace("value: 0.3", "value: abc"), reg)
    with pytest.raises(ValueError, match="drawn_on"):
        review_from_yaml(text.replace("2026-08-20", "yesterday"), reg)


async def test_review_dialogue_paths():
    out = []
    # approve is blocked while a unit row remains
    blocked = payload(unmapped=[{"raw": {"name": "Zinc", "value": "90", "unit": "furlongs", "ref_low": None, "ref_high": None, "flag": None, "page": None}, "reason": "unit", "marker": "zinc"}])
    d = await review_dialogue(blocked, reads(["approve", "reject bad units"]), out.append, None)
    assert d is not None and d.action == "reject" and d.note == "bad units"
    assert any("need a unit or value fix" in s for s in out)
    # approve collects the context
    d = await review_dialogue(payload(), reads(["approve", "y", "07:30", "", "", "", ""]), out.append, None)
    assert d is not None and d.action == "approve" and d.context is not None and d.context.fasting is True
    # approve reuses a context that came back from an edit
    ctx = PanelContext(fasting=False).model_dump(mode="json")
    d = await review_dialogue(payload(context=ctx), reads(["approve"]), out.append, None)
    assert d is not None and d.context is not None and d.context.fasting is False
    # unknown word re-prompts; quit returns None
    assert await review_dialogue(payload(), reads(["what", "/quit"]), out.append, None) is None
    # edit calls the editor and returns its fields
    async def edit(p):
        return {"drawn_on": date(2026, 8, 21), "results": [], "unmapped": [], "lab_name": None, "context": PanelContext()}

    d = await review_dialogue(payload(), reads(["edit"]), out.append, edit)
    assert d is not None and d.action == "edit" and d.drawn_on == date(2026, 8, 21) and d.results == []
    # a cancelled edit re-prompts
    async def cancel(p):
        return None

    d = await review_dialogue(payload(), reads(["edit", "reject"]), out.append, cancel)
    assert d is not None and d.action == "reject" and any("edit cancelled" in s for s in out)
    # no editor available
    d = await review_dialogue(payload(), reads(["edit", "reject"]), out.append, None)
    assert any("not available" in s for s in out)


@pytest.mark.db
async def test_run_ingest_end_to_end(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", load_extracted("pdf_panel"))])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    kw = dict(source_path=str(tiny_pdf), source_kind="pdf", drawn_on_hint=None, thread_id="ingest:abc", out=out.append, edit=None)
    code = await run_ingest(graph, read=reads(["approve", "y", "07:30", "", "", "", ""]), **kw)
    assert code == 0 and any("stored panel" in s for s in out)
    pid = int(next(s for s in out if "stored panel" in s).split()[-1])
    assert repo.get_panel(nocommit, pid) is not None
    # rerunning the same thread does not re-extract or re-store
    code = await run_ingest(graph, read=reads([]), **kw)
    assert code == 0 and model.calls == 1 and any("already stored" in s for s in out)


@pytest.mark.db
async def test_run_ingest_pause_and_resume_then_reject(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", load_extracted("pdf_panel"))])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    kw = dict(source_path=str(tiny_pdf), source_kind="pdf", drawn_on_hint=None, thread_id="ingest:def", out=out.append, edit=None)
    assert await run_ingest(graph, read=reads(["/quit"]), **kw) == 3
    assert await run_ingest(graph, read=reads(["reject nope"]), **kw) == 2
    assert model.calls == 1 and any("resuming" in s for s in out)
    assert repo.find_duplicate_panels(nocommit, date(2026, 8, 20), "Quest Diagnostics") == []


@pytest.mark.db
async def test_run_ingest_reports_extraction_failure(nocommit, make_deps, tiny_pdf):
    model = ScriptedChatModel(script=[tool_call("ExtractedPanel", {"results": []})])
    graph = build_ingest_graph(make_deps(model), InMemorySaver())
    out = []
    code = await run_ingest(graph, source_path=str(tiny_pdf), source_kind="pdf", drawn_on_hint=None, thread_id="ingest:ghi", read=reads([]), out=out.append, edit=None)
    assert code == 1 and any("no rows" in s for s in out)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_repl.py -q`
Expected: `ModuleNotFoundError: No module named 'tri_wellness.repl'`.

- [ ] **Step 3: Write the REPL**

`packages/tri-wellness/src/tri_wellness/repl.py`:
```python
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

from tri_wellness.labs.models import IngestDecision, LabResult, PanelContext, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry

Out = Callable[[str], None]
Read = Callable[[], Awaitable[str | None]]
EditFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]

REVIEW_PROMPT = "approve / edit / reject <note> / quit"
BLOCKING_REASONS = ("unit", "value")


def _rng(low: Any, high: Any) -> str:
    if low is None and high is None:
        return ""
    fmt = lambda v: "" if v is None else f"{float(v):g}"  # noqa: E731
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
    doc = yaml.safe_load(text) or {}
    problems: list[str] = []
    results: list[LabResult] = []
    for i, row in enumerate(doc.get("results") or []):
        marker = str(row.get("marker") or "")
        if marker not in registry.markers:
            problems.append(f"results[{i}]: unknown marker '{marker}'")
            continue
        spec = registry.get(marker)
        if row.get("unit") != spec.unit:
            problems.append(f"results[{i}] ({marker}): unit must be {spec.unit}, got {row.get('unit')}")
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
        context = PanelContext.model_validate(doc.get("context") or {})
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
        if payload.get("context"):
            out("using the context from your edit\n")
            return IngestDecision(
                action="approve", context=PanelContext.model_validate(payload["context"])
            )
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest packages/tri-wellness/tests/test_repl.py -q`
Expected: 10 passed. If `test_yaml_round_trip_and_validation` fails on the `results` equality: `yaml.safe_dump` writes `42.0` as `42.0` and `float()` reads it back; `raw.value` for ferritin is `"42.0"` in both because `lr()` stringifies the float. If `test_run_ingest_end_to_end` cannot find the panel id line, the `store` update is printed by `run_turn` as `stored panel <id>`; check the node name is `store`.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): review REPL: table, context prompts, YAML edit, ingest runner"
```

---

### Task 5: `tri-wellness ingest`, the Postgres resume test, the live PDF test

**Files:**
- Modify: `packages/tri-wellness/src/tri_wellness/cli.py`, `.env.example`
- Test: `packages/tri-wellness/tests/test_cli.py`, append to `tests/test_checkpointer.py`, create `tests/test_live_pdf.py`

**Interfaces:**
- Consumes: Task 4 `run_ingest`, `review_to_yaml`, `review_from_yaml`; Task 2 `sniff`, `file_sha256`; Task 1 plumbing.
- Produces: `tri-wellness ingest <file> [--kind pdf|export] [--drawn-on YYYY-MM-DD]` with exit codes 0/1/2/3 from `run_ingest`, 2 for a usage or setup problem; `edit_in_editor(payload) -> dict | None` (writes `review_to_yaml`, opens `$EDITOR`, parses with `review_from_yaml`, prints validation errors and returns `None` so the dialogue re-prompts).

- [ ] **Step 1: Write the failing tests**

`packages/tri-wellness/tests/test_cli.py`:
```python
from typer.testing import CliRunner

from tri_wellness.cli import app

runner = CliRunner()


def test_help_lists_ingest():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "ingest" in result.output


def test_ingest_unknown_extension_needs_kind(tmp_path):
    f = tmp_path / "panel.txt"
    f.write_text("x")
    result = runner.invoke(app, ["ingest", str(f)])
    assert result.exit_code == 2 and "--kind" in result.output


def test_ingest_missing_file_is_a_usage_error(tmp_path):
    result = runner.invoke(app, ["ingest", str(tmp_path / "nope.pdf")])
    assert result.exit_code == 2


def test_ingest_bad_drawn_on(tmp_path, tiny_pdf):
    result = runner.invoke(app, ["ingest", str(tiny_pdf), "--drawn-on", "yesterday"])
    assert result.exit_code == 2 and "YYYY-MM-DD" in result.output
```

Append to `packages/tri-wellness/tests/test_checkpointer.py`:
```python


import uuid

import pytest
from langgraph.types import Command

from tri_core.config import Settings
from tri_core.testing import ScriptedChatModel, tool_call
from tri_wellness.graph.checkpointer import checkpointer_ready, open_checkpointer
from tri_wellness.graph.graph import build_ingest_graph
from tri_wellness.testing import load_extracted


@pytest.mark.db
async def test_second_process_resumes_the_ingest_thread_from_postgres(nocommit, make_deps, tiny_pdf):
    url = Settings().test_database_url
    if not checkpointer_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"ingest:test-{uuid.uuid4()}"}}
    src = {"source_path": str(tiny_pdf), "source_kind": "pdf", "drawn_on_hint": None}
    script = [tool_call("ExtractedPanel", load_extracted("pdf_panel"))]
    try:
        async with open_checkpointer(url) as saver:
            graph = build_ingest_graph(make_deps(ScriptedChatModel(script=script)), saver)
            out = await graph.ainvoke(src, thread)
            assert "__interrupt__" in out
        async with open_checkpointer(url) as saver2:
            graph2 = build_ingest_graph(make_deps(ScriptedChatModel(script=[])), saver2)
            snap = await graph2.aget_state(thread)
            assert snap.next == ("review",)
            assert snap.tasks[0].interrupts[0].value["lab_name"] == "Quest Diagnostics"
            out = await graph2.ainvoke(
                Command(resume={"action": "approve", "context": {"fasting": True}}), thread
            )
            assert out["panel_id"] is not None  # written through the rolled-back connection
    finally:
        async with open_checkpointer(url) as saver3:
            await saver3.adelete_thread(thread["configurable"]["thread_id"])
```
(Move the imports to the top of the file; ruff will insist.)

`packages/tri-wellness/tests/test_live_pdf.py`:
```python
"""Real PDF extraction against one redacted panel Brian provides (spec §15, §19 item 1).
Opt-in: `uv run pytest --live packages/tri-wellness/tests/test_live_pdf.py -s`
with TRI_WELLNESS_LIVE_PDF=<path> and, optionally, TRI_WELLNESS_LIVE_ROWS=<expected row count>
and TRI_WELLNESS_LIVE_DRAWN_ON=<YYYY-MM-DD> in .env."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tri_wellness.config import WellnessSettings
from tri_wellness.graph.llm import make_model
from tri_wellness.labs.extract.pdf import extract_pdf
from tri_wellness.labs.normalize import normalize
from tri_wellness.ranges.registry import load_registry

pytestmark = pytest.mark.live


async def test_live_pdf_extraction():
    load_dotenv()
    path = os.environ.get("TRI_WELLNESS_LIVE_PDF")
    if not path:
        pytest.skip("set TRI_WELLNESS_LIVE_PDF to a redacted lab PDF")
    settings = WellnessSettings()
    panel, pages = await extract_pdf(make_model(settings), Path(path), None, None)
    print(f"\n{pages} pages, {len(panel.results)} rows, drawn {panel.drawn_on}, lab {panel.lab_name}")
    assert panel.results and panel.drawn_on is not None
    expected_rows = os.environ.get("TRI_WELLNESS_LIVE_ROWS")
    if expected_rows:
        assert len(panel.results) == int(expected_rows)
    expected_date = os.environ.get("TRI_WELLNESS_LIVE_DRAWN_ON")
    if expected_date:
        assert panel.drawn_on == date.fromisoformat(expected_date)
    out = normalize(panel.results, load_registry(settings.tri_athlete_sex))
    print(f"{len(out.results)} mapped; unmapped: {[(u.raw.name, u.reason) for u in out.unmapped]}")
    by_page = sorted({r.page for r in panel.results if r.page is not None})
    print(f"rows on pages {by_page}")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-wellness/tests/test_cli.py -q`
Expected: `test_help_lists_ingest` fails (no `ingest` command); the others exit with `No such command`.

- [ ] **Step 3: Write the command**

Replace `packages/tri-wellness/src/tri_wellness/cli.py` with:
```python
"""Command-line entry points for the wellness agent: ingest (report, chat, panels arrive in
Plan 3)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from pydantic import ValidationError
from rich.console import Console

from tri_wellness.config import get_wellness_settings

load_dotenv()
# The agents share one .env; give this one its own LangSmith project before LangChain loads.
os.environ["LANGSMITH_PROJECT"] = os.environ.get(
    "TRI_WELLNESS_LANGSMITH_PROJECT", "tri_wellness"
)

app = typer.Typer(help="Functional-medicine lab interpreter", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    """Functional-medicine lab interpreter."""


def _out(s: str) -> None:
    console.print(s, end="", markup=False, highlight=False, soft_wrap=True)


async def _read() -> str | None:
    try:
        return await asyncio.to_thread(console.input, "[bold cyan]review>[/] ")
    except EOFError:
        return None


def make_editor(registry: Any) -> Any:
    """`$EDITOR` over the review document. Returns the parsed fields, or None (with the errors
    printed) so the dialogue re-prompts."""
    from tri_wellness.repl import review_from_yaml, review_to_yaml

    async def edit_in_editor(payload: dict[str, Any]) -> dict[str, Any] | None:
        editor = os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(review_to_yaml(payload))
            path = f.name
        try:
            await asyncio.to_thread(subprocess.call, [editor, path])
            with open(path, encoding="utf-8") as fh:
                return review_from_yaml(fh.read(), registry)
        except ValueError as exc:
            _out(f"edited YAML is not valid:\n{exc}\n")
            return None
        finally:
            os.unlink(path)

    return edit_in_editor


@app.command()
def ingest(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    kind: str | None = typer.Option(None, "--kind", help="pdf or export; sniffed from the extension"),
    drawn_on: str | None = typer.Option(
        None, "--drawn-on", help="Draw date YYYY-MM-DD when the file does not print one"
    ),
) -> None:
    """Extract a lab panel, review it, store it. Rerunning the same file resumes at review."""
    raise typer.Exit(code=asyncio.run(_ingest(file, kind, drawn_on)))


async def _ingest(file: Path, kind: str | None, drawn_on: str | None) -> int:
    from tri_wellness.graph.checkpointer import SETUP_HINT, checkpointer_ready, open_checkpointer
    from tri_wellness.graph.deps import make_deps
    from tri_wellness.graph.graph import build_ingest_graph
    from tri_wellness.graph.llm import make_model
    from tri_wellness.labs.extract import file_sha256, sniff
    from tri_wellness.repl import run_ingest

    if kind not in (None, "pdf", "export"):
        console.print("--kind must be pdf or export", style="red")
        return 2
    try:
        source_kind = sniff(file, kind)  # type: ignore[arg-type]
    except ValueError as exc:
        console.print(str(exc), style="red")
        return 2
    hint: date | None = None
    if drawn_on is not None:
        try:
            hint = date.fromisoformat(drawn_on)
        except ValueError:
            console.print("--drawn-on must be YYYY-MM-DD", style="red")
            return 2
    try:
        settings = get_wellness_settings()
    except ValidationError:
        console.print("TRI_ATHLETE_SEX must be set to male or female in .env", style="red")
        return 2
    if not settings.anthropic_api_key:
        console.print("ANTHROPIC_API_KEY is not set in .env", style="red")
        return 2
    if not checkpointer_ready(settings.database_url):
        console.print(SETUP_HINT, style="red")
        return 2
    thread_id = f"ingest:{file_sha256(file)}"
    async with open_checkpointer(settings.database_url) as saver:
        deps = make_deps(settings, make_model(settings))
        graph = build_ingest_graph(deps, saver)
        return await run_ingest(
            graph,
            source_path=str(file.resolve()),
            source_kind=source_kind,
            drawn_on_hint=hint,
            thread_id=thread_id,
            read=_read,
            out=_out,
            edit=make_editor(deps.registry),
        )


if __name__ == "__main__":
    app()
```

`.env.example`: append under the tri-wellness block:
```
TRI_WELLNESS_LIVE_PDF=
TRI_WELLNESS_LIVE_ROWS=
TRI_WELLNESS_LIVE_DRAWN_ON=
```

- [ ] **Step 4: Run the tests, then the live test with a real panel (Brian)**

```bash
uv run pytest packages/tri-wellness -q
```
Expected: all pass; the Postgres resume test skips until `scripts/setup_checkpointer.py` has run against `tri_analyze_test` (it has, for planning), the live test skips without `--live`.

Brian drops a redacted panel PDF somewhere outside the repo, sets `TRI_WELLNESS_LIVE_PDF` in `.env`, then:
```bash
uv run pytest --live packages/tri-wellness/tests/test_live_pdf.py -s
```
Record in the README (Task 6) what it printed: pages, rows, whether every page contributed rows (spec §19 item 1: one call or a per-page pass), and the unmapped names (each is an alias to add to `markers.yaml`).

Then the first real ingest:
```bash
uv run tri-wellness ingest ~/labs/2026-08-20-quest.pdf
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff format packages/tri-wellness && uv run ruff check . && uv run mypy
git add -A
git commit -m "feat(wellness): ingest command with checkpointed review; live PDF test"
```

---

### Task 6: README, root README, docs sync

**Files:**
- Modify: `packages/tri-wellness/README.md`, `README.md`

- [ ] **Step 1: Package README**

Replace the `## After Plan 1` heading with `## After Plan 2` and append after the Plan 1 bullets:
```markdown
- `labs/extract/`: `sniff` picks pdf or export; PDFs go to the model as a document block and
  come back as an `ExtractedPanel` (verbatim rows, draw date, lab name); exports with a
  recognisable header (`generic_csv`) are parsed without a model call, anything else falls back
  to the model with the file text in the prompt.
- `graph/`: `extract -> normalize -> review -> store`, checkpointed in Postgres under
  `ingest:<sha256 of the file>`. The review interrupt shows the canonical table, the unmapped
  rows with a reason, and a duplicate-panel warning; `approve` collects the panel context
  (fasting, draw time, supplements, diet, symptoms, notes); `edit` opens the document in
  `$EDITOR` as YAML and re-validates; `reject` ends with nothing stored. Approve is refused
  while a row still has an unknown unit or a non-numeric value.
- `tri-wellness ingest <file> [--kind pdf|export] [--drawn-on YYYY-MM-DD]`: exit 0 stored, 1
  extraction or API error, 2 rejected, 3 paused (rerun to resume).

Unmapped names are fixed by adding an alias to `ranges/markers.yaml`, then rerunning the same
command: the thread resumes at review, so extraction is not repeated. Re-normalising after an
alias change needs a `reject` and a fresh run (or an `edit` that moves the row by hand).

Live check (needs a redacted panel and `TRI_WELLNESS_LIVE_PDF` in `.env`):
`uv run pytest --live packages/tri-wellness/tests/test_live_pdf.py -s`. Findings from the first
run: _fill in pages, rows per page, unmapped names, and whether one call returned every row_.
```
Replace the italic placeholder with the actual numbers from Task 5 step 4 before committing; if the live run has not happened yet, write "not run yet (no panel provided)" instead.

- [ ] **Step 2: Root README**

In the Run block add:
```
uv run tri-wellness ingest <file.pdf|csv> [--kind pdf|export] [--drawn-on YYYY-MM-DD]   # extract, review, store a lab panel
```
In the Layout block change the tri-wellness line to `packages/tri-wellness/  src/tri_wellness/{config,cli,repo,repl,testing,ranges,labs,graph,prompts}`.

Under Status add: `- tri-wellness milestone 2 (2026-09): PDF and export ingest with a checkpointed review; first real panel stored.`

- [ ] **Step 3: Copy docs to the vault and commit**

```bash
V=/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent
mkdir -p $V/packages/tri-wellness $V/docs/superpowers/plans
cp packages/tri-wellness/README.md $V/packages/tri-wellness/readme.md
cp README.md $V/readme.md
cp docs/superpowers/plans/2026-09-11-tri-wellness-02-ingest.md $V/docs/superpowers/plans/
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
git add -A
git commit -m "docs(wellness): plan 2 READMEs and live extraction findings"
```

---

## Layout after this plan

```
packages/tri-wellness/src/tri_wellness/
  cli.py                       ingest; make_editor()
  repl.py                      render_review, parse_decision, collect_context, review_to_yaml,
                               review_from_yaml, review_dialogue, run_turn, run_ingest
  labs/extract/{__init__,structured,pdf,exports}.py
  prompts/extract.py
  graph/{state,deps,llm,checkpointer,graph}.py, graph/nodes/{extract,normalize,review,store}.py
  testing.py                   + NoCommit, RecordingScriptedModel, load_extracted
tests/fixtures/extract/{pdf_panel,pdf_panel_bad_unit}.json, tests/fixtures/exports/{generic,unknown}.csv
```

Signatures Plan 3 calls: `make_model(settings)` and `MAX_TOKENS` from `graph/llm.py`; `run_turn`'s error handling pattern and `Out`/`Read` from `repl.py`; `checkpointer_ready` is not needed by report, chat or panels (spec §13).

## Self-review notes

- Spec §9 thread id, checkpointer reuse, state (with the listed additions), the four nodes and every edge including `extract -> END` on no rows or no date; §9.2 extract paths (export deterministic, unknown export to the model, PDF as a file block), the prompt's verbatim rule, page and row counts logged (`run_turn`) and traced (tags); normalize as Plan 1's pure function; review payload, table, unmapped rows, duplicate warning, context prompts, approve/edit/reject with `$EDITOR` YAML and re-validation; store in one transaction printing the panel id.
- Spec §12 `ingest` signature; §13 every row of the error table: no rows / no date (Task 3), unmapped kept only in `raw_extract` (store passes `raw_results`), unit unknown refuses approve (node and REPL), duplicate warns and stores a second panel (test), ranges file invalid (Plan 1), API errors caught per command with the thread resuming on rerun (`run_turn`, `run_ingest`), checkpointer unavailable refuses to start (`_ingest`), invalid YAML re-prompts (`make_editor` returns None).
- Spec §15: extraction fixture per source kind (`pdf_panel.json`; the export parser against `generic.csv`), graph tests with `ScriptedChatModel` for pause, approve, reject and a second process resuming (InMemorySaver shared, and Postgres in `test_checkpointer.py`), the YAML edit round trip, the live opt-in test asserting row count and draw date.
- Spec §16 extraction tags `source_kind` and `page_count`.
- Spec §19 items 1 and 2 are answered by the live run and the first real export; both are recorded in the README, not decided here.
- Type consistency: `IngestDecision` fields match what `review_dialogue` builds and `make_review_node` reads; `run_ingest` keyword names match `_ingest`; `review_from_yaml`'s returned keys are exactly `IngestDecision`'s edit fields; `load_extracted` and `RecordingScriptedModel` are used with the same spellings in Tasks 2, 3 and 4.
