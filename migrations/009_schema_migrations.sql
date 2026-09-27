-- 009_schema_migrations.sql
-- The record `tri migrate` keeps: one row per applied migrations/ file, with the sha256 of its
-- bytes. `tri migrate` creates this table itself before anything else
-- (tri_core.db.migrate.TRACKING_DDL), so this file is a no-op there; it keeps the table in the
-- numbered history.

create table if not exists schema_migrations (
  version     int primary key,
  name        text not null,
  sha256      text not null,
  applied_at  timestamptz not null default now()
);
