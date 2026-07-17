"""Public "For recruiters" page — honest copy, real counts, open to all."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


def test_landing_is_public(client: Client) -> None:
    assert client.get(reverse("search:recruiters_landing")).status_code == 200


def test_landing_shows_real_counts(client: Client) -> None:
    """Honest numbers — no inflated counters (docs/01-DESIGN.md §3.6)."""
    User.objects.create_user(email="a@example.com", password="x", display_name="A")
    User.objects.create_user(
        email="b@example.com", password="x", display_name="B", profile_public=False
    )
    Game.objects.create(title="G1", source=Game.Source.MANUAL)
    Game.objects.create(title="G2", source=Game.Source.MANUAL)

    response = client.get(reverse("search:recruiters_landing"))

    assert response.context["public_profiles"] == 1  # the private one isn't counted
    assert response.context["games"] == 2


def test_landing_links_to_apply(client: Client) -> None:
    response = client.get(reverse("search:recruiters_landing"))
    assert reverse("accounts:recruiter_apply").encode() in response.content


def test_landing_links_to_the_open_search(client: Client) -> None:
    response = client.get(reverse("search:recruiters_landing"))
    assert reverse("search:recruiter_search").encode() in response.content
