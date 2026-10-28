"""Amazon affiliate tag. Off unless AMAZON_AFFILIATE_ENABLED is true."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import settings


def _is_amazon(host: str) -> bool:
    # amazon.com, amazon.co.uk, and the amzn.to short link.
    return host == "amzn.to" or ".amazon." in f".{host}."


def apply_amazon_affiliate_tag(link: str) -> str:
    """Return link with our tag only when the flag is on.

    Amazon links lose any existing tag when the flag is off, so production
    does not emit one. Other hosts are unchanged.
    """
    parts = urlsplit(link)
    host = (parts.hostname or "").lower()
    if not _is_amazon(host):
        return link
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "tag"
    ]
    if settings.amazon_affiliate_enabled and settings.amazon_affiliate_tag:
        query.append(("tag", settings.amazon_affiliate_tag))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
