"""Game and company pages — same contributions table read the other way."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Company, Game, GameCompany

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(
        title="Hades", source=Game.Source.MANUAL, cover_url="https://cdn.example/hades.jpg"
    )


@pytest.fixture
def contributor() -> User:
    return User.objects.create_user(
        email="dev@example.com", password="x", display_name="Gameplay Dev"
    )


@pytest.fixture
def discipline() -> Discipline:
    return Discipline.objects.get(name="Programming")


def test_game_page_lists_its_contributors(
    client: Client, game: Game, contributor: User, discipline: Discipline
) -> None:
    Contribution.objects.create(
        user=contributor,
        game=game,
        discipline=discipline,
        job_title="Engine Programmer",
        start_date=date(2018, 1, 1),
    )
    response = client.get(reverse("games:game", kwargs={"slug": game.slug}))
    assert response.status_code == 200
    assert b"Gameplay Dev" in response.content
    assert b"Engine Programmer" in response.content


def test_game_page_never_leaks_a_contributor_email(
    client: Client, game: Game, contributor: User, discipline: Discipline
) -> None:
    Contribution.objects.create(
        user=contributor,
        game=game,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2018, 1, 1),
    )
    response = client.get(reverse("games:game", kwargs={"slug": game.slug}))
    assert b"dev@example.com" not in response.content


def test_game_page_hides_non_active_contributions(
    client: Client, game: Game, contributor: User, discipline: Discipline
) -> None:
    Contribution.objects.create(
        user=contributor,
        game=game,
        discipline=discipline,
        job_title="Hidden Role",
        start_date=date(2018, 1, 1),
        status=Contribution.Status.REMOVED,
    )
    response = client.get(reverse("games:game", kwargs={"slug": game.slug}))
    assert b"Hidden Role" not in response.content


def test_game_page_shows_cover_from_cdn(client: Client, game: Game) -> None:
    response = client.get(reverse("games:game", kwargs={"slug": game.slug}))
    assert b"https://cdn.example/hades.jpg" in response.content


def test_company_page_lists_games_and_contributors(
    client: Client, game: Game, contributor: User, discipline: Discipline
) -> None:
    studio = Company.objects.create(name="Supergiant Games", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)
    Contribution.objects.create(
        user=contributor,
        game=game,
        company=studio,
        discipline=discipline,
        job_title="Programmer",
        start_date=date(2018, 1, 1),
    )

    response = client.get(reverse("games:company", kwargs={"slug": studio.slug}))

    assert response.status_code == 200
    assert b"Hades" in response.content  # game via IGDB facts
    assert b"Gameplay Dev" in response.content  # contributor via employer


def _private_member() -> User:
    return User.objects.create_user(
        email="quiet@example.com",
        password="x",
        display_name="Private Person",
        profile_public=False,
    )


def test_game_page_hides_credits_of_private_profiles(
    client: Client, game: Game, discipline: Discipline
) -> None:
    """docs/01 §3.4: profile_public=False makes the profile invisible everywhere —
    the game page included, or flipping the switch still leaves your name on
    every game you shipped (issue #22)."""
    Contribution.objects.create(
        user=_private_member(),
        game=game,
        discipline=discipline,
        job_title="Secret Role",
        start_date=date(2018, 1, 1),
    )
    response = client.get(reverse("games:game", kwargs={"slug": game.slug}))
    assert response.status_code == 200
    assert b"Private Person" not in response.content
    assert b"Secret Role" not in response.content


def test_company_page_hides_credits_of_private_profiles(
    client: Client, game: Game, discipline: Discipline
) -> None:
    studio = Company.objects.create(name="Quiet Studio", source=Company.Source.MANUAL)
    Contribution.objects.create(
        user=_private_member(),
        game=game,
        company=studio,
        discipline=discipline,
        job_title="Secret Role",
        start_date=date(2018, 1, 1),
    )
    response = client.get(reverse("games:company", kwargs={"slug": studio.slug}))
    assert response.status_code == 200
    assert b"Private Person" not in response.content
    assert b"Secret Role" not in response.content
