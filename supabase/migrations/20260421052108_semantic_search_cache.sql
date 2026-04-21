create table if not exists public.semantic_search_cache (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    query_hash text not null,
    query_text text not null,
    result_tmdb_ids integer[] not null,
    reasoning_map jsonb not null default '{}',
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default now() + interval '24 hours'
);

create unique index if not exists idx_semantic_cache_user_query
    on public.semantic_search_cache(user_id, query_hash);

create index if not exists idx_semantic_cache_expires
    on public.semantic_search_cache(expires_at);
