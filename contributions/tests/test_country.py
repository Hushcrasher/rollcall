"""Where a credit happened (spec 2026-08-21-credit-form-v2 §2): optional,
asked in the form, shown after the dates, exported with the member's data."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from contributions.forms import ContributionForm
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hades", source=Game.Source.MANUAL)


@pytest.fixture
def discipline() -> Discipline:
    return Discipline.objects.get(name="Programming")


def test_form_saves_the_country(game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    form = ContributionForm(
        data={
            "game": game.pk,
            "discipline": discipline.pk,
            "job_title": "Dev",
            "start_date": "08/2024",
            "country": "FR",
        }
    )
    assert form.is_valid(), form.errors
    credit = form.save(commit=False)
    credit.user = user
    credit.save()
    assert Contribution.objects.get(pk=credit.pk).country.code == "FR"


def test_country_is_optional(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(
        data={
            "game": game.pk,
            "discipline": discipline.pk,
            "job_title": "Dev",
            "start_date": "08/2024",
        }
    )
    assert form.is_valid(), form.errors


def test_profile_and_game_lines_show_the_country(
    client: Client, game: Game, discipline: Discipline
) -> None:
    user = User.objects.create_user(
        email="c@example.com", password="x", display_name="Country Person"
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2024, 8, 1),
        country="FR",
    )
    assert (
        "08/2024 – present · France"
        in client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    )
    assert "· France" in client.get(reverse("games:game", args=[game.slug])).content.decode()


def test_export_includes_the_country(client: Client, game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(
        email="c@example.com", password="x", display_name="C", email_verified_at=timezone.now()
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2024, 8, 1),
        country="FR",
    )
    client.force_login(user)
    data = client.get(reverse("accounts:export_data")).json()
    assert data["contributions"][0]["country"] == "FR"
