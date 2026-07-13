"""htmx autocomplete endpoints — return HTML fragments of matching options."""

from typing import Any

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


def test_game_autocomplete_offers_igdb_when_configured(client: Client, settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"
    response = client.get(reverse("search:game_autocomplete"), {"q": "obscure"})
    assert b"igdb/search" in response.content  # inline "Search IGDB" fallback


def test_game_autocomplete_hides_igdb_when_unconfigured(client: Client) -> None:
    # No IGDB creds in the default test settings.
    response = client.get(reverse("search:game_autocomplete"), {"q": "obscure"})
    assert b"igdb/search" not in response.content
