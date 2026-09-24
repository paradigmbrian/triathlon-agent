# Guardrails: Python-owned TSS, validate-then-refuse, a consult budget, one held-review rule, private sub-graphs

**Date:** 2026-09-24
**Status:** Draft
**Purpose:** Move the limits that today live in prompt prose into code: the arithmetic a model cannot do reliably, the validation that today proposes anyway, the consult budget nothing enforces, the four different answers to "a review is waiting", and the embedded graphs that write to Postgres while claiming to be private. Third of five specs; assumes the correctness fixes and the data layer are in. Line numbers are `main` @ 6540055.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| TSS owner | Python computes `tss_planned` from duration and intensity; the model returns sessions without it and the week is scaled to the target (chosen 2026-09-24). | The prompt asks the model to make numbers sum within 10%; the retry loop exists because it cannot. A 30-min "vo2" at 200 TSS passes today. |
| Violations | A week or plan that still fails validation after one retry is not proposed. It is stored with its violations, the summary says so, and the athlete can ask again (chosen 2026-09-24). | Proposing a known-bad week and relying on the athlete to notice is the bug the `--yes` gate papered over. |
| Consult budget | A counter in coach state; the consult tool returns an error tool message past the limit. | `max_consults` reaches only the prompt today; the only stop is the recursion limit. |
| Held reviews | Block until answered, everywhere: a paused review refuses a new turn in the REPL, the web route and cron (chosen 2026-09-24). | Four implementations disagree today; the web one loses the change set. |
| Embedded graphs | Compiled with `checkpointer=False`. | LangGraph prefers the config's checkpointer over a compiled saver, so the private savers never run. |

## 2. Feasibility, verified 2026-09-24

- `PlannedSession` (`tri_planning/planning/models.py:61-72`) has `tss_planned: float` with no description; `DESIGN_SYSTEM` (`prompts/design.py:21-33`) carries the only intensity-to-IF table (0.65 recovery, 0.70 endurance, 0.80 tempo, 0.90 threshold, 1.0 vo2/race) and the "sum within 10%" rule; `validate.week` (`planning/validate.py:40-74`) checks the sum, not per-session TSS, and never checks `weekly_hours_min`. `design_week` (`graph/nodes/design.py:35-63`) retries once and returns `(week, violations)`; the node (`:104-130`) persists and proposes regardless. `PHASE_IF` (`planning/periodization.py:56-64`) is keyed by phase and used only for target hours. tri-planning has no `PROMPT_VERSION`.
- `FuelPlanner.session` and `.race` (`tri_nutrition/graph/nodes/fuel.py:79-119`) retry once and return `(plan, violations)`; the node (`:150-191`) stores and proposes regardless.
- `CoachState` (`tri_coach/graph/state.py:23-33`) has no consult counter; `_consult` (`tools/handoff.py:23-38`) takes `messages` via `InjectedState`; `max_consults` appears only in `COACH_RULES` (`prompts/coach.py:29-31`) and `CoachDeps`.
- Held-review detection: planning `route_start` (`tri_planning/graph/graph.py:34-38`) routes to review on `pending_changes`; nutrition the same (`tri_nutrition/graph/graph.py:42-49`); the coach has no `route_start`; `tri_coach.repl.paused_review` (`repl.py:306-313`) is reused by coach check-in and tri-web's `thread.py:99-111`; `tri_web/routes/coach.py:42-46` `post_turn` checks nothing; nutrition `checkin_run` (`repl.py:221-243`) approves a review it did not produce under `--yes` (the fixes spec changes that); planning `checkin.py:28-43` refuses.
- `build_graph` in tri-coach (`graph/graph.py:68-99`) compiles the embedded graphs with `InMemorySaver(serde=...)`; planning and nutrition `build_graph` take `checkpointer: BaseCheckpointSaver[Any]` positionally. LangGraph `_defaults` (`pregel/main.py:2579-2593`) takes `self.checkpointer is False` before the config's `CONFIG_KEY_CHECKPOINTER`; `compile(checkpointer=False)` "will not use or inherit any checkpointer" (`graph/state.py:1195-1202`).

## 3. Planning: Python-owned TSS

### 3.1 Schema

```python
class DesignedSession(BaseModel):        # what the model returns
    date: date
    sport: Sport
    title: str
    description: str
    duration_minutes: int = Field(ge=0)
    intensity: Intensity
    structure: dict[str, Any] | None = None

class DesignedWeek(BaseModel):
    week_start: date
    sessions: list[DesignedSession]
    coach_note: str
```

`PlannedSession` and `PlannedWeek` keep `tss_planned`; they are what is stored, proposed and written. `planning/tss.py`:

```python
INTENSITY_IF: dict[Intensity, float] = {"recovery": 0.65, "endurance": 0.70, "tempo": 0.80, "threshold": 0.90, "vo2": 1.0, "race": 1.0}

def session_tss(duration_minutes: int, intensity: Intensity) -> float   # hours * IF^2 * 100
def scale_to_target(week: DesignedWeek, target: WeekTarget, goal: TrainingGoal) -> tuple[PlannedWeek, list[str]]
```

`scale_to_target` computes each session's TSS, sums, and when the total is outside 10% of `target.target_tss` scales every non-race session's duration by `target / total`, clamped to `[0.75, 1.25]` and rounded to 5 minutes, then recomputes. Structures scale with their session (step durations by the same factor). A remaining gap after clamping is a violation `total TSS <n> cannot reach target <t> by scaling`; the model then gets the retry with that message, which asks for more or fewer sessions, not different numbers.

### 3.2 Prompt and validator

`DESIGN_SYSTEM` drops the TSS estimate paragraph and the "sum within 10%" rule and states instead: target hours, the phase, and that intensity drives load ("the planner computes load from duration and intensity; choose durations that fit the hours target"). `PROMPT_VERSION = "2"` is added to `prompts/design.py`; `tri-planning eval` names experiments `design-v2` and `render_pass_rates` shows the version.

`validate.week` keeps days, sports, rest and brick rules, consecutive hard days, structure sums, hours max, and adds hours min (`target_hours * 0.8` unless the week is recovery, taper or race) and a per-session sanity rule: no session over 6 hours, no `vo2` session over 90 minutes. The TSS sum rule stays as the post-scaling check.

`design_week` returns `(PlannedWeek, violations)` as today, built from `scale_to_target`. `design_eval.design_target` returns the scaled week; `validator_pass` is unchanged.

## 4. Validate-then-refuse

### 4.1 Planning

`make_design_node`: a week whose violations survive the retry is stored via `set_week_designed` with `designed = null` and `violations` in a new `plan_weeks.violations jsonb` column (migration 008), is not in `pending_changes`, and the summary line reads `week <start>: not designed: <violations>`. When no week is designed the node returns no `pending_changes` and the turn ends with that summary as the coach note. `design_next_week` returns `{"week_start", "violations", "changes": []}` for such a week, and the adjust agent's prompt tells it to report the violations and, if the athlete's message suggests a fix, call `design_next_week` again with a note.

### 4.2 Nutrition

The fuel node stores every plan with its violations as today, but only plans with no violations reach `changes`. `pending_summary` gains a line per skipped session: `<day> <title>: not proposed: <violations>`. The race plan is treated the same. The check-in `--yes` gate from the fixes spec then has nothing to skip; it stays as a second layer.

## 5. Consult budget

`CoachState` gains `consults: dict[str, int]` (domain to count), reset to `{}` in `start_node`. `_consult` takes `consults: Annotated[dict[str, int], InjectedState("consults")]` and `max_consults` from a closure over `CoachDeps` (`make_handoff_tools(max_consults)`); when `consults.get(domain, 0) >= max_consults` it returns a plain `ToolMessage` (no handoff): `consult budget for <domain> is spent this turn (<n> of <n>); explain what you have and stop, or ask the athlete`. The planning and nutrition nodes increment the count in their state update. The context block shows `consults left: planning 2, nutrition 2`. `COACH_RULES` keeps the sentence, now describing what the tool does.

## 6. One held-review rule

`tri_core.harness.turns.paused_review(snap)` moves out of `tri_coach.repl` and is the only definition: a snapshot whose `next` is `("review",)` with an interrupt on its first task. Every host uses it:

| Host | Behaviour when paused |
|---|---|
| REPL (coach, planning, nutrition) | The loop enters the review dialogue before reading a message; already true for the coach, made true for planning and nutrition. |
| `check-in` (planning, nutrition, coach) | Exit 3 with the review printed; `--yes` approves only a review the same run produced. |
| tri-web `POST /api/coach/turns` | 409 `{"reason": "paused"}`; the composer is disabled while `paused` is set. |
| Graph routing | Planning and nutrition `route_start` keep routing to review on `pending_changes`; the fixes spec's P1 ensures a rejected set is cleared. The coach's `pending` (a partial apply's remainder) is not a paused review: it is shown in context and re-proposed by the coach, so a new turn is allowed. |

## 7. Private sub-graphs

`build_planning_graph(deps, checkpointer: BaseCheckpointSaver[Any] | Literal[False], *, embedded=False)` and the nutrition equivalent accept `False`; tri-coach `build_graph` passes `False` for both. The `make_serde(...)` calls and the two `InMemorySaver` imports in tri-coach go. `docs/architecture/harness.md` and the routing diagram's caption change from "throwaway InMemorySaver" to "no checkpointer; the parent graph owns the messages".

## 8. Errors

- A design that fails scaling twice ends the turn with the violations in the note; nothing is written.
- A consult past the budget is a tool message, not an exception; the coach's next step is its own answer.
- A paused review blocks a turn with a 409 or a printed review, never by dropping the interrupt.

## 9. Testing

- `tri-planning/tests/test_tss.py`: `session_tss` values; `scale_to_target` scales durations and structures, clamps, rounds, reports the unreachable case.
- `test_validate.py`: hours min, the sanity rules, week_start mismatch (fixes P9).
- `test_design_node.py`: a still-invalid week is stored with `designed = null` and `violations`, not proposed; the summary names it.
- `tri-nutrition/tests/test_fuel_node.py`: a violating plan is stored, not proposed, and named in the summary.
- `tri-coach/tests/test_handoff.py`: the third consult of a domain returns the budget message and makes no handoff; `test_graph.py`: `consults` resets each turn and the context block shows the remaining counts.
- `tri-core/tests/test_turns.py`: `paused_review` on a paused, a held and an idle snapshot.
- `tri-planning` and `tri-nutrition` `test_repl.py`: the chat loop enters the review dialogue on a paused snapshot.
- `tri-web/tests/test_routes_coach.py`: a turn during a paused review is 409 and the review survives.
- `tri-coach/tests/test_graph.py`: after a consult, `checkpointer.list(config)` on the parent saver holds no `planning:` or `nutrition:` namespaces.
- Evals: `tri-planning eval` as `design-v2` after merge (Brian), compared with `design-base-6d37af94` (74% over 23).

## 10. Out of scope

- Per-sport TSS splits and long-session progression in `WeekTarget`.
- Re-baselining targets from live CTL at check-in.
- A graph path that lets a message during a paused review become a question about the proposal.

## 11. Rollout

Two plans. Plan 01: Python-owned TSS, validate-then-refuse in planning and nutrition, migration 008 (`plan_weeks.violations`), `PROMPT_VERSION` for planning. Plan 02: consult budget, `paused_review` in the harness and the four hosts, `checkpointer=False`, docs.
