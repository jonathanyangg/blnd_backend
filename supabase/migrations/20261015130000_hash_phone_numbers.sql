-- Phone columns stay, but they must hold HMAC-SHA256 digests, not E.164.
-- CONTACT_HASH_KEY lives in the app, not in Postgres, so existing raw numbers
-- cannot be re-hashed here. Clear only values that are not already 64-char
-- hex digests. Users save the number again and clients re-upload contacts.
UPDATE profiles
SET phone_number = NULL
WHERE phone_number IS NOT NULL
  AND phone_number !~ '^[0-9a-f]{64}$';

DELETE FROM user_contacts
WHERE contact_phone !~ '^[0-9a-f]{64}$';
