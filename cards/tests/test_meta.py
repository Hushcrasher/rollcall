"""Every page carries Open Graph tags; profiles and games override them.
Absolute URLs, a cache-busting token, and never an email (spec §1)."""

import re
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _meta(body: str, prop: str) -> str:
    match = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', body)
    assert match, f"no {prop} tag"
    return match.group(1)


def test_home_carries_default_tags_with_absolute_urls(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    assert _meta(body, "og:title") == "Rollcall"
    assert _meta(body, "og:url").startswith("http://testserver/")
    assert _meta(body, "og:image").startswith("http://testserver/card.png?v=")
    assert _meta(body, "twitter:card") == "summary_large_image"
    assert _meta(body, "og:image:width") == "1200"


def test_profile_overrides_and_token_tracks_the_data(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="Mina Okafor")
    url = reverse("accounts:profile", args=[user.slug])
    before = _meta(client.get(url).content.decode(), "og:image")
    assert before.startswith(f"http://testserver{reverse('cards:profile', args=[user.slug])}?v=")
    Contribution.objects.create(
        user=user,
        game=Game.objects.create(title="G", source=Game.Source.MANUAL),
        discipline=Discipline.objects.get(name="Design"),
        job_title="Producer",
        start_date=date(2020, 1, 1),
    )
    body = client.get(url).content.decode()
    assert _meta(body, "og:image") != before
    assert _meta(body, "og:title") == "Mina Okafor · Rollcall"
    assert _meta(body, "og:type") == "profile"
    assert "1 credit" in _meta(body, "og:description")
    assert _meta(body, "og:url") == f"http://testserver{url}"


def test_game_overrides(client: Client) -> None:
    game = Game.objects.create(
        title="Lost Depths", source=Game.Source.MANUAL, release_date=date(2021, 1, 1)
    )
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    assert _meta(body, "og:title") == "Lost Depths (2021) · Rollcall"
    assert _meta(body, "og:image").startswith(
        f"http://testserver{reverse('cards:game', args=[game.slug])}?v="
    )


def test_no_meta_tag_ever_carries_an_email(client: Client) -> None:
    user = User.objects.create_user(
        email="leak@example.com", password="x", display_name="Leak Test"
    )
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    for content in re.findall(r'<meta [^>]*content="([^"]*)"', body):
        assert "@" not in content
