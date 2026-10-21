"""Amazon affiliate tag stays off unless the setting is turned on."""

import pytest

from app.config import settings
from app.streaming.affiliate import apply_amazon_affiliate_tag
from app.streaming.services import _parse_options

AMAZON = "https://www.amazon.com/gp/video/detail/B00EXAMPLE?tag=someone-20&ref=x"
NETFLIX = "https://www.netflix.com/title/80057281?tag=someone-20"


def test_disabled_strips_other_amazon_tlds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", False)
    link = apply_amazon_affiliate_tag(
        "https://www.amazon.co.uk/dp/B00EXAMPLE?tag=someone-20"
    )
    assert "tag=" not in link


def test_disabled_strips_amazon_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", False)
    monkeypatch.setattr(settings, "amazon_affiliate_tag", "blnd-20")
    link = apply_amazon_affiliate_tag(AMAZON)
    assert "tag=" not in link
    assert "ref=x" in link


def test_enabled_sets_our_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", True)
    monkeypatch.setattr(settings, "amazon_affiliate_tag", "blnd-20")
    link = apply_amazon_affiliate_tag(AMAZON)
    assert "tag=blnd-20" in link
    assert "someone-20" not in link


def test_enabled_without_a_tag_emits_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", True)
    monkeypatch.setattr(settings, "amazon_affiliate_tag", "")
    assert "tag=" not in apply_amazon_affiliate_tag(AMAZON)


def test_other_hosts_keep_their_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", True)
    monkeypatch.setattr(settings, "amazon_affiliate_tag", "blnd-20")
    assert apply_amazon_affiliate_tag(NETFLIX) == NETFLIX


def test_parse_options_obeys_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = [
        {
            "service": {"id": "prime", "name": "Prime Video"},
            "type": "subscription",
            "link": AMAZON,
        }
    ]
    monkeypatch.setattr(settings, "amazon_affiliate_enabled", False)
    monkeypatch.setattr(settings, "amazon_affiliate_tag", "blnd-20")
    assert "tag=" not in _parse_options(raw)[0]["link"]

    monkeypatch.setattr(settings, "amazon_affiliate_enabled", True)
    assert "tag=blnd-20" in _parse_options(raw)[0]["link"]
