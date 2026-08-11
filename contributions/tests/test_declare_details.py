"""Step 2 of the declare funnel — the rest of the credit, still no account."""

import pytest
from django.test import Client
from django.urls import reverse

from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def _with_game(client: Client, game: Game) -> None:
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk)}
    session.save()


def test_details_needs_a_game_first(client: Client) -> None:
    """A direct hit with an empty session must land on the question, not on a
    form with no game."""
    response = client.get(reverse("contributions:declare_details"))
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare")


def test_details_is_open_to_anonymous_visitors(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.get(reverse("contributions:declare_details"))
    assert response.status_code == 200
    assert b"Hollow Knight" in response.content  # the chosen game is shown back


def test_a_valid_credit_moves_to_the_account_step(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.post(
        reverse("contributions:declare_details"),
        {
            "game": str(game.pk),
            "discipline": str(Discipline.objects.get(name="Design").pk),
            "job_title": "Level Designer",
            "start_date": "2020-01",
            "end_date": "",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_account")
    assert client.session[SESSION_KEY]["job_title"] == "Level Designer"
    assert client.session[SESSION_KEY]["start_date"] == "2020-01"


def test_nothing_is_written_to_the_database(client: Client, game: Game) -> None:
    """No account exists yet — the draft lives in the session and nowhere else."""
    _with_game(client, game)
    client.post(
        reverse("contributions:declare_details"),
        {
            "game": str(game.pk),
            "discipline": str(Discipline.objects.get(name="Design").pk),
            "job_title": "Level Designer",
            "start_date": "2020-01",
        },
    )
    assert Contribution.objects.count() == 0


def test_an_invalid_credit_re_renders_with_errors(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.post(
        reverse("contributions:declare_details"),
        {"game": str(game.pk), "job_title": "", "start_date": ""},
    )
    assert response.status_code == 200
    assert SESSION_KEY in client.session
    assert "discipline" not in client.session[SESSION_KEY]
