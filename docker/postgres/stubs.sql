-- Enough of Supabase's auth/storage catalogs for the public migrations to apply.
create schema if not exists auth;
create schema if not exists storage;

create table if not exists auth.users (
    id uuid primary key,
    instance_id uuid,
    aud text,
    role text,
    email text,
    created_at timestamptz,
    updated_at timestamptz
);

create or replace function auth.uid()
returns uuid
language sql
stable
as $$ select null::uuid $$;

create table if not exists storage.objects (
    id uuid primary key default gen_random_uuid(),
    name text,
    bucket_id text
);

create or replace function storage.foldername(name text)
returns text[]
language sql
immutable
as $$ select string_to_array(name, '/') $$;
