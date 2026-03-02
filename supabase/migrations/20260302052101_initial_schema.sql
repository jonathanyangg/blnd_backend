-- Enable pgvector
create extension if not exists vector;

-- ============================================================
-- PROFILES (extends auth.users)
-- ============================================================
create table profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    username text unique not null,
    display_name text,
    avatar_url text,
    taste_bio text,                    -- free-text description of what they like ("I love slow-burn sci-fi and A24 horror")
    favorite_genres jsonb default '[]', -- e.g. ["Sci-Fi", "Horror", "Drama"]
    taste_embedding vector(1536),      -- embedding of taste_bio + favorite_genres + watch history signal
    created_at timestamptz default now()
);

-- ============================================================
-- MOVIES (cached TMDB data)
-- ============================================================
create table movies (
    tmdb_id int primary key,
    title text not null,
    year int,
    overview text,
    poster_path text,
    genres jsonb default '[]',
    runtime int,
    vote_average float,
    cached_at timestamptz default now()
);

-- ============================================================
-- WATCHED MOVIES
-- ============================================================
create table watched_movies (
    id bigint generated always as identity primary key,
    user_id uuid not null references profiles(id) on delete cascade,
    tmdb_id int not null references movies(tmdb_id),
    rating float check (rating >= 0.5 and rating <= 5.0),
    review text,
    watched_date date,
    created_at timestamptz default now(),
    unique(user_id, tmdb_id)
);

-- ============================================================
-- FRIENDSHIPS
-- ============================================================
create table friendships (
    id bigint generated always as identity primary key,
    requester_id uuid not null references profiles(id) on delete cascade,
    addressee_id uuid not null references profiles(id) on delete cascade,
    status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
    created_at timestamptz default now(),
    unique(requester_id, addressee_id)
);

-- ============================================================
-- GROUPS
-- ============================================================
create table groups (
    id bigint generated always as identity primary key,
    name text not null,
    created_by uuid not null references profiles(id),
    created_at timestamptz default now()
);

create table group_members (
    group_id bigint not null references groups(id) on delete cascade,
    user_id uuid not null references profiles(id) on delete cascade,
    joined_at timestamptz default now(),
    primary key (group_id, user_id)
);

-- ============================================================
-- MOVIE EMBEDDINGS (pgvector)
-- ============================================================
create table movie_embeddings (
    tmdb_id int primary key references movies(tmdb_id) on delete cascade,
    embedding vector(1536),
    created_at timestamptz default now()
);

-- IVFFlat index for fast similarity search
create index on movie_embeddings
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- ============================================================
-- RPC: match movies by embedding similarity
-- ============================================================
create or replace function match_movies(
    query_embedding vector(1536),
    match_count int default 20,
    exclude_tmdb_ids int[] default '{}'
)
returns table (
    tmdb_id int,
    similarity float
)
language sql stable
as $$
    select
        me.tmdb_id,
        1 - (me.embedding <=> query_embedding) as similarity
    from movie_embeddings me
    where me.tmdb_id != all(exclude_tmdb_ids)
    order by me.embedding <=> query_embedding asc
    limit match_count;
$$;
