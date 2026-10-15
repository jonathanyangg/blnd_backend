-- Hide test accounts and let a user opt out of discovery.
-- DEFAULT backfills existing profiles: discoverable, not a test account.
-- Profile lookups already use the primary key or the username unique index.
-- These flags are a residual filter on those rows, so no extra index is added.
ALTER TABLE profiles
    ADD COLUMN is_discoverable boolean NOT NULL DEFAULT true,
    ADD COLUMN is_test boolean NOT NULL DEFAULT false;
