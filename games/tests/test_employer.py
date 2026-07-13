"""Employer field helpers — the game's studios as quick-picks + create-company."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Company, Game, GameCompany

pytestmark = pytest.mark.django_db


def test_game_employers_lists_the_games_companies(client: Client) -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    pub = Company.objects.create(name="Private Division", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)
    GameCompany.objects.create(game=game, company=pub, role=GameCompany.Role.PUBLISHER)

    response = client.get(reverse("games:game_employers", kwargs={"pk": game.pk}))

    assert response.status_code == 200
    assert b"Supergiant Games" in response.content
    assert b"Private Division" in response.content
    assert f'data-id="{dev.pk}"'.encode() in response.content
    assert b"another company" in response.content.lower()  # the "other" fallback


def test_game_employers_dedupes_a_company_with_multiple_roles(client: Client) -> None:
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    studio = Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.PUBLISHER)

    response = client.get(reverse("games:game_employers", kwargs={"pk": game.pk}))

    assert response.content.count(f'data-id="{studio.pk}"'.encode()) == 1


def test_company_create_requires_login(client: Client) -> None:
    assert client.post(reverse("games:company_create"), {"name": "Virtuos"}).status_code == 302


def test_company_create_makes_a_manual_company_and_returns_json(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)

    response = client.post(reverse("games:company_create"), {"name": "Virtuos"})

    assert response.status_code == 200
    company = Company.objects.get(name="Virtuos")
    assert company.source == Company.Source.MANUAL
    assert response.json() == {"id": company.pk, "label": "Virtuos"}


def test_company_create_is_idempotent(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    client.post(reverse("games:company_create"), {"name": "Virtuos"})
    client.post(reverse("games:company_create"), {"name": "Virtuos"})
    assert Company.objects.filter(name="Virtuos").count() == 1
