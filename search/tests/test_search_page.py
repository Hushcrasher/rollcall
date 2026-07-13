"""Public search page — games + public people, open to all, no full listing."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Company, Game

pytestmark = pytest.mark.django_db


def test_search_finds_companies(client: Client) -> None:
    company = Company.objects.create(name="Hadron Studios", source=Company.Source.MANUAL)
    response = client.get(reverse("search:search"), {"q": "hadron"})
    assert company.get_absolute_url().encode() in response.content


def test_search_finds_games(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:search"), {"q": "hade"})
    assert response.status_code == 200
    assert b"Hades" in response.content


def test_search_finds_public_people(client: Client) -> None:
    User.objects.create_user(email="a@example.com", password="x", display_name="Ada Lovelace")
    response = client.get(reverse("search:search"), {"q": "lovelace"})
    assert b"Ada Lovelace" in response.content


def test_search_excludes_private_people(client: Client) -> None:
    hidden = User.objects.create_user(
        email="h@example.com", password="x", display_name="Hidden Person", profile_public=False
    )
    response = client.get(reverse("search:search"), {"q": "Hidden Person"})
    # The query is echoed in the input, so check the profile link is absent,
    # not the raw name string.
    profile_path = reverse("accounts:profile", kwargs={"slug": hidden.slug})
    assert profile_path.encode() not in response.content
    assert b"No people found" in response.content


def test_search_never_leaks_email(client: Client) -> None:
    User.objects.create_user(email="findme@example.com", password="x", display_name="Findable")
    response = client.get(reverse("search:search"), {"q": "Findable"})
    assert b"findme@example.com" not in response.content


def test_empty_query_lists_nothing(client: Client) -> None:
    """Anti-scraping: no exhaustive listing — a blank search shows no results."""
    User.objects.create_user(email="a@example.com", password="x", display_name="Somebody")
    Game.objects.create(title="Some Game", source=Game.Source.MANUAL)

    response = client.get(reverse("search:search"))

    assert response.status_code == 200
    assert b"Somebody" not in response.content
    assert b"Some Game" not in response.content
