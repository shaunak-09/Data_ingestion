-- One-time-per-deploy bootstrap: give the Function App's Managed Identity a login role
-- inside PostgreSQL, plus read/write access to the students schema.
--
-- This is NOT an application migration. `apply_pending_migrations` (src/persist.py) only
-- globs files directly under db/, so this file is never picked up as one, and it touches two
-- databases (postgres, then students) which a migration never should.
--
-- Must run as the Postgres Entra AD admin — the identity set as postgres_entra_admin_object_id
-- / postgres_entra_admin_principal_name in infra/variables.tf. Safe to re-run: every step is
-- guarded, so repeating it changes nothing.
--
--   psql "host=<postgres_fqdn> dbname=postgres user=<entra_admin_upn> sslmode=require" \
--        -v identity="<function_app_identity_name>" \
--        -f db/bootstrap/grant_function_role.sql

\connect postgres

SELECT pgaadauth_create_principal(:'identity', false, false)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'identity');

\connect students

-- Least privilege: the pipeline only reads and upserts. It must not be able to DELETE or
-- TRUNCATE student data, so those privileges are withheld deliberately.
GRANT USAGE ON SCHEMA public TO :"identity";
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO :"identity";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"identity";

-- Covers tables/sequences created by migrations applied after this grant runs, so a new
-- db/NNN_*.sql file never needs a matching manual grant.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO :"identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO :"identity";
