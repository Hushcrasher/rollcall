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
    # Asserted on an ASCII fragment, not the whole sentence: the copy carries
    # an em dash, and a byte comparison against it is a needless trap.
    assert b"after signing up" in response.content
    assert b"{#" not in response.content


def test_company_autocomplete_keeps_the_optional_hint_away_from_a_member(client: Client) -> None:
    """A member reaching this endpoint from the logged-in credit form sends
    `offer_create=1` (see test_company_autocomplete_offers_a_create_option_to_the_credit_form) —
    that page's working create button already gives them a way forward, so
    the hint is noise there. Without `offer_create=1` the same authenticated
    request is the declare funnel's step 2, which gets its own hint instead
    (test_company_autocomplete_tells_a_member_on_the_declare_funnels_step_2_the_employer_is_optional)."""
    user = User.objects.create_user(email="m2@example.com", password="x", display_name="M2")
    client.force_login(user)
    response = client.get(
        reverse("search:company_autocomplete"), {"q": "Nonexistent Studio", "offer_create": "1"}
    )
    assert b"No companies found." in response.content
    assert b"Optional" not in response.content
    assert b"{#" not in response.content


def test_company_autocomplete_tells_a_member_on_the_declare_funnels_step_2_the_employer_is_optional(
    client: Client,
) -> None:
    """A logged-in member can walk the declare funnel too. Step 2
    (declare_details.html) sends no `offer_create`, so unlike the credit form
    they get no create button (see
    test_company_autocomplete_hides_the_create_option_from_the_declare_funnels_step_2)
    — without a hint of their own that was a silent dead end: not the
    anonymous hint above (wrong copy — they already have an account) and not
    the button (nothing listens for its click on this page)."""
    user = User.objects.create_user(email="m6@example.com", password="x", display_name="M6")
    client.force_login(user)
    response = client.get(reverse("search:company_autocomplete"), {"q": "Nonexistent Studio"})
    assert b"No companies found." in response.content
    assert b"add it later" in response.content
    assert b"company-create" not in response.content
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


@pytest.fixture
def igdb_configured(settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"


def test_a_local_miss_fetches_igdb_without_being_asked(
    client: Client, igdb_configured: None
) -> None:
    """The escape hatch used to be an italic line the member had to notice.
    Nothing found locally means the question was already asked — ask IGDB."""
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b'hx-trigger="load"' in response.content
    assert b"Searching IGDB" in response.content


def test_local_matches_keep_igdb_behind_a_deliberate_click(
    client: Client, igdb_configured: None
) -> None:
    """A search that found what it wanted must still cost zero IGDB calls."""
    Game.objects.create(title="Slay the Spire", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b"igdb-trigger" in response.content
    assert b'hx-trigger="load"' not in response.content
    # The copy must not name the external service (owner decision 2026-08-22).
    assert b"Run a deeper search" in response.content


def test_a_local_miss_offers_nothing_when_igdb_is_unconfigured(client: Client) -> None:
    """Default test settings blank the credentials — the page must look
    exactly as it did before this feature."""
    response = client.get(reverse("search:game_autocomplete"), {"q": "Slay the Spire"})
    assert b'hx-trigger="load"' not in response.content
    assert b"igdb-trigger" not in response.content


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
def test_game_and_company_autocomplete_meter_each_member_without_sharing_a_nat_counter(
    client: Client, settings: Any, url_name: str
) -> None:
    """These two also back the logged-in credit form's keyup typeahead, keyed
    by `user_or_ip` rather than `ip`. Two members behind the same office NAT
    (both hit from this test's single IP) must not share a counter — a
    per-IP limit meant for anonymous scraping would otherwise 403 one
    member's requests because of another's, and htmx does not swap on a 403,
    so the dropdown would silently stop updating. Unlike the earlier
    `None`-for-authenticated approach (reverted — it hands out an unmetered
    endpoint to anyone with a free, unverified account), each member is
    still metered on their own budget: Alice's second request 403s, but Bob
    signing in right after is untouched by Alice's usage."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()
    alice = User.objects.create_user(email="alice@example.com", password="x", display_name="Alice")
    bob = User.objects.create_user(email="bob@example.com", password="x", display_name="Bob")
    url = reverse(url_name)

    client.force_login(alice)
    assert client.get(url, {"q": "a"}).status_code == 200
    assert client.get(url, {"q": "a"}).status_code == 403  # Alice is metered, not exempt

    client.force_login(bob)
    assert client.get(url, {"q": "a"}).status_code == 200  # Bob's own budget, untouched
