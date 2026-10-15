"""Affiliate link builders, keyed by TMDB watch-provider id.

Adding a provider is a new target plus an adapter (or one more id on an
existing adapter) and env vars. Call sites only use ``links_for`` and
``REGISTRY``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlparse

from app.config import settings

DEFAULT_AMAZON_TAG = "blndmovies-20"


@dataclass(frozen=True)
class Title:
    title: str
    year: int | None
    media_type: str
    tmdb_id: int


@dataclass(frozen=True)
class Provider:
    provider_id: int
    provider_name: str


@dataclass(frozen=True)
class Offer:
    provider_id: int
    provider_name: str
    monetization: str
    logo_path: str | None = None
    region_link: str | None = None


@dataclass(frozen=True)
class ProviderTarget:
    provider_id: int
    name: str
    search_url: str
    hosts: frozenset[str]


class AffiliateProvider(Protocol):
    provider_ids: tuple[int, ...]

    def supports(self, title: Title, provider: Provider) -> bool:
        """Whether this adapter should tag a link for the provider."""
        ...

    def build_web_url(self, title: Title, offer: Offer) -> str:
        """Title-specific https URL, affiliate-tagged when configured."""
        ...

    def build_app_deeplink(self, title: Title, offer: Offer) -> str | None:
        """Optional app URL. None when we only have a universal https link."""
        ...


# Custom schemes ios_link may return. https universal links are the other kind.
IOS_CUSTOM_SCHEMES = frozenset({"aiv"})
UNIVERSAL_LINK_HOSTS = frozenset({"www.amazon.com", "tv.apple.com"})


def resolve_amazon_tag(raw: str | None) -> str | None:
    """Tag appended on the redirect, never by the client.

    Unset uses the public tag. A blank string is explicit and means untagged.
    The redirect adds ``tag`` only when this returns a non-empty value.
    """
    if raw is None:
        return DEFAULT_AMAZON_TAG
    tag = raw.strip()
    return tag or None


def _query_text(title: Title) -> str:
    if title.year is None:
        return title.title
    return f"{title.title} {title.year}"


def _search_url(target: ProviderTarget, title: Title) -> str:
    return target.search_url.format(query=quote(_query_text(title), safe=""))


def _with_param(url: str, key: str, value: str | None) -> str:
    if not value:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{key}={quote(value, safe='')}"


TARGETS: dict[int, ProviderTarget] = {
    119: ProviderTarget(
        119,
        "Amazon Prime Video",
        "https://www.amazon.com/gp/video/search?phrase={query}",
        frozenset({"www.amazon.com"}),
    ),
    10: ProviderTarget(
        10,
        "Amazon Video",
        "https://www.amazon.com/s?k={query}&i=instant-video",
        frozenset({"www.amazon.com"}),
    ),
    531: ProviderTarget(
        531,
        "Paramount Plus",
        "https://www.paramountplus.com/search/?q={query}",
        frozenset({"www.paramountplus.com"}),
    ),
    386: ProviderTarget(
        386,
        "Peacock",
        "https://www.peacocktv.com/watch/search?q={query}",
        frozenset({"www.peacocktv.com"}),
    ),
    387: ProviderTarget(
        387,
        "Peacock Premium",
        "https://www.peacocktv.com/watch/search?q={query}",
        frozenset({"www.peacocktv.com"}),
    ),
    15: ProviderTarget(
        15,
        "Hulu",
        "https://www.hulu.com/search?q={query}",
        frozenset({"www.hulu.com"}),
    ),
    43: ProviderTarget(
        43,
        "Starz",
        "https://www.starz.com/us/en/search?q={query}",
        frozenset({"www.starz.com"}),
    ),
    283: ProviderTarget(
        283,
        "Crunchyroll",
        "https://www.crunchyroll.com/search?q={query}",
        frozenset({"www.crunchyroll.com"}),
    ),
    2: ProviderTarget(
        2,
        "Apple TV",
        "https://tv.apple.com/us/search?term={query}",
        frozenset({"tv.apple.com"}),
    ),
    350: ProviderTarget(
        350,
        "Apple TV Plus",
        "https://tv.apple.com/us/search?term={query}",
        frozenset({"tv.apple.com"}),
    ),
}


class AmazonAssociates:
    """Prime Video and Amazon Video search links with an Associates tag."""

    provider_ids: tuple[int, ...] = (119, 10)

    def supports(self, title: Title, provider: Provider) -> bool:
        return (
            settings.amazon_associates_enabled
            and provider.provider_id in self.provider_ids
        )

    def build_web_url(self, title: Title, offer: Offer) -> str:
        return _search_url(TARGETS[offer.provider_id], title)

    def build_app_deeplink(self, title: Title, offer: Offer) -> str | None:
        phrase = quote(_query_text(title), safe="")
        return f"aiv://aiv/search?phrase={phrase}"


class ConfiguredSearchStub:
    """Provider search URL tagged with a partner id when that network is enabled.

    Impact, Rakuten, and CJ need a campaign template from the network before
    these are real deep links. Until then the user stays on the provider host
    and the partner id is a query param. Apple's ``at`` token is the real
    Services Performance Partners parameter, but it stays off until set.
    """

    provider_ids: tuple[int, ...]

    def __init__(
        self,
        provider_ids: tuple[int, ...],
        param_name: str,
        enabled: Callable[[], bool],
        partner_id: Callable[[], str],
    ) -> None:
        self.provider_ids = provider_ids
        self._param_name = param_name
        self._enabled = enabled
        self._partner_id = partner_id

    def _partner(self) -> str:
        return (self._partner_id() or "").strip()

    def supports(self, title: Title, provider: Provider) -> bool:
        return (
            provider.provider_id in self.provider_ids
            and bool(self._enabled())
            and bool(self._partner())
        )

    def build_web_url(self, title: Title, offer: Offer) -> str:
        base = _search_url(TARGETS[offer.provider_id], title)
        return _with_param(base, self._param_name, self._partner())

    def build_app_deeplink(self, title: Title, offer: Offer) -> str | None:
        return None


class PassthroughProvider:
    """Untagged link. Search URL when we know the provider, otherwise JustWatch."""

    provider_ids: tuple[int, ...] = ()

    def supports(self, title: Title, provider: Provider) -> bool:
        return True

    def build_web_url(self, title: Title, offer: Offer) -> str:
        target = TARGETS.get(offer.provider_id)
        if target is not None:
            return _search_url(target, title)
        if offer.region_link:
            return offer.region_link
        kind = "tv" if title.media_type == "tv" else "movie"
        return f"https://www.themoviedb.org/{kind}/{title.tmdb_id}/watch"

    def build_app_deeplink(self, title: Title, offer: Offer) -> str | None:
        return None


AMAZON = AmazonAssociates()
IMPACT = ConfiguredSearchStub(
    (531, 386, 387),
    "subId1",
    lambda: settings.impact_enabled,
    lambda: settings.impact_partner_id,
)
RAKUTEN = ConfiguredSearchStub(
    (15,),
    "ranSiteID",
    lambda: settings.rakuten_enabled,
    lambda: settings.rakuten_partner_id,
)
CJ = ConfiguredSearchStub(
    (43, 283),
    "sid",
    lambda: settings.cj_enabled,
    lambda: settings.cj_partner_id,
)
APPLE = ConfiguredSearchStub(
    (2, 350),
    "at",
    lambda: settings.apple_tv_affiliate_enabled,
    lambda: settings.apple_tv_affiliate_token,
)
PASSTHROUGH = PassthroughProvider()

REGISTRY: dict[int, AffiliateProvider] = {}
for _adapter in (AMAZON, IMPACT, RAKUTEN, CJ, APPLE):
    for _provider_id in _adapter.provider_ids:
        if _provider_id not in TARGETS:
            raise RuntimeError(f"provider {_provider_id} has no search target")
        REGISTRY[_provider_id] = _adapter


def ios_link(web_url: str, app_url: str | None) -> str | None:
    """Link the iOS app can open. Null when we have neither kind.

    A custom scheme is returned only if it is in ``IOS_CUSTOM_SCHEMES``.
    Otherwise an https universal link is returned when the host is known.
    """
    if app_url:
        scheme = (urlparse(app_url).scheme or "").lower()
        if scheme in IOS_CUSTOM_SCHEMES:
            return app_url
    parsed = urlparse(web_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host in UNIVERSAL_LINK_HOSTS:
        return web_url
    return None


def click_base(configured: str, request_base: str, forwarded_proto: str) -> str:
    """Origin for click_url. PUBLIC_BASE_URL wins. Otherwise the request, with
    X-Forwarded-Proto applied so a proxy can force https.
    """
    raw = configured.strip()
    if raw:
        parsed = urlparse(raw)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    base = urlparse(request_base)
    proto = forwarded_proto.split(",")[0].strip().lower()
    scheme = proto if proto in ("http", "https") else (base.scheme or "http")
    if not base.netloc:
        return request_base.rstrip("/")
    return f"{scheme}://{base.netloc}"


def click_url(
    base_url: str, provider_id: int, media_type: str, tmdb_id: int
) -> str | None:
    """Absolute public redirect URL. Null when the provider is not allow-listed."""
    if provider_id not in REGISTRY:
        return None
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    root = base_url.rstrip("/")
    return f"{root}/out/{provider_id}/{media_type}/{tmdb_id}"


def links_for(title: Title, offer: Offer) -> tuple[str, str | None]:
    """Adapter link, or the untagged passthrough link. No Amazon tag here."""
    provider = Provider(offer.provider_id, offer.provider_name)
    adapter = REGISTRY.get(offer.provider_id)
    if adapter is not None and adapter.supports(title, provider):
        return adapter.build_web_url(title, offer), adapter.build_app_deeplink(
            title, offer
        )
    return PASSTHROUGH.build_web_url(title, offer), PASSTHROUGH.build_app_deeplink(
        title, offer
    )


def outbound_url(title: Title, provider_id: int) -> str:
    """Https URL for a redirect. Raises KeyError or ValueError if not allowed."""
    if provider_id not in REGISTRY:
        raise KeyError(provider_id)
    target = TARGETS[provider_id]
    web, _app = links_for(
        title,
        Offer(
            provider_id=provider_id,
            provider_name=target.name,
            monetization="flatrate",
        ),
    )
    if provider_id in AMAZON.provider_ids:
        web = _with_param(
            web, "tag", resolve_amazon_tag(settings.amazon_associates_tag)
        )
    parsed = urlparse(web)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in target.hosts:
        raise ValueError(host or parsed.scheme)
    return web
