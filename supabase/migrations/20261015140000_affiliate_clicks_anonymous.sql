-- Anonymous clicks have no user. The API (database owner / service role)
-- bypasses RLS and may insert either kind. PostgREST anon may insert only
-- a row with no user_id, and cannot read clicks.
alter table affiliate_clicks alter column user_id drop not null;

create policy affiliate_clicks_insert_anonymous
    on affiliate_clicks for insert
    to anon
    with check (user_id is null);
