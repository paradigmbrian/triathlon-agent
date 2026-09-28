# tri-coach

[Architecture index](README.md) · [Package README](../../packages/tri-coach/README.md) · [Harness](harness.md)

The orchestrator. On each turn the coach node rebuilds its agent with a fresh prompt. The agent then replies, consults a domain graph, asks a read-only agent, or proposes changes for review. The thread (`"coach"`) checkpoints to Postgres after every step, so a paused review survives a restart.

![tri-coach graph](diagrams/tri-coach.svg)

- **start** clears the per-turn keys, including the consult counts. `pending` (the held change set) survives.
- **coach** runs on `Role.COACH` with prompt v4: `COACH_RULES`, then the context (thresholds, plan, nutrition, labs, the last 7 days, consults left, pending changes), then memory. It makes one tool call per step.
- **consult_planning / consult_nutrition** hand off through `handoff()` to the embedded graph, which runs with no checkpointer and starts fresh each time. The node returns a `Proposal` and counts the consult. After two consults in one domain in a turn, the tool returns an error message instead of handing off.
- **propose_changes** names proposal ids and hands off to **review**, which pauses with `interrupt()`. Review refuses unknown ids, empty ids and proposals with no changes. A reject goes back to the coach and resets the consult budget.
- **apply** runs planning first, then nutrition, through each package's `apply_changes`. Every write goes through `recorded_write` into `plan_changes` or `nutrition_changes`. Whatever a partial apply could not write is held as `held-planning` or `held-nutrition` in `pending`. If sessions moved and nutrition targets exist in the horizon, nutrition runs once more to regenerate them.

## Tools

| Tool | What it does |
|---|---|
| `ask_analyst` | Runs the tri-analyze agent on a throwaway thread (recursion limit 40). Read-only. |
| `ask_wellness` | Runs the tri-wellness chat agent. Bound only when `TRI_ATHLETE_SEX` is set. Read-only. |
| `consult_planning`, `consult_nutrition` | Hand off to the embedded graph; count toward the budget. |
| `propose_changes` | Hands off to review with the proposal ids to approve. |
| `remember`, `forget` | Memory in the Store at `("athlete", "coach")`. A `checkin` entry expires after 14 days. |

Write tools are bound only to `ToolsCaller`, never to a model.

## Check-in

`tri-coach check-in` runs `tri sync`, then one coach turn with the check-in request. It refuses (exit 3) when a review is paused, a held set exists or the thread is stuck, and exits 2 with no plan or profile. `--yes` approves at most two gates, the second only for the nutrition follow-on, and edits out any change the validator flagged.

## Evals

13 routing cases, each one coach turn with stub tools. The code checks are `routing_accuracy` and `no_unrequested_adjustment`; the `brief_quality` judge runs on `Role.JUDGE`.
