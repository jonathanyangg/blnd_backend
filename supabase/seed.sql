-- Local Docker seed only. `supabase db reset` loads this file.
-- It is not a migration and must not be applied to production.
--
-- blnd+ is a row on profiles, not a live RevenueCat call:
--   subscription_tier = 'premium'
--   subscription_source = 'admin'
--   subscription_expires_at IS NULL
-- is_premium() treats that as a perpetual admin grant.
-- GET /auth/me then returns is_premium: true.

update public.profiles
set
    subscription_tier = 'premium',
    subscription_source = 'admin',
    subscription_expires_at = null
where username in ('demo_one', 'demo_two');
