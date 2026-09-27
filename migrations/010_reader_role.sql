-- 010_reader_role.sql
-- tri_reader: the login the agents' query_training_db tool uses (tri_core.config.readonly_url).
-- SELECT only, read-only transactions by default, a 5 s statement timeout, and no
-- pg_signal_backend, so it cannot cancel or terminate another role's backend. Roles are
-- cluster-wide, so the second database skips the create; grants are per database. Default
-- privileges give SELECT on every table the migrating role creates later, so later migrations
-- need nothing extra.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'tri_reader') then
    create role tri_reader login password 'tri_reader' nosuperuser nocreatedb nocreaterole noinherit;
  end if;
end $$;

revoke all on schema public from tri_reader;
grant usage on schema public to tri_reader;
grant select on all tables in schema public to tri_reader;
alter default privileges in schema public grant select on tables to tri_reader;
alter role tri_reader set default_transaction_read_only = on;
alter role tri_reader set statement_timeout = '5s';
