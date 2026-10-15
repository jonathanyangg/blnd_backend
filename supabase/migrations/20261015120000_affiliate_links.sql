-- Cached TMDB /watch/providers payloads. Movie and TV ids overlap, so
-- media_type is part of the key. `results` is the country map TMDB returns.
create table watch_provider_cache (
    media_type text not null check (media_type in ('movie', 'tv')),
    tmdb_id int not null,
    results jsonb not null,
    fetched_at timestamptz not null default now(),
    primary key (media_type, tmdb_id)
);

-- One row per outbound affiliate click. `provider` is the TMDB watch-provider id.
create table affiliate_clicks (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    media_type text not null check (media_type in ('movie', 'tv')),
    tmdb_id int not null,
    provider int not null,
    created_at timestamptz not null default now()
);

create index affiliate_clicks_user_id_created_at_idx
    on affiliate_clicks (user_id, created_at desc);

alter table affiliate_clicks enable row level security;

create policy affiliate_clicks_select_own
    on affiliate_clicks for select
    to authenticated
    using (auth.uid() = user_id);

create policy affiliate_clicks_insert_own
    on affiliate_clicks for insert
    to authenticated
    with check (auth.uid() = user_id);
