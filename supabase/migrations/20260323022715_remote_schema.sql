alter table "public"."hidden_movies" enable row level security;

alter table "public"."movies" add column "vote_count" integer default 0;

alter table "public"."sync_state" enable row level security;

alter table "public"."watchlist_movies" enable row level security;

alter table "public"."watchlists" enable row level security;

create policy "RLS for pfp 1oj01fe_0"
  on "storage"."objects"
  as permissive
  for select
  to public
using (true);

create policy "RLS inserting and updating 1oj01fe_0"
  on "storage"."objects"
  as permissive
  for insert
  to public
with check (((auth.uid())::text = (storage.foldername(name))[1]));

create policy "RLS inserting and updating 1oj01fe_1"
  on "storage"."objects"
  as permissive
  for update
  to public
using (((auth.uid())::text = (storage.foldername(name))[1]));

create policy "RLS inserting and updating 1oj01fe_3"
  on "storage"."objects"
  as permissive
  for delete
  to public
using (((auth.uid())::text = (storage.foldername(name))[1]));
