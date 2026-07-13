"""The person page lists the user's active credits (docs/01-DESIGN.md §3.3)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_profile_lists_active_credits(client: Client, user: User) -> None:
    game = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2018, 1, 1),
    )
    response = client.get(reverse("accounts:profile", kwargs={"slug": user.slug}))
    assert b"Level Designer" in response.content
    assert b"Celeste" in response.content


def test_profile_omits_non_active_credits(client: Client, user: User) -> None:
    game = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Secret Role",
        start_date=date(2018, 1, 1),
        status=Contribution.Status.DISPUTED,
    )
    response = client.get(reverse("accounts:profile", kwargs={"slug": user.slug}))
    assert b"Secret Role" not in response.content
