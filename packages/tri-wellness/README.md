# tri-wellness

The lab interpreter: ingests the athlete's lab work from PDFs and structured exports, evaluates
every marker against the curated functional-medicine ranges in `src/tri_wellness/ranges/markers.yaml`,
and writes an interpretation grounded in the training, sleep and recovery data tri-core syncs to
Postgres. Design: `docs/superpowers/specs/2026-09-10-tri-wellness-design.md`.
Plans: `docs/superpowers/plans/2026-09-11-tri-wellness-0*.md`.
