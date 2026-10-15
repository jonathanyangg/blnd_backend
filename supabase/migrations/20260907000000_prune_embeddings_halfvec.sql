-- Shrink movie_embeddings (was ~918 MB of a 500 MB free-tier quota).
--
-- 1. Drop embeddings for obscure movies (< 20 TMDB votes) that no user has
--    watched, watchlisted, hidden, or commented on. The exploration pool and
--    semantic search already filter these out downstream, and the ingestion
--    threshold (MIN_VOTE_COUNT) is raised to 20 so they don't come back.
-- 2. Store vectors as halfvec(1536) (16-bit floats): halves table + index size
--    with negligible impact on cosine similarity.
-- 3. Replace the ivfflat index (lists=100, probes=1 => poor recall) with HNSW.
-- 4. match_movies keeps its vector(1536) signature so callers don't change;
--    it casts to halfvec internally. ef_search / iterative_scan are set on the
--    function so LIMIT 500 + exclusion filters still return a full result set.

delete from movie_embeddings e
using (
    select e2.tmdb_id
    from movie_embeddings e2
    left join movies m on m.tmdb_id = e2.tmdb_id
    where coalesce(m.vote_count, 0) < 20
      and e2.tmdb_id not in (
          select tmdb_id from watched_movies
          union select tmdb_id from watchlist_movies
          union select tmdb_id from hidden_movies
          union select tmdb_id from movie_comments
      )
) prune
where e.tmdb_id = prune.tmdb_id;

drop index if exists movie_embeddings_embedding_idx;

-- Rewrites the table, which also reclaims the space freed by the delete.
alter table movie_embeddings
    alter column embedding type halfvec(1536) using embedding::halfvec(1536);

create index movie_embeddings_embedding_idx
    on movie_embeddings using hnsw (embedding halfvec_cosine_ops)
    with (m = 16, ef_construction = 64);

create or replace function public.match_movies(
    query_embedding vector,
    match_count integer default 20,
    exclude_tmdb_ids integer[] default '{}'::integer[]
)
returns table(tmdb_id integer, similarity double precision)
language sql
stable
set hnsw.ef_search = 1000
set hnsw.iterative_scan = 'strict_order'
as $function$
    select
        me.tmdb_id,
        1 - (me.embedding <=> query_embedding::halfvec(1536)) as similarity
    from movie_embeddings me
    where me.tmdb_id != all(exclude_tmdb_ids)
    order by me.embedding <=> query_embedding::halfvec(1536) asc
    limit match_count;
$function$;
