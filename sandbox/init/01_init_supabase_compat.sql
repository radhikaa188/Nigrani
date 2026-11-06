-- 01_init_supabase_compat.sql
-- Sets up roles, schemas, and helper functions mimicking Supabase's environment for PostgREST

-- 1. Create PostgREST / Supabase standard roles
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
    CREATE ROLE authenticator NOINHERIT LOGIN PASSWORD 'authenticator_password'; -- pragma: allowlist secret
  END IF;
END $$;

-- Allow authenticator to switch to anon and authenticated roles
GRANT anon TO authenticator;
GRANT authenticated TO authenticator;

-- 2. Grants for public schema
GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL ROUTINES IN SCHEMA public TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON ROUTINES TO anon, authenticated;

-- 3. Create auth schema and Supabase auth helper functions
CREATE SCHEMA IF NOT EXISTS auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated;

-- auth.uid() function replicating Supabase auth.uid()
-- Safely extracts 'sub' claim as UUID; returns NULL if not present or invalid
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  sub_val text;
BEGIN
  sub_val := COALESCE(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  );
  IF sub_val IS NULL THEN
    RETURN NULL;
  END IF;
  BEGIN
    RETURN sub_val::uuid;
  EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
  END;
END;
$$;

-- auth.role() function replicating Supabase auth.role()
CREATE OR REPLACE FUNCTION auth.role()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )::text;
$$;

-- auth.jwt() function replicating Supabase auth.jwt()
CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT nullif(current_setting('request.jwt.claims', true), '')::jsonb;
$$;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA auth TO anon, authenticated;
