alter table public.profiles
    add column subscription_tier text not null default 'free'
        check (subscription_tier in ('free', 'premium')),
    add column subscription_expires_at timestamptz,
    add column subscription_source text
        check (subscription_source in ('apple', 'stripe', 'admin')),
    add column subscription_original_transaction_id text;

create index if not exists idx_profiles_subscription
    on public.profiles (subscription_tier, subscription_expires_at);

create index if not exists idx_profiles_subscription_original_transaction_id
    on public.profiles (subscription_original_transaction_id)
    where subscription_original_transaction_id is not null;
