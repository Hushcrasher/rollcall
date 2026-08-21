"""CardData builders pin what a card may ever show (spec §2): the profile
card's stats come from search.profile_summary so the two surfaces never
disagree, and the game card counts public people only."""

from datetime import date
from typing import Any

import pytest

from accounts.models import User
from cards.data import default_card, game_card, profile_card, token
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _user(**kw: Any) -> User:
    defaults: dict[str, Any] = {
        "email": "p@example.com",
        "password": "x",
        "display_name": "Sasha Haddad",
    }
    defaults.update(kw)
    return User.objects.create_user(**defaults)


def _credit(user: User, game: Game, job: str, start: date, end: date | None) -> None:
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title=job,
        start_date=start,
        end_date=end,
    )


def test_profile_card_maps_name_latest_job_stats_location_badge() -> None:
    user = _user(open_to_work=True, location="Lyon", country="FR")
    g1 = Game.objects.create(title="A", source=Game.Source.MANUAL)
    g2 = Game.objects.create(title="B", source=Game.Source.MANUAL)
    _credit(user, g1, "Junior Designer", date(2016, 1, 1), date(2018, 1, 1))
    _credit(user, g2, "Tools Programmer", date(2019, 1, 1), None)
    data = profile_card(user)
    assert data.kind == "profile" and data.title == "Sasha Haddad"
    assert data.subtitle == "Tools Programmer"
    assert data.stats == "2 credits · 2 games · 2016–present"
    assert data.footer == user.location_display and "Lyon" in data.footer
    assert data.badge == "Open to work"


def test_profile_card_without_credits_has_no_stats() -> None:
    data = profile_card(_user())
    assert data.subtitle == "" and data.stats == "" and data.badge == ""


def test_game_card_counts_public_people_only() -> None:
    game = Game.objects.create(
        title="Lost Depths", source=Game.Source.MANUAL, release_date=date(2021, 5, 1)
    )
    _credit(_user(email="a@example.com"), game, "Artist", date(2020, 1, 1), None)
    _credit(
        _user(email="b@example.com", profile_public=False), game, "Artist", date(2020, 1, 1), None
    )
    data = game_card(game)
    assert data.title == "Lost Depths" and data.subtitle == "Released 2021"
    assert data.stats == "1 person credited on Rollcall"


def test_game_card_with_nobody_invites_the_first_claim() -> None:
    game = Game.objects.create(title="Empty", source=Game.Source.MANUAL)
    assert game_card(game).stats == "Be the first to claim a credit"


def test_token_changes_with_the_data() -> None:
    a = default_card()
    assert len(token(a)) == 10
    assert token(a) != token(profile_card(_user()))
