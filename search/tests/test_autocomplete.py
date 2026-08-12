"""htmx autocomplete endpoints — return HTML fragments of matching options."""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Company, Game

pytestmark = pytest.mark.django_db


def test_game_autocomplete_returns_matching_options(client: Client) -> None:
    Game.objects.create(title="Hades", igdb_id=1, source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", igdb_id=2, source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_autocomplete"), {"q": "hade"})

    assert response.status_code == 200
    assert b"Hades" in response.content
    assert b"Celeste" not in response.content


def test_game_autocomplete_blank_query_is_empty(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_autocomplete"), {"q": ""})
    assert response.status_code == 200
    assert b"Hades" not in response.content


def test_company_autocomplete_returns_matching_options(client: Client) -> None:
    Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)

    response = client.get(reverse("search:company_autocomplete"), {"q": "super"})

    assert response.status_code == 200
    assert b"Supergiant Games" in response.content


def test_company_autocomplete_offers_a_create_option_to_the_credit_form(client: Client) -> None:
    """games:company_create is @login_required and stays that way, so the
    button that posts to it only makes sense once someone can actually use
    it. `offer_create=1` is what contribution_form.html's employer field
    sends — it's the one page with a `.company-create` click handler."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(
        reverse("search:company_autocomplete"), {"q": "Brand New Studio", "offer_create": "1"}
    )
    assert b"company-create" in response.content
    assert b"Brand New Studio" in response.content
    assert b"{#" not in response.content  # {# ... #} is single-line only; a
    # multi-line one leaks its raw text into the fragment instead of being lexed


def test_company_autocomplete_hides_the_create_option_from_an_anonymous_visitor(
    client: Client,
) -> None:
    """The declare funnel serves this endpoint to anonymous visitors too, and
    unlike the credit form's version the button there has no click handler —
    clicking it did nothing at all. It can't work anonymously either way:
    games:company_create is @login_required."""
    response = client.get(
        reverse("search:company_autocomplete"), {"q": "Brand New Studio", "offer_create": "1"}
    )
    assert b"company-create" not in response.content
    assert b"{#" not in response.content


def test_company_autocomplete_hides_the_create_option_from_the_declare_funnels_step_2(
    client: Client,
) -> None:
    """A logged-in member can walk the declare funnel too (an explicitly
    supported path), and declare_details.html — unlike contribution_form.html
    — carries no `.company-create` click handler. Without sending
    `offer_create`, the button must not appear even though the request is
    authenticated; a member reaching this same endpoint from the credit form
    is covered by test_company_autocomplete_offers_a_create_option_to_the_credit_form
    above."""
    user = User.objects.create_user(email="m5@example.com", password="x", display_name="M5")
    client.force_login(user)
    response = client.get(reverse("search:company_autocomplete"), {"q": "Brand New Studio"})
    assert b"company-create" not in response.content


def test_company_autocomplete_tells_an_anonymous_visitor_the_employer_is_optional(
    client: Client,
) -> None:
    """The declare funnel serves this endpoint to anonymous visitors, and
    withholds the create button from them — without this hint, a studio that
    isn't in the database is a dead end with no way forward."""
    response = client.get(reverse("search:company_autocomplete"), {"q": "Nonexistent Studio"})
    assert b"No companies found." in response.content
    assert b"optional" in response.content
    assert b"{#" not in response.content


def test_company_autocomplete_keeps_the_optional_hint_away_from_a_member(client: Client) -> None:
    """Members reach this endpoint from the logged-in credit form, where the
    create button already gives them a way forward — the hint is noise there."""
    user = User.objects.create_user(email="m2@example.com", password="x", display_name="M2")
    client.force_login(user)
    response = client.get(reverse("search:company_autocomplete"), {"q": "Nonexistent Studio"})
    assert b"No companies found." in response.content
    assert b"optional" not in response.content
    assert b"{#" not in response.content


def test_game_autocomplete_offers_igdb_when_configured(client: Client, settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"
    response = client.get(reverse("search:game_autocomplete"), {"q": "obscure"})
    assert b"igdb/search" in response.content  # inline "Search IGDB" fallback


def test_game_autocomplete_hides_igdb_when_unconfigured(client: Client) -> None:
    # No IGDB creds in the default test settings.
    response = client.get(reverse("search:game_autocomplete"), {"q": "obscure"})
    assert b"igdb/search" not in response.content


@pytest.mark.parametrize("url_name", ["search:game_autocomplete", "search:company_autocomplete"])
def test_game_and_company_autocomplete_are_rate_limited_for_anonymous_visitors(
    client: Client, settings: Any, url_name: str
) -> None:
    """Both now serve the declare funnel to anonymous visitors, so they carry
    the same IP rate limit as the public search pages (docs/02-ARCHITECTURE.md
    §5) — same pattern as test_filter_autocomplete_is_rate_limited."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse(url_name)
    assert client.get(url, {"q": "a"}).status_code == 200
    assert client.get(url, {"q": "a"}).status_code == 403


@pytest.mark.parametrize("url_name", ["search:game_autocomplete", "search:company_autocomplete"])
def test_game_and_company_autocomplete_are_not_rate_limited_for_a_member(
    client: Client, settings: Any, url_name: str
) -> None:
    """These two also back the logged-in credit form's keyup typeahead. On a
    shared studio NAT a per-IP limit meant for anonymous scraping would 403
    one member's requests because of another's — and htmx does not swap on a
    403, so the dropdown would silently stop updating. The anti-scraping
    target is anonymous traffic, so a member's requests must not spend the
    same quota."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()
    user = User.objects.create_user(email="nat@example.com", password="x", display_name="Nat")
    client.force_login(user)

    url = reverse(url_name)
    for _ in range(3):
        assert client.get(url, {"q": "a"}).status_code == 200
