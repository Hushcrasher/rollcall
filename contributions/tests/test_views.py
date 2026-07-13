"""Contribution CRUD + the email-verified gate (design non-negotiable #6)."""

from datetime import date
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Some Game", source=Game.Source.MANUAL)


@pytest.fixture
def discipline() -> Discipline:
    return Discipline.objects.get(name="Programming")


@pytest.fixture
def verified_user() -> User:
    return User.objects.create_user(
        email="verified@example.com",
        password="x",
        display_name="Verified",
        email_verified_at=timezone.now(),
    )


def _post_data(game: Game, discipline: Discipline, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "game": game.pk,
        "company": "",
        "discipline": discipline.pk,
        "job_title": "Gameplay Programmer",
        "start_date": "2021-03",
        "end_date": "",
    }
    data.update(overrides)
    return data


def test_create_requires_login(client: Client) -> None:
    assert client.get(reverse("contributions:create")).status_code == 302


def test_unverified_user_is_blocked_from_creating(
    client: Client, game: Game, discipline: Discipline
) -> None:
    unverified = User.objects.create_user(
        email="unverified@example.com", password="x", display_name="Unverified"
    )
    client.force_login(unverified)

    get_response = client.get(reverse("contributions:create"))
    post_response = client.post(reverse("contributions:create"), _post_data(game, discipline))

    assert get_response.status_code == 302  # bounced to the verification notice
    assert reverse("accounts:verification_sent") in get_response.url
    assert Contribution.objects.count() == 0  # POST created nothing
    assert post_response.status_code == 302


def test_verified_user_can_create_a_credit(
    client: Client, verified_user: User, game: Game, discipline: Discipline
) -> None:
    client.force_login(verified_user)

    response = client.post(reverse("contributions:create"), _post_data(game, discipline))

    assert response.status_code == 302
    contribution = Contribution.objects.get()
    assert contribution.user == verified_user
    assert contribution.game == game
    assert contribution.start_date == date(2021, 3, 1)


def test_multiple_credits_on_the_same_game_are_allowed(
    client: Client, verified_user: User, game: Game, discipline: Discipline
) -> None:
    client.force_login(verified_user)
    client.post(reverse("contributions:create"), _post_data(game, discipline, start_date="2018-01"))
    client.post(reverse("contributions:create"), _post_data(game, discipline, start_date="2021-06"))

    assert Contribution.objects.filter(user=verified_user, game=game).count() == 2


def test_owner_can_edit_their_credit(
    client: Client, verified_user: User, game: Game, discipline: Discipline
) -> None:
    contribution = Contribution.objects.create(
        user=verified_user,
        game=game,
        discipline=discipline,
        job_title="Old",
        start_date=date(2020, 1, 1),
    )
    client.force_login(verified_user)

    client.post(
        reverse("contributions:edit", kwargs={"pk": contribution.pk}),
        _post_data(game, discipline, job_title="New Title"),
    )

    contribution.refresh_from_db()
    assert contribution.job_title == "New Title"


def test_non_owner_cannot_edit(
    client: Client, verified_user: User, game: Game, discipline: Discipline
) -> None:
    contribution = Contribution.objects.create(
        user=verified_user,
        game=game,
        discipline=discipline,
        job_title="Mine",
        start_date=date(2020, 1, 1),
    )
    intruder = User.objects.create_user(
        email="intruder@example.com",
        password="x",
        display_name="Intruder",
        email_verified_at=timezone.now(),
    )
    client.force_login(intruder)

    response = client.get(reverse("contributions:edit", kwargs={"pk": contribution.pk}))

    assert response.status_code == 404  # not in the intruder's queryset


def test_owner_can_delete_their_credit(
    client: Client, verified_user: User, game: Game, discipline: Discipline
) -> None:
    contribution = Contribution.objects.create(
        user=verified_user,
        game=game,
        discipline=discipline,
        job_title="X",
        start_date=date(2020, 1, 1),
    )
    client.force_login(verified_user)

    response = client.post(reverse("contributions:delete", kwargs={"pk": contribution.pk}))

    assert response.status_code == 302
    assert not Contribution.objects.filter(pk=contribution.pk).exists()
