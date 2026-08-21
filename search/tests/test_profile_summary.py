"""profile_summary(): the career aggregate the search cards and the OG cards
share. Active credits only — the display rule everywhere (docs/00 #7)."""

from datetime import date

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game
from search.services import profile_summary

pytestmark = pytest.mark.django_db


def _user() -> User:
    return User.objects.create_user(email="s@example.com", password="x", display_name="S")


def _credit(
    user: User, title: str, start: date, end: date | None, status: str = Contribution.Status.ACTIVE
) -> None:
    Contribution.objects.create(
        user=user,
        game=Game.objects.create(title=title, source=Game.Source.MANUAL),
        discipline=Discipline.objects.get(name="Design"),
        job_title="Designer",
        start_date=start,
        end_date=end,
        status=status,
    )


def test_no_active_credit_means_no_summary() -> None:
    user = _user()
    _credit(user, "Pending Game", date(2020, 1, 1), None, status=Contribution.Status.PENDING)
    assert profile_summary(user) is None


def test_counts_games_distinctly_and_reads_present_from_an_open_end() -> None:
    user = _user()
    _credit(user, "A", date(2016, 3, 1), date(2018, 1, 1))
    _credit(user, "B", date(2019, 1, 1), None)
    s = profile_summary(user)
    assert s is not None
    assert (s.credits_count, s.games_count, s.first_year, s.last_year) == (2, 2, 2016, None)
    assert s.years_label == "2016–present"


def test_closed_career_reads_the_last_year() -> None:
    user = _user()
    _credit(user, "A", date(2010, 1, 1), date(2012, 6, 1))
    s = profile_summary(user)
    assert s is not None and s.years_label == "2010–2012"
