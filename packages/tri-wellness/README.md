# tri-wellness

The lab interpreter: ingests the athlete's lab work from PDFs and structured exports, evaluates
every marker against the curated functional-medicine ranges in
`src/tri_wellness/ranges/markers.yaml`, and writes an interpretation grounded in the training,
sleep and recovery data tri-core syncs to Postgres. Design:
`docs/superpowers/specs/2026-09-10-tri-wellness-design.md`. Plans:
`docs/superpowers/plans/2026-09-11-tri-wellness-0*.md`.

## After Plan 2

Pure layer, no model, no commands yet:

- `ranges/markers.yaml`: 65 markers with conventional and functional ranges, aliases, unit
  conversions, athlete notes and sources. `ranges/registry.py` loads it for the configured
  `TRI_ATHLETE_SEX`, validates every rule, and builds the alias index. A bad entry fails the
  test suite naming the marker and field.
- `labs/models.py`: `RawResult` (what a lab printed), `LabResult` (canonical marker, unit and
  value), `PanelContext`, `TrainingContext`, `Finding`.
- `labs/normalize.py`: raw rows to `LabResult`s; unmapped names, unknown units, non-numeric
  values and duplicates are returned with a reason instead of being guessed.
- `labs/evaluate.py`: `Finding`s with conventional and functional status, the previous value,
  and the confounders that apply. Every threshold is a constant at the top of the module.
- `labs/training_context.py`: load, sessions, sleep and HRV around the draw date.
- `repo.py`: `lab_panels`, `lab_results`, `lab_reports` (`migrations/005_wellness.sql`).

Try the registry and evaluate without a database:

```bash
uv run python -c "
from datetime import date, time
from tri_wellness.ranges.registry import load_registry
from tri_wellness.labs.models import RawResult, PanelContext, TrainingContext
from tri_wellness.labs.normalize import normalize
from tri_wellness.labs.evaluate import evaluate
reg = load_registry('male')
rows = [RawResult(name='Ferritin, Serum', value='42', unit='ng/mL', ref_low='30', ref_high='400'),
        RawResult(name='hs-CRP', value='<0.3', unit='mg/L', ref_high='3.0'),
        RawResult(name='Glucose', value='5.2', unit='mmol/L'),
        RawResult(name='Sed Rate', value='4', unit='mm/hr')]
n = normalize(rows, reg)
print('unmapped:', [(u.raw.name, u.reason) for u in n.unmapped])
ctx = PanelContext(fasting=True, draw_time=time(7, 30))
tr = TrainingContext(drawn_on=date.today(), last_sessions=[{'date': '', 'sport': 'bike', 'duration_min': 180, 'tss': 200, 'title': 'long'}])
for f in evaluate(n.results, reg, {}, ctx, tr):
    print(f.display, f.value, f.unit, f.conventional_status, f.functional_status, f.functional_range, f.active_confounders)
"
```

Extract, normalize, review, store:

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
run: not run yet (no panel provided).
