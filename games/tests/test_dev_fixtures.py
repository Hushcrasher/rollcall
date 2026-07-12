"""The dev-fixtures command is the contributor onboarding path — it must work
and stay idempotent (docs/02-ARCHITECTURE.md §6)."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from contributions.models import Contribution
from games.models import Company, Game

pytestmark = pytest.mark.django_db


def test_load_dev_fixtures_is_idempotent():
    args = ["--games", "30", "--users", "8", "--contributions", "20"]
    call_command("load_dev_fixtures", *args)

    counts = (
        Game.objects.count(),
        Company.objects.count(),
        get_user_model().objects.count(),
        Contribution.objects.count(),
    )
    assert counts[0] == 30
    assert counts[2] == 8 + 1  # +1 dev admin

    call_command("load_dev_fixtures", *args)  # second run adds nothing

    assert counts == (
        Game.objects.count(),
        Company.objects.count(),
        get_user_model().objects.count(),
        Contribution.objects.count(),
    )
