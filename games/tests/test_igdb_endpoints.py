"""IGDB search + import endpoints (login-gated). No network — the client's
fetch methods are monkeypatched."""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.igdb import IGDBClient
from games.models import Game

pytestmark = pytest.mark.django_db

CELESTE = {
    "id": 26226,
    "name": "Celeste",
    "first_release_date": 1516924800,
    "genres": [{"name": "Platformer"}],
    "involved_companies": [{"company": {"name": "Maddy Makes Games"}, "developer": True}],
}


@pytest.fixture
def member(client: Client) -> User:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    return user


@pytest.fixture
def igdb_configured(settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def test_search_requires_login(client: Client) -> None:
    assert client.get(reverse("games:igdb_search")).status_code == 302


def test_search_returns_igdb_options(
    client: Client, member: User, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: [{"id": 26226, "name": "Celeste"}]
    )
    response = client.get(reverse("games:igdb_search"), {"q": "celeste"})
    assert response.status_code == 200
    assert b"Celeste" in response.content
    assert b'data-igdb-id="26226"' in response.content


def test_search_shows_a_notice_when_igdb_is_unconfigured(client: Client, member: User) -> None:
    # No IGDB creds in the default test settings.
    response = client.get(reverse("games:igdb_search"), {"q": "celeste"})
    assert response.status_code == 200
    assert b"not configured" in response.content.lower()


def test_search_over_quota_says_so_and_calls_nothing(
    client: Client,
    member: User,
    igdb_configured: None,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Over quota is not an error: the fragment says why and no HTTP happens."""
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "0/m"
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or [])
    response = client.get(reverse("games:igdb_search"), {"q": "celeste"})
    assert response.status_code == 200
    assert b"busy right now" in response.content
    assert calls == []


def test_a_cached_search_does_not_spend_quota(
    client: Client,
    member: User,
    igdb_configured: None,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The eleventh repeat of a popular title costs IGDB nothing, so it must
    still answer."""
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "1/m"
    monkeypatch.setattr(
        IGDBClient, "search_games", lambda self, q, limit=10: [{"id": 26226, "name": "Celeste"}]
    )
    url = reverse("games:igdb_search")
    for _ in range(3):
        response = client.get(url, {"q": "celeste"})
        assert b"Celeste" in response.content


def test_import_requires_login(client: Client) -> None:
    response = client.post(reverse("games:igdb_import"), {"igdb_id": 1})
    assert response.status_code == 302
    assert Game.objects.count() == 0  # the redirect must not hide a write


def test_import_creates_the_game_and_returns_json(
    client: Client, member: User, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(IGDBClient, "get_game", lambda self, igdb_id: CELESTE)

    response = client.post(reverse("games:igdb_import"), {"igdb_id": 26226})

    assert response.status_code == 200
    payload = response.json()
    game = Game.objects.get(igdb_id=26226)
    assert payload == {"id": game.pk, "label": "Celeste"}
    assert game.source == Game.Source.IGDB_LIVE


def test_import_returns_404_when_igdb_has_no_such_game(
    client: Client, member: User, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(IGDBClient, "get_game", lambda self, igdb_id: None)
    response = client.post(reverse("games:igdb_import"), {"igdb_id": 999})
    assert response.status_code == 404
    assert Game.objects.count() == 0
