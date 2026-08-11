"""Step 1 of the declare funnel — turn a typed title into a chosen game.

Plain HTML on purpose: the root only carries a text box, and the picking happens
here (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
"""

import pytest
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
    response = client.post(reverse("contributions:declare"), {"q": "hollow"})
    assert response.status_code == 200
    assert b"Hollow Knight" in response.content


def test_picking_a_game_stores_it_and_moves_on(client: Client, game: Game) -> None:
    response = client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_details")
    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_a_junk_game_id_does_not_500(client: Client) -> None:
    """Public page, unauthenticated POST — junk must re-render, never crash."""
    for junk in ("abc", "-1", "999999999", ""):
        response = client.post(reverse("contributions:declare"), {"game": junk})
        assert response.status_code == 200, junk
        assert SESSION_KEY not in client.session, junk


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


def test_home_does_not_ask_a_member(client: Client) -> None:
    """They already have an account — the invitation is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    body = client.get(reverse("home")).content
    assert b"Which game did you work on?" not in body
    assert b"Find people by what they" in body
