"""robots.txt + sitemap — index public pages (SEO), exclude private profiles."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


def test_robots_txt_allows_indexing_and_points_to_sitemap(client: Client) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content
    assert b"Sitemap:" in body
    assert b"Disallow: /admin/" in body
    assert b"Disallow: /settings/" in body


def test_sitemap_lists_public_profiles_and_games(client: Client) -> None:
    public = User.objects.create_user(email="pub@example.com", password="x", display_name="Pub")
    private = User.objects.create_user(
        email="priv@example.com", password="x", display_name="Priv", profile_public=False
    )
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    response = client.get(reverse("sitemap"))

    assert response.status_code == 200
    body = response.content
    assert public.get_absolute_url().encode() in body
    assert private.get_absolute_url().encode() not in body  # private excluded
    assert game.get_absolute_url().encode() in body


def test_game_and_company_have_absolute_urls() -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    assert game.get_absolute_url() == f"/g/{game.slug}/"
