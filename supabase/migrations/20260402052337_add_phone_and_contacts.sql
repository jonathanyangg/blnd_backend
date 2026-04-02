-- Add phone number to profiles for contact discovery
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS phone_number TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_phone_number
    ON profiles (phone_number) WHERE phone_number IS NOT NULL;

-- Store uploaded contact phone numbers for matching
CREATE TABLE IF NOT EXISTS user_contacts (
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    contact_phone TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, contact_phone)
);

CREATE INDEX idx_user_contacts_phone ON user_contacts (contact_phone);
