"""Step 2 of the declare funnel — the rest of the credit, still no account."""

import pytest
from django.test import Client
from django.urls import reverse

from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Company, Game

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
    # The employer field partial is shared with the credit form
    # (contributions/_employer_field.html); a {# ... #} comment there that
    # spans more than one line is not lexed as a comment and leaks into the page.
    assert b"{#" not in response.content


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
    assert response.context["form"].errors  # the missing fields are reported
    assert SESSION_KEY in client.session
    assert "discipline" not in client.session[SESSION_KEY]


def test_the_game_is_taken_from_the_session_not_the_post(client: Client, game: Game) -> None:
    """The dispatch guard's contract is "the game is fixed by step 1" — a
    crafted POST must not be able to swap it."""
    other = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    _with_game(client, game)

    client.post(
        reverse("contributions:declare_details"),
        {
            "game": str(other.pk),
            "discipline": str(Discipline.objects.get(name="Design").pk),
            "job_title": "Level Designer",
            "start_date": "2020-01",
        },
    )

    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_repicking_the_same_game_does_not_render_none_as_the_employer(
    client: Client, game: Game
) -> None:
    """Step 2 is unbound with `initial` taken from the session draft, so
    `form["company"].value()` is a pk string while `form.instance` is a
    fresh, unsaved Contribution() — rendering `form.instance.company` prints
    the literal "None" instead of the employer's name. Reachable by the path
    the funnel designs for: fill step 2 with an employer, click "Wrong
    game?", re-pick the SAME game — which deliberately preserves `company` —
    and land back on step 2."""
    company = Company.objects.create(name="Silver Forge Games", source=Company.Source.MANUAL)
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk), "company": str(company.pk)}
    session.save()

    client.post(reverse("contributions:declare"), {"game": str(game.pk)})  # re-pick the same game
    response = client.get(reverse("contributions:declare_details"))

    assert b"Silver Forge Games" in response.content
    assert b">None<" not in response.content


def test_a_deleted_game_redirects_to_the_question(client: Client, game: Game) -> None:
    """A game removed between steps 1 and 2 must not render "On ." or feed a
    broken /games//employers/ URL to the JS."""
    _with_game(client, game)
    game.delete()

    response = client.get(reverse("contributions:declare_details"))

    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare")
