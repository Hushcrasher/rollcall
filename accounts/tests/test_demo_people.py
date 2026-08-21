"""seed_demo_people — populate the people side on top of catalog games (dev only)."""

from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from contributions.models import Contribution
from games.models import Company, Game, GameCompany


@pytest.fixture(autouse=True)
def _debug_on(settings: Any) -> None:
    """The command refuses to run outside DEBUG (it creates accounts with a
    published password) and test settings are DEBUG=False, so every run here
    has to opt in. The guard's own test flips it back."""
    settings.DEBUG = True


@pytest.mark.django_db
def test_refuses_to_create_demo_accounts_outside_debug(settings: Any) -> None:
    """demo{i}@example.com / "demopass" is a published credential pair once the
    repo is public; DEBUG is the only signal separating a contributor's box
    from a live database, so the command must fail closed."""
    settings.DEBUG = False
    Game.objects.create(title="Catalog Game", steam_positive_pct=90, source=Game.Source.MANUAL)

    with pytest.raises(CommandError):
        call_command("seed_demo_people", "--people", "3")

    assert not User.objects.filter(email__startswith="demo").exists()
    assert not Contribution.objects.exists()  # the guard runs before any write


@pytest.mark.django_db
def test_creates_verified_people_with_credits_on_existing_games() -> None:
    game = Game.objects.create(
        title="Catalog Game", steam_positive_pct=90, source=Game.Source.MANUAL
    )
    studio = Company.objects.create(name="Catalog Studio", source=Company.Source.SEED)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)

    call_command("seed_demo_people", "--people", "8", "--max-credits", "3")

    people = User.objects.filter(email__startswith="demo")
    assert people.count() == 8
    assert all(p.is_email_verified for p in people)  # can already be searched/credited
    # Every credit is on the pre-existing catalog game (no fake games created).
    assert Game.objects.count() == 1
    assert Contribution.objects.exists()
    assert all(c.game == game for c in Contribution.objects.all())


@pytest.mark.django_db
def test_is_idempotent() -> None:
    Game.objects.create(title="Catalog Game", steam_positive_pct=90, source=Game.Source.MANUAL)
    call_command("seed_demo_people", "--people", "5", "--max-credits", "2")
    call_command("seed_demo_people", "--people", "5", "--max-credits", "2")
    assert User.objects.filter(email__startswith="demo").count() == 5
