-- 02_test_user_notes.sql
-- Default test table for RLS verification in PostgREST sandbox

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.custom_accounts (
    account_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_email TEXT UNIQUE NOT NULL,
    pass_hash TEXT NOT NULL, -- pragma: allowlist secret
    is_admin_flag BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

GRANT ALL ON TABLE public.custom_accounts TO anon, authenticated;

CREATE TABLE IF NOT EXISTS public.test_user_notes (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE public.test_user_notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS p_user_notes_all ON public.test_user_notes;
CREATE POLICY p_user_notes_all
ON public.test_user_notes
FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

GRANT ALL ON TABLE public.test_user_notes TO authenticated;
GRANT ALL ON SEQUENCE public.test_user_notes_id_seq TO authenticated;
