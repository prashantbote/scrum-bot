-- Runs once on first container start (as the owner/superuser "scrum").
-- The application connects as scrum_app: not a table owner and no BYPASSRLS (plan §4.2).
CREATE EXTENSION IF NOT EXISTS vector;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'scrum_app') THEN
    CREATE ROLE scrum_app LOGIN PASSWORD 'scrum_app' NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE scrum TO scrum_app;
GRANT USAGE ON SCHEMA public TO scrum_app;
CREATE DATABASE scrum_test OWNER scrum;
\c scrum_test
CREATE EXTENSION IF NOT EXISTS vector;
GRANT USAGE ON SCHEMA public TO scrum_app;
