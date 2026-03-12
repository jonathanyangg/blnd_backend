# Production Checklist

## Before Deploy
- [ ] Remove `BLND_DISABLE_RATE_LIMITS=true` from `.env` (or don't set it in prod)
- [ ] Run `supabase db push` to apply any pending migrations
- [ ] Run movie sync (`POST /import/sync-movies`) to backfill `vote_count` on existing cached movies

## After Deploy
- [ ] Rebuild taste profiles — each user should hit `POST /recommendations/me/refresh` (or trigger via admin) to recompute embeddings with the new rating-weighted algorithm
