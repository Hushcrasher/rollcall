"""The dev-fixtures command is the contributor onboarding path — it must work
and stay idempotent (docs/02-ARCHITECTURE.md §6)."""

import random
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django_countries.fields import Country

from accounts.models import User
from contributions.models import Contribution
from games.management.commands.load_dev_fixtures import CITIES, COUNTRY_CODES, Command
from games.models import Company, Game

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _debug_on(settings: Any) -> None:
    """The command refuses to run outside DEBUG (it creates a known superuser)
    and test settings are DEBUG=False, so every run here has to opt in. The
    guard's own test flips it back."""
    settings.DEBUG = True


def test_refuses_to_create_the_dev_superuser_outside_debug(settings: Any) -> None:
    """admin@example.com / "admin" is a published credential pair once the repo
    is public; DEBUG is the only thing separating a contributor's box from a
    live database, so the command must fail closed rather than create it."""
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("load_dev_fixtures", games=1, users=1, contributions=1)

    assert not User.objects.filter(email="admin@example.com").exists()
    assert not Game.objects.exists()  # the guard runs before any row is written


def test_load_dev_fixtures_is_idempotent() -> None:
    args = ["--games", "30", "--users", "8", "--contributions", "20"]
    call_command("load_dev_fixtures", *args)

    counts = (
        Game.objects.count(),
        Company.objects.count(),
        User.objects.count(),
        Contribution.objects.count(),
    )
    assert counts[0] == 30
    assert counts[2] == 8 + 1  # +1 dev admin

    call_command("load_dev_fixtures", *args)  # second run adds nothing

    assert counts == (
        Game.objects.count(),
        Company.objects.count(),
        User.objects.count(),
        Contribution.objects.count(),
    )


def test_create_users_rng_consumption_is_independent_of_existing_rows() -> None:
    """THE invariant of this file: a draw must not depend on DB state. If one
    moves inside `if created:`, a re-run consumes a different number of values
    and every later draw shifts — silently changing "deterministic" data.
    Asserted directly on the rng state, not inferred from downstream row
    counts (which catch it only incidentally, via drift)."""
    command = Command()
    first = random.Random(42)
    command._create_users(first, 10)  # rows created
    expected_state = first.getstate()

    second = random.Random(42)
    command._create_users(second, 10)  # rows already exist
    assert second.getstate() == expected_state


@pytest.mark.parametrize("code", COUNTRY_CODES)
def test_country_codes_constant_is_valid_iso(code: str) -> None:
    """CountryField validation only runs via full_clean()/forms — get_or_create
    persists a bogus code silently, and an invalid code is truthy with an empty
    .name. Catches the plausible mistake: "UK" instead of the ISO "GB"."""
    assert Country(code).name


def test_fixture_users_get_countries_and_cities() -> None:
    """~80% of devusers get a country, and cities come from CITIES with at
    least one set. The country half is a range, not a literal, so the test
    isn't glued to one seed's exact roll count. The city half is what stops
    the `location` draw from being dropped entirely — nothing else here
    would notice, and Task 7 renders it."""
    call_command("load_dev_fixtures", games=5, users=40, contributions=5)
    devusers = User.objects.filter(email__startswith="devuser")

    fraction = devusers.exclude(country="").count() / devusers.count()
    assert 0.65 <= fraction <= 0.95

    cities = {user.location for user in devusers}
    assert cities <= set(CITIES)
    assert cities - {""}
