# tri-wellness

[Architecture index](README.md) · [Package README](../../packages/tri-wellness/README.md)

Three separate flows around blood work: a checkpointed ingest graph with a human review, a streamed report that interprets findings against recent training, and a read-only chat agent the coach reaches through `ask_wellness`.

![tri-wellness](diagrams/tri-wellness.svg)

- **Ingest.** `extract` first tries a deterministic CSV or TSV parse. When that finds nothing, or the file is a PDF, it makes one `structured()` call on `LAB_EXTRACT`. `normalize` is code: it maps aliases, converts units and flags unmapped rows against the marker registry. `review` pauses with `interrupt()` for approve, edit or reject. `store` writes `lab_panels` and `lab_results` in one transaction.
- **Report.** It reads the panel, previous values and the training context (72 hours of sessions, load, and sleep and HRV against a 30-day baseline). `evaluate` turns these into findings in code. Report prompt v2 adds the prior report's priorities. `streaming()` on `LAB_REPORT` writes the report to `lab_reports` with a disclaimer.
- **Chat.** An agent loop on `WELLNESS_CHAT` with a static prompt, `query_training_db` as `tri_reader`, and `get_panel_findings`, `get_marker_spec` and `get_marker_history`.
- **Registry.** `ranges/markers.yaml` holds the markers, their aliases and their ranges, resolved for the athlete's sex.

Review refuses an approve when the file's sha256 was already ingested, an unmapped row has a blocking reason, or the panel context or draw date is missing.

## Evals

Four report cases with no database. The checks are code only: `cites_functional_ranges`, `has_required_sections` and `names_active_confounders`.
