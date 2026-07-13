"""htmx autocomplete endpoints — return HTML fragments of matching options."""

import pytest
from django.test import Client
from django.urls import reverse

from games.models import Company, Game

pytestmark = pytest.mark.django_db


def test_game_autocomplete_returns_matching_options(client: Client) -> None:
    Game.objects.create(title="Hades", igdb_id=1, source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", igdb_id=2, source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_autocomplete"), {"q": "hade"})

    assert response.status_code == 200
    assert b"Hades" in response.content
    assert b"Celeste" not in response.content


def test_game_autocomplete_blank_query_is_empty(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_autocomplete"), {"q": ""})
    assert response.status_code == 200
    assert b"Hades" not in response.content


def test_company_autocomplete_returns_matching_options(client: Client) -> None:
    Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)

    response = client.get(reverse("search:company_autocomplete"), {"q": "super"})

    assert response.status_code == 200
    assert b"Supergiant Games" in response.content
