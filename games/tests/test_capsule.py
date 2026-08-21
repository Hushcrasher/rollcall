"""Game.capsule_url (spec 2026-08-21-game-capsules §1): the catalog's own image
first, else the public Steam CDN asset for the app id, else nothing."""

import re
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
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


def test_game_page_renders_the_derived_capsule_with_the_guards(client: Client) -> None:
    game = Game.objects.create(title="Derived", source=Game.Source.MANUAL, steam_appid=620)
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    tag = re.search(r'<img class="capsule"[^>]*>', body)
    assert tag, body
    assert STEAM_CAPSULE_URL.format(appid=620) in tag.group(0)
    assert 'referrerpolicy="no-referrer"' in tag.group(0)
    assert 'onerror="this.remove()"' in tag.group(0)
    assert 'loading="lazy"' not in tag.group(0)


def test_game_page_without_any_image_has_no_capsule_tag(client: Client) -> None:
    game = Game.objects.create(title="Bare", source=Game.Source.MANUAL)
    assert (
        'class="capsule"'
        not in client.get(reverse("games:game", args=[game.slug])).content.decode()
    )


def test_profile_credit_line_shows_a_thumbnail_only_when_there_is_a_url(client: Client) -> None:
    user = User.objects.create_user(email="p@example.com", password="x", display_name="P")
    design = Discipline.objects.get(name="Design")
    with_img = Game.objects.create(title="With", source=Game.Source.MANUAL, steam_appid=620)
    without = Game.objects.create(title="Without", source=Game.Source.MANUAL)
    for game in (with_img, without):
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=design,
            job_title="Designer",
            start_date=date(2020, 1, 1),
        )
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert body.count('class="capsule-sm"') == 1
    tag = re.search(r'<img class="capsule-sm"[^>]*>', body)
    assert tag, body
    assert STEAM_CAPSULE_URL.format(appid=620) in tag.group(0)
    assert 'referrerpolicy="no-referrer"' in tag.group(0)
    assert 'onerror="this.remove()"' in tag.group(0)
    assert 'loading="lazy"' in tag.group(0)


def test_company_game_list_shows_thumbnails(client: Client) -> None:
    from games.models import Company, GameCompany

    studio = Company.objects.create(name="Studio", source=Company.Source.MANUAL)
    game = Game.objects.create(title="With", source=Game.Source.MANUAL, steam_appid=620)
    bare = Game.objects.create(title="Bare", source=Game.Source.MANUAL)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)
    GameCompany.objects.create(game=bare, company=studio, role=GameCompany.Role.DEVELOPER)
    body = client.get(reverse("games:company", args=[studio.slug])).content.decode()
    assert body.count('class="capsule-sm"') == 1
