"""Schema constraints on the core table — docs/04-DATABASE-SCHEMA.md §7–9."""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from contributions.models import Contribution, Discipline, Vouch
from games.models import Company, Game

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(email="dev@example.com", password="x", display_name="Dev")


@pytest.fixture
def game():
    return Game.objects.create(title="Some Game", source=Game.Source.MANUAL)


@pytest.fixture
def discipline():
    return Discipline.objects.get(name="Programming")


@pytest.mark.django_db
def test_disciplines_seeded_by_migration():
    names = list(Discipline.objects.values_list("name", flat=True))
    assert len(names) == 11
    assert names[0] == "Programming"  # ordered by sort_order
    assert "Support/Other" in names


@pytest.mark.django_db
def test_end_date_before_start_date_rejected(user, game, discipline):
    with pytest.raises(IntegrityError):
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=discipline,
            job_title="Dev",
            start_date=date(2020, 5, 1),
            end_date=date(2019, 1, 1),
        )


@pytest.mark.django_db
def test_game_and_company_both_null_rejected(user, discipline):
    with pytest.raises(IntegrityError):
        Contribution.objects.create(
            user=user,
            game=None,
            company=None,
            discipline=discipline,
            job_title="Dev",
            start_date=date(2020, 1, 1),
        )


@pytest.mark.django_db
def test_company_only_contribution_allowed_at_schema_level(user, discipline):
    """Future 'unannounced project at company C' — POC forms still require a game."""
    company = Company.objects.create(name="Some Studio", source=Company.Source.MANUAL)
    contribution = Contribution.objects.create(
        user=user,
        game=None,
        company=company,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    assert contribution.pk


@pytest.mark.django_db
def test_multiple_contributions_per_user_game_allowed(user, game, discipline):
    """Promotion mid-project, left and came back — a feature, not a bug."""
    for start in (date(2018, 1, 1), date(2021, 6, 1)):
        Contribution.objects.create(
            user=user, game=game, discipline=discipline, job_title="Dev", start_date=start
        )
    assert Contribution.objects.filter(user=user, game=game).count() == 2


@pytest.mark.django_db
def test_game_with_contributions_is_protected(user, game, discipline):
    Contribution.objects.create(
        user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )
    with pytest.raises(ProtectedError):
        game.delete()


@pytest.mark.django_db
def test_vouch_unique_per_voter_but_anonymized_duplicates_allowed(user, game, discipline):
    voter = User.objects.create_user(email="v@example.com", password="x", display_name="Voter")
    contribution = Contribution.objects.create(
        user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )
    Vouch.objects.create(contribution=contribution, voter=voter)

    with pytest.raises(IntegrityError), transaction.atomic():
        Vouch.objects.create(contribution=contribution, voter=voter)

    # Anonymized vouches (voter NULL) are exempt from the unique constraint.
    Vouch.objects.create(contribution=contribution, voter=None)
    Vouch.objects.create(contribution=contribution, voter=None)
    assert contribution.vouches.count() == 3
