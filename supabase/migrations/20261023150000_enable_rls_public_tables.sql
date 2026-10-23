-- Enable row-level security on every public table that lacks it.
-- The backend connects via DATABASE_URL as the `postgres` role (BYPASSRLS) and uses
-- the Supabase client for auth only, so it is unaffected. With RLS on and no policies,
-- the anon/authenticated roles used by the public PostgREST API get no access.
-- Idempotent: safe to re-run; also covers tables added by future migrations if re-applied.
DO $$
DECLARE
  t record;
BEGIN
  FOR t IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND NOT c.relrowsecurity
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t.relname);
  END LOOP;
END
$$;
