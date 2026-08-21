"""Game.capsule_url (spec 2026-08-21-game-capsules §1): the catalog's own image
first, else the public Steam CDN asset for the app id, else nothing."""

import pytest

from games.models import STEAM_CAPSULE_URL, Game

pytestmark = pytest.mark.django_db


def test_prefers_the_catalog_cover_url() -> None:
    game = Game.objects.create(
        title="A", source=Game.Source.MANUAL, cover_url="https://cdn.example/a.jpg", steam_appid=10
    )
    assert game.capsule_url == "https://cdn.example/a.jpg"


def test_derives_from_the_steam_appid() -> None:
    game = Game.objects.create(title="B", source=Game.Source.MANUAL, steam_appid=620)
    assert game.capsule_url == STEAM_CAPSULE_URL.format(appid=620)
    assert game.capsule_url.startswith("https://") and "/620/" in game.capsule_url


def test_empty_without_either() -> None:
    game = Game.objects.create(title="C", source=Game.Source.MANUAL)
    assert game.capsule_url == ""
