"""Nav live-search suggestions — games + public people as you type."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


def test_suggest_returns_games_and_people(client: Client) -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    person = User.objects.create_user(
        email="a@example.com", password="x", display_name="Hadley Fox"
    )

    response = client.get(reverse("search:suggest"), {"q": "had"})

    assert response.status_code == 200
    assert game.get_absolute_url().encode() in response.content
    assert person.get_absolute_url().encode() in response.content


def test_suggest_excludes_private_people(client: Client) -> None:
    hidden = User.objects.create_user(
        email="h@example.com", password="x", display_name="Hidden Hades", profile_public=False
    )
    response = client.get(reverse("search:suggest"), {"q": "hades"})
    assert hidden.get_absolute_url().encode() not in response.content


def test_suggest_blank_query_is_empty(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:suggest"), {"q": ""})
    assert response.status_code == 200
    assert b"Hades" not in response.content
