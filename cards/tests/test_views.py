"""The card endpoints are public and unauthenticated: a profile card exists
only for profile_public=True (404 otherwise, owner included — crawlers never
carry a session), responses are cached, and repeated hits are rate-limited."""

from io import BytesIO
from typing import Any
from unittest import mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def _png(response: Any) -> Image.Image:
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    return Image.open(BytesIO(response.content))


def test_profile_card_is_a_png_with_cache_headers(client: Client) -> None:
    user = User.objects.create_user(email="p@example.com", password="x", display_name="P")
    response = client.get(reverse("cards:profile", args=[user.slug]))
    assert _png(response).size == (1200, 630)
    assert "max-age=3600" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_private_profile_has_no_card(client: Client) -> None:
    user = User.objects.create_user(
        email="h@example.com", password="x", display_name="H", profile_public=False
    )
    assert client.get(reverse("cards:profile", args=[user.slug])).status_code == 404
    client.force_login(user)  # not even for the owner: crawlers never carry a session
    assert client.get(reverse("cards:profile", args=[user.slug])).status_code == 404


def test_game_and_default_cards(client: Client) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    assert _png(client.get(reverse("cards:game", args=[game.slug]))).size == (1200, 630)
    assert _png(client.get(reverse("cards:default"))).size == (1200, 630)
    assert client.get("/u/nobody-here/card.png").status_code == 404


def test_second_request_is_served_from_cache(client: Client) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    url = reverse("cards:profile", args=[user.slug])
    real_render = __import__("cards.render", fromlist=["render"]).render
    with mock.patch("cards.views.render", wraps=real_render) as spy:
        client.get(url)
        client.get(url)
    assert spy.call_count == 1


def test_cards_are_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.PROFILE_RATELIMIT = "2/m"
    cache.clear()
    url = reverse("cards:default")
    client.get(url)
    client.get(url)
    assert client.get(url).status_code == 403


def test_head_shares_the_get_quota_and_post_is_not_allowed(client: Client, settings: Any) -> None:
    # method=_ALL_METHODS (cards.views): GET and HEAD must share one counter, or a client
    # can double its effective quota by alternating verbs. require_safe keeps
    # POST/PUT out of the limiter entirely (405, not a quota-consuming 403).
    settings.RATELIMIT_ENABLE = True
    settings.PROFILE_RATELIMIT = "1/m"
    cache.clear()
    url = reverse("cards:default")
    assert client.get(url).status_code == 200
    assert client.head(url).status_code == 403
    assert client.post(url).status_code == 405
