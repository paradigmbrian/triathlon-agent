-- 006_fixes.sql  (apply to tri_analyze and tri_analyze_test)
-- Correctness fixes, 2026-09-24: bounded lab values, panel file sha, fuel plans keyed by title
-- for id-less sessions, and the bought-plan adoption stamp.

alter table lab_results add column if not exists bound text;             -- '<', '<=', '>', '>='
alter table lab_panels add column if not exists source_sha text;          -- sha256 of the ingested file
create index if not exists lab_panels_source_sha_idx on lab_panels (source_sha);

drop index if exists fuel_plans_kind_day_workout_idx;
create unique index if not exists fuel_plans_kind_day_workout_title_idx
  on fuel_plans (kind, day, coalesce(tp_workout_id, ''), coalesce((payload->>'title'), ''));

alter table training_goals add column if not exists tp_plan_applied_at timestamptz;
