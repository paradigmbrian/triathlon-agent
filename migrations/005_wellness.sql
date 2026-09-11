-- 005_wellness.sql  (apply to tri_analyze and tri_analyze_test)

create table if not exists lab_panels (
  id            serial primary key,
  drawn_on      date not null,
  lab_name      text,                  -- Quest, LabCorp, Function Health, ...
  source_file   text,                  -- path as given at ingest
  source_kind   text not null,         -- pdf | export | manual
  context       jsonb not null,        -- PanelContext
  raw_extract   jsonb not null,        -- list[RawResult] exactly as extraction returned them
  created_at    timestamptz not null default now()
);
create index if not exists lab_panels_drawn_on_idx on lab_panels (drawn_on);

create table if not exists lab_results (
  panel_id      int not null references lab_panels,
  marker        text not null,         -- canonical key from markers.yaml
  value         numeric not null,      -- canonical unit
  unit          text not null,
  raw_name      text not null,         -- what the lab printed
  raw_value     text not null,         -- verbatim, including "<5"
  raw_unit      text,
  lab_ref_low   numeric,
  lab_ref_high  numeric,
  flag          text,                  -- lab's own H / L, if printed
  primary key (panel_id, marker)
);
create index if not exists lab_results_marker_idx on lab_results (marker);

create table if not exists lab_reports (
  id             serial primary key,
  panel_id       int not null references lab_panels,
  ranges_version text not null,        -- markers.yaml version used
  findings       jsonb not null,       -- list[Finding], what the report was written from
  report_md      text not null,
  created_at     timestamptz not null default now()
);
