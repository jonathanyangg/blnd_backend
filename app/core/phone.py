"""Phone numbers are matched as hashes. The client sends raw E.164.

The server strips separators, checks E.164, then stores
HMAC-SHA256(CONTACT_HASH_KEY, e164). The raw number is not written and is
not returned. iOS does not pre-hash: the key stays on the server.
"""

import hashlib
import hmac
import re

from app.config import settings

_SEPARATORS = re.compile(r"[\s().-]")
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_e164(value: str) -> str:
    """Strip separators and require a leading + and country code."""
    cleaned = _SEPARATORS.sub("", value.strip())
    if not _E164.match(cleaned):
        raise ValueError("Phone number must be in E.164 format (e.g. +15551234567)")
    return cleaned


def hash_phone(value: str) -> str:
    """HMAC of a normalized E.164 number. Raises if the server key is unset."""
    key = settings.contact_hash_key
    if not key:
        raise ValueError("Contact matching is not configured")
    e164 = normalize_e164(value)
    return hmac.new(key.encode(), e164.encode(), hashlib.sha256).hexdigest()
