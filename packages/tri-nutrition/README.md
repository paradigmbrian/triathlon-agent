# tri-nutrition

The nutrition agent: interviews the athlete about diet, restrictions and physique goals, derives
periodized daily calorie and macro targets and per-session fueling plans from the training plan,
writes them to Garmin Connect and TrainingPeaks after approval, and checks in against logged
intake and body composition. Design: `docs/superpowers/specs/2026-09-10-tri-nutrition-design.md`.
Plans: `docs/superpowers/plans/2026-09-10-tri-nutrition-0*.md`.

## Layout so far

- `nutrition/models.py`: profile, product, session, day target, session fuel, race plan, change.
- `nutrition/constants.py`: every tunable number (formulas, macro table, deficit sizes, bounds).
- `nutrition/energy.py`: `rmr`, `session_kcal`, `day_type`. Pure.
- `nutrition/targets.py`: `build(profile, sessions, ctx, today, horizon_days)` -> one `DayTarget`
  per day. Pure.
- `nutrition/bounds.py`: `validate_targets`, `validate_fuel`, `validate_race` -> violations. Pure.
- `repo.py`: the three nutrition tables (`migrations/004_nutrition.sql`).

Try the targets builder without a database:

```bash
uv run python -c "
from datetime import date, timedelta
from tri_nutrition.nutrition.models import NutritionProfile, PlanContext, Session
from tri_nutrition.nutrition.targets import build
from tri_nutrition.nutrition.bounds import validate_targets
p = NutritionProfile(height_cm=180, weight_kg=80, body_fat_pct=15, sex='m', age=40, goal='lose',
    target_weight_kg=76, pattern='omnivore', meals_per_day=3, cooks=True, tracks_food=True,
    scale_days_per_week=3, unit_preference='metric')
today = date.today()
s = [Session(day=today+timedelta(days=1), sport='bike', duration_min=90, intensity='endurance', planned_tss=80),
     Session(day=today+timedelta(days=3), sport='run', duration_min=50, intensity='threshold'),
     Session(day=today+timedelta(days=5), sport='bike', duration_min=180, intensity='endurance', planned_tss=170)]
ts = build(p, s, PlanContext(source='plan', ftp_watts=250), today, 7)
for t in ts:
    print(t.day, f'{t.day_type:9}', t.session_kcal, t.total_kcal, f'{t.carbs_g}/{t.protein_g}/{t.fat_g}', t.notes)
print(validate_targets(ts, p) or 'within bounds')
"
```
