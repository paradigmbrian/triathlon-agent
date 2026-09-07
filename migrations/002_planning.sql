-- 002_planning.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists training_goals (
  id                serial primary key,
  goal_type         text not null,      -- sprint | olympic | half_ironman | ironman | maintenance | build | recovery
  event_name        text,
  event_date        date,               -- null for maintenance/build/recovery
  duration_weeks    int,                -- set for goals without an event
  tp_event_id       text,               -- set if we created the race event in TP
  priority          text,               -- A | B | C
  weekly_hours_min  numeric,
  weekly_hours_max  numeric,
  available_days    jsonb not null,     -- {"mon": ["swim"], "tue": ["bike","run"], "sat": "any", "sun": []}
  constraints       jsonb,              -- list of strings from intake
  tp_plan_id        text,               -- bought TrainingPeaks plan to activate instead of generating
  create_tp_event   boolean not null default false,
  status            text not null default 'active',   -- active | completed | abandoned
  created_at        timestamptz not null default now()
);

create table if not exists training_plans (
  id            serial primary key,
  goal_id       int not null references training_goals,
  source        text not null,          -- generated | tp_plan
  tp_plan_id    text,
  start_date    date not null,
  end_date      date not null,
  skeleton      jsonb not null,         -- [WeekTarget as JSON]
  status        text not null default 'active',   -- active | superseded | completed
  created_at    timestamptz not null default now()
);

create table if not exists plan_weeks (
  plan_id       int not null references training_plans,
  week_start    date not null,          -- Monday
  phase         text not null,          -- base | build | peak | taper | race | recovery
  target_tss    numeric,
  target_hours  numeric,
  designed      jsonb,                  -- validated PlannedWeek; null outside the rolling window
  written_to_tp boolean not null default false,
  primary key (plan_id, week_start)
);

create table if not exists plan_changes (
  id            serial primary key,
  plan_id       int references training_plans,
  thread_id     text not null,
  operation     text not null,          -- create | update | delete | move | apply_plan | create_event
  tp_workout_id text,
  workout_date  date,
  payload       jsonb not null,         -- exactly what we sent
  result        jsonb,                  -- exactly what TP returned
  reason        text,
  applied_at    timestamptz not null default now()
);
create index if not exists plan_changes_workout_idx on plan_changes (tp_workout_id);
