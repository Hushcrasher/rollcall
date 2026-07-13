"""seed_demo_people — populate the people side on top of real games (dev only)."""

import pytest
from django.core.management import call_command

from accounts.models import User
from contributions.models import Contribution
from games.models import Company, Game, GameCompany


@pytest.mark.django_db
def test_creates_verified_people_with_credits_on_existing_games() -> None:
    game = Game.objects.create(title="Real Game", steam_positive_pct=90, source=Game.Source.MANUAL)
    studio = Company.objects.create(name="Real Studio", source=Company.Source.SEED)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)

    call_command("seed_demo_people", "--people", "8", "--max-credits", "3")

    people = User.objects.filter(email__startswith="demo")
    assert people.count() == 8
    assert all(p.is_email_verified for p in people)  # can already be searched/credited
    # Every credit is on the pre-existing real game (no fake games created).
    assert Game.objects.count() == 1
    assert Contribution.objects.exists()
    assert all(c.game == game for c in Contribution.objects.all())


@pytest.mark.django_db
def test_is_idempotent() -> None:
    Game.objects.create(title="Real Game", steam_positive_pct=90, source=Game.Source.MANUAL)
    call_command("seed_demo_people", "--people", "5", "--max-credits", "2")
    call_command("seed_demo_people", "--people", "5", "--max-credits", "2")
    assert User.objects.filter(email__startswith="demo").count() == 5
