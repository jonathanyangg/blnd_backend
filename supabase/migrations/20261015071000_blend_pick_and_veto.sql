-- One pick and the vetoes that excluded titles, per blend per UTC day.
create table if not exists public.blend_picks (
    group_id bigint not null references public.groups(id) on delete cascade,
    pick_date date not null,
    tmdb_id int not null references public.movies(tmdb_id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (group_id, pick_date)
);

create table if not exists public.blend_vetoes (
    group_id bigint not null references public.groups(id) on delete cascade,
    veto_date date not null,
    user_id uuid not null references public.profiles(id) on delete cascade,
    tmdb_id int not null references public.movies(tmdb_id) on delete cascade,
    reason text not null check (char_length(reason) between 1 and 280),
    created_at timestamptz not null default now(),
    primary key (group_id, veto_date, user_id, tmdb_id)
);
