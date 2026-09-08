# tri-planning

The planning agent: establishes a training goal, builds a periodized plan, writes sessions to
the TrainingPeaks calendar after approval, and adjusts the plan as training unfolds.
Design: `docs/superpowers/specs/2026-09-07-tri-planning-design.md`. Plans:
`docs/superpowers/plans/2026-09-07-tri-planning-0*.md`.

## Layout so far

- `planning/models.py`: goal, week target, session, week, calendar change.
- `planning/periodization.py`: every tunable number (phase table, ramp, recovery, taper, IF).
- `planning/targets.py`: `build(goal, fitness, start)` -> week targets. Pure.
- `planning/validate.py`: `week(planned, target, goal)` -> violations. Pure.
- `repo.py`: the four planning tables (`migrations/002_planning.sql`).

Try the targets without a database:

```bash
uv run python -c "
from datetime import date
from tri_planning.planning.models import TrainingGoal, FitnessSnapshot
from tri_planning.planning.targets import build, next_monday
g = TrainingGoal(goal_type='olympic', event_date=date(2026,12,13), weekly_hours_min=6,
                 weekly_hours_max=10, available_days={d:'any' for d in ('mon','tue','wed','thu','fri','sat','sun')})
for w in build(g, FitnessSnapshot(ctl=45), next_monday(date.today())):
    print(w.week_start, w.phase, w.target_tss, w.target_hours, 'R' if w.is_recovery else '', w.flags)
"
```
