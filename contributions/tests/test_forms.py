"""ContributionForm — month/year dates and validation (docs/01-DESIGN.md §3.3)."""

from datetime import date
from typing import Any

import pytest

from contributions.forms import ContributionForm
from contributions.models import Discipline
from games.models import Company, Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Some Game", source=Game.Source.MANUAL)


@pytest.fixture
def discipline() -> Discipline:
    return Discipline.objects.get(name="Programming")


def _data(game_obj: Game, discipline_obj: Discipline, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "game": game_obj.pk,
        "company": "",
        "discipline": discipline_obj.pk,
        "job_title": "Gameplay Programmer",
        "start_date": "2021-03",
        "end_date": "",
    }
    data.update(overrides)
    return data


def test_month_year_field_parses_to_first_of_month(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(_data(game, discipline))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["start_date"] == date(2021, 3, 1)


def test_open_end_and_no_company_are_valid(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(_data(game, discipline, end_date="", company=""))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["end_date"] is None


def test_end_before_start_is_rejected(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(_data(game, discipline, start_date="2021-05", end_date="2021-01"))
    assert not form.is_valid()
    assert "end_date" in form.errors


def test_game_is_required_in_poc(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(_data(game, discipline, game=""))
    assert not form.is_valid()
    assert "game" in form.errors


def test_optional_company_is_accepted(game: Game, discipline: Discipline) -> None:
    company = Company.objects.create(name="Virtuos", source=Company.Source.MANUAL)
    form = ContributionForm(_data(game, discipline, company=company.pk))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["company"] == company
