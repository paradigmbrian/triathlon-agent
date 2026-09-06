-- 001_initial.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists athlete_profile (
  id              int primary key default 1 check (id = 1),
  tp_athlete_id   text,
  ftp_watts       int,
  run_threshold_pace_sec_per_km  int,
  swim_css_sec_per_100m          int,
  lthr_bpm        int,
  max_hr_bpm      int,
  hr_zones        jsonb,
  power_zones     jsonb,
  pace_zones      jsonb,
  weight_kg       numeric(5,2),
  raw             jsonb not null,
  updated_at      timestamptz not null default now()
);

create table if not exists workouts (
  tp_workout_id       text primary key,
  workout_date        date not null,
  sport               text not null,
  sport_raw           text,
  title               text,
  description         text,
  completed           boolean not null default false,
  planned_duration_sec  int,
  planned_distance_m    numeric,
  planned_tss           numeric,
  planned_if            numeric,
  actual_duration_sec   int,
  actual_distance_m     numeric,
  actual_tss            numeric,
  actual_if             numeric,
  normalized_power    int,
  avg_power           int,
  avg_hr              int,
  avg_cadence         numeric,
  elevation_gain_m    numeric,
  calories            int,
  feeling             int,
  rpe                 int,
  comments            jsonb,
  structure           jsonb,
  garmin_activity_id  text unique,
  start_time_local    timestamp,
  raw                 jsonb not null,
  synced_at           timestamptz not null default now()
);
create index if not exists workouts_date_idx on workouts (workout_date);
create index if not exists workouts_sport_date_idx on workouts (sport, workout_date);

create table if not exists daily_metrics (
  metric_date       date primary key,
  sleep_seconds     int,
  sleep_score       int,
  hrv_overnight_avg int,
  resting_hr        int,
  body_battery_high int,
  body_battery_low  int,
  stress_avg        int,
  training_readiness int,
  garmin_raw        jsonb,
  ctl               numeric,
  atl               numeric,
  tsb               numeric,
  tss_day           numeric,
  tp_raw            jsonb,
  synced_at         timestamptz not null default now()
);

create table if not exists sync_state (
  source            text primary key,
  last_synced_date  date not null,
  last_run_at       timestamptz not null,
  last_status       text not null,
  last_error        text
);
