# Project instructions

## Eval runs

Every `tri-* eval` run and every `pytest --live` spends real Anthropic credit: about $1 per full
eval run (docs/notes/2026-09-28-anthropic-api-usage-audit.md).

- A spec or plan that calls for eval runs lists each one as its exact command, with the case
  count and an estimated $. Take the estimate from `usage.total_cost` in the latest full run's
  `.evals/` file for that eval (a name without `-subset` or `-rescore`: those cost a fraction of a
  full run), or write "no baseline".
- Pick the cheapest run that answers the question: `--rescore <file>` for a judge-only change,
  then `--cases` / `--failed-from <file>` while iterating. A full run is only for the gate that
  decides a change.
- Ask Brian before starting any `tri-* eval` run or `pytest --live`, even when a plan, spec or
  handoff note lists it, and give the estimate when asking.
