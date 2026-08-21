"""Where a credit happened (spec 2026-08-21-credit-form-v2 §2): optional,
asked in the form, shown after the dates, exported with the member's data."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from contributions.forms import ContributionForm
from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db

# Same shape as contributions/tests/test_declare_account.py's SIGNUP — step 3
# needs a fresh signup to turn the draft into a row.
SIGNUP = {
    "email": "funnel-country@example.com",
    "display_name": "Funnel Country",
    "password1": "a-strong-passphrase-42",
    "password2": "a-strong-passphrase-42",
    "consent": "on",
}


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


def _step2_post(game: Game, discipline: Discipline, **overrides: str) -> dict[str, str]:
    data = {
        "game": str(game.pk),
        "discipline": str(discipline.pk),
        "job_title": "Level Designer",
        "start_date": "2020-01",
        "end_date": "",
        "country": "FR",
    }
    data.update(overrides)
    return data


def test_the_funnel_keeps_the_credit_s_country(
    client: Client, game: Game, discipline: Discipline
) -> None:
    """Walks the real three steps — not test_declare_account.py's `_with_draft`
    session shortcut, which never invokes DeclareDetailsView.form_valid or
    DeclareAccountView._save_credit, so it can't catch either dropping a field.
    Regression: `contributions.funnel.CREDIT_FIELDS` (the whitelist step 2
    copies the POST through, and step 3 rebuilds ContributionForm from) didn't
    list `country`, so every funnel credit was saved with an empty country."""
    step1 = client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    assert step1.status_code == 302

    step2 = client.post(reverse("contributions:declare_details"), _step2_post(game, discipline))
    assert step2.status_code == 302
    assert step2["Location"] == reverse("contributions:declare_account")
    assert client.session[SESSION_KEY]["country"] == "FR"

    step3 = client.post(reverse("contributions:declare_account"), SIGNUP)
    assert step3.status_code == 302

    assert Contribution.objects.get().country.code == "FR"


def test_bouncing_back_to_details_re_fills_the_country(
    client: Client, game: Game, discipline: Discipline
) -> None:
    """DeclareDetailsView.get_initial dumps the whole session draft as the
    form's initial values (contributions/views.py) — once `country` survives
    in the draft, it must come back pre-selected like every other field
    rather than reset to the blank choice."""
    client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    client.post(reverse("contributions:declare_details"), _step2_post(game, discipline))

    response = client.get(reverse("contributions:declare_details"))

    assert response.status_code == 200
    assert response.context["form"]["country"].value() == "FR"
