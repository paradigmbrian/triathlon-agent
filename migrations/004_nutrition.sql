-- 004_nutrition.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists nutrition_targets (
  day               date primary key,
  day_type          text not null,        -- rest | easy | moderate | hard | long | race | carb_load
  session_kcal      int not null,
  total_kcal        int not null,
  carbs_g           int not null,
  protein_g         int not null,
  fat_g             int not null,
  fluid_baseline_ml int not null,
  goal_adjust_kcal  int not null default 0,   -- negative deficit, positive surplus
  notes             jsonb not null default '[]',
  plan_phase        text,                 -- copied from plan_weeks.phase when a plan exists
  source            text not null,        -- plan | tp_calendar | profile_hours
  written_to_garmin boolean not null default false,
  generated_at      timestamptz not null default now()
);

create table if not exists fuel_plans (
  id            serial primary key,
  kind          text not null,            -- session | race
  day           date not null,
  tp_workout_id text,                     -- session plans
  tp_note_id    text,                     -- race plans, once written
  payload       jsonb not null,           -- SessionFuel or RaceFuelPlan
  violations    jsonb not null default '[]',
  written       boolean not null default false,
  generated_at  timestamptz not null default now()
);
create unique index if not exists fuel_plans_kind_day_workout_idx
  on fuel_plans (kind, day, coalesce(tp_workout_id, ''));

create table if not exists nutrition_changes (
  id            serial primary key,
  thread_id     text not null,
  operation     text not null,            -- set_day_targets | set_session_note | set_race_note
  target_key    text not null,            -- the date, workout id or note id
  payload       jsonb not null,           -- exactly what we sent
  result        jsonb,                    -- exactly what the server returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index if not exists nutrition_changes_op_key_idx on nutrition_changes (operation, target_key);
