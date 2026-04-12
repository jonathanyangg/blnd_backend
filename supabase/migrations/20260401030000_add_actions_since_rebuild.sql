-- Add action counter for debounced taste profile rebuilds.
-- Incremented on rate/hide/watchlist; reset to 0 after rebuild.
alter table profiles
    add column actions_since_rebuild int not null default 0;
