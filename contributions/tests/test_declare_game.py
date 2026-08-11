"""Step 1 of the declare funnel — turn a typed title into a chosen game.

Plain HTML on purpose: the root only carries a text box, and the picking happens
here (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
"""

import re
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.funnel import SESSION_KEY
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def test_declare_is_open_to_anonymous_visitors(client: Client) -> None:
    """The whole point: no account needed to start."""
    assert client.get(reverse("contributions:declare")).status_code == 200


def test_posting_a_title_lists_matching_games(client: Client, game: Game) -> None:
    """Scoped to the form carrying the hidden `game` input, not just the page
    text — the search box's own placeholder ("Hollow Knight, Dishonored…")
    would satisfy a bare `b"Hollow Knight" in response.content` even when
    nothing matched."""
    response = client.post(reverse("contributions:declare"), {"q": "hollow"})
    assert response.status_code == 200
    body = response.content.decode()
    match = re.search(r'<form[^>]*>.*?name="game".*?</form>', body, re.S)
    assert match is not None, "no form carrying a pickable game"
    assert "Hollow Knight" in match.group(0)


def test_picking_a_game_stores_it_and_moves_on(client: Client, game: Game) -> None:
    response = client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_details")
    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_a_junk_game_id_does_not_500(client: Client) -> None:
    """Public page, unauthenticated POST — junk must re-render, never crash."""
    for junk in ("abc", "-1", "999999999", "", "²"):
        response = client.post(reverse("contributions:declare"), {"game": junk})
        assert response.status_code == 200, junk
        assert SESSION_KEY not in client.session, junk


def test_repicking_a_different_game_clears_the_old_employer(client: Client, game: Game) -> None:
    """Step 2's own "Wrong game?" link leads here. The stale employer is
    unclearable through the UI (the funnel's JS can only set a company, never
    clear one), so a different pick must drop the rest of the draft."""
    other = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk), "company": "42", "job_title": "Artist"}
    session.save()

    client.post(reverse("contributions:declare"), {"game": str(other.pk)})

    assert client.session[SESSION_KEY] == {"game": str(other.pk)}


def test_repicking_the_same_game_keeps_the_draft(client: Client, game: Game) -> None:
    """A visitor who re-picks the title they already had must not lose what
    they typed."""
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk), "company": "42", "job_title": "Artist"}
    session.save()

    client.post(reverse("contributions:declare"), {"game": str(game.pk)})

    assert client.session[SESSION_KEY] == {
        "game": str(game.pk),
        "company": "42",
        "job_title": "Artist",
    }


def test_no_match_says_so_and_offers_the_account(client: Client) -> None:
    """igdb_search is login-gated and stays that way, so a miss converts into a
    signup rather than a dead end."""
    body = client.post(reverse("contributions:declare"), {"q": "zzzznotagame"}).content
    assert b"No match" in body
    assert reverse("accounts:signup").encode() in body


def test_home_leads_with_the_question_for_anonymous_visitors(client: Client) -> None:
    body = client.get(reverse("home")).content
    assert b"Which game did you work on?" in body
    assert reverse("contributions:declare").encode() in body


def test_the_search_post_is_rate_limited(client: Client, settings: Any) -> None:
    """This is where /declare/'s trigram search over Game actually runs — an
    unmetered anonymous search otherwise (docs/02-ARCHITECTURE.md §5)."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    assert client.post(url, {"q": "a"}).status_code == 200
    assert client.post(url, {"q": "a"}).status_code == 403


def test_a_bare_get_is_never_rate_limited(client: Client, settings: Any) -> None:
    """The page itself must always answer, the same reason the home page's
    front door is unmetered — only the POSTed search spends quota."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    client.post(url, {"q": "a"})
    client.post(url, {"q": "a"})
    assert client.get(url).status_code == 200


def test_home_does_not_ask_a_member(client: Client) -> None:
    """They already have an account — the invitation is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    body = client.get(reverse("home")).content
    assert b"Which game did you work on?" not in body
    assert b"Find people by what they" in body
