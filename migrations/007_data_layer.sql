-- 007_data_layer.sql  (apply to tri_analyze and tri_analyze_test)
-- Data layer, 2026-09-24 spec: tombstones for workouts removed from TrainingPeaks, every Garmin
-- activity kept (a brick has two), and a status on every recorded external write.

alter table workouts add column if not exists deleted_at timestamptz;
create index if not exists workouts_live_date_idx on workouts (workout_date) where deleted_at is null;

create table if not exists garmin_activities (
  id                text primary key,
  tp_workout_id     text references workouts on delete set null,
  sport             text not null,
  type_key          text,
  start_time_local  timestamp not null,
  duration_sec      numeric,
  distance_m        numeric,
  avg_hr            int,
  name              text,
  raw               jsonb not null,
  synced_at         timestamptz not null default now()
);
create index if not exists garmin_activities_workout_idx on garmin_activities (tp_workout_id);
create index if not exists garmin_activities_day_idx on garmin_activities ((start_time_local::date));

-- One row per activity already matched; the next Garmin sync fills the rest inside its window.
-- A brick's one matched activity has an unknown sport ('other') until that sync rewrites it.
insert into garmin_activities (id, tp_workout_id, sport, start_time_local, raw)
select garmin_activity_id, tp_workout_id, case when sport = 'brick' then 'other' else sport end,
       coalesce(start_time_local, workout_date::timestamp), '{}'::jsonb
from workouts
where garmin_activity_id is not null
on conflict (id) do nothing;

-- Existing rows were written after a successful call: they are 'applied'.
alter table plan_changes add column if not exists status text not null default 'applied';
alter table plan_changes add column if not exists error text;
alter table nutrition_changes add column if not exists status text not null default 'applied';
alter table nutrition_changes add column if not exists error text;
