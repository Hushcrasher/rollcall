"""Account deletion — non-negotiable test zone #3 (docs/02-ARCHITECTURE.md §7).

GDPR map (docs/04-DATABASE-SCHEMA.md §14): contributions CASCADE, vouches
emitted anonymized (voter SET NULL), vouches received die with the
contribution, contact requests SET NULL both directions, reports SET NULL.
"""

from datetime import date

import pytest
from django.contrib.auth import get_user_model

from contact.models import ContactRequest, Report
from contributions.models import Contribution, Discipline, Vouch
from games.models import Game

User = get_user_model()


@pytest.fixture
def users():
    alice = User.objects.create_user(email="alice@example.com", password="x", display_name="Alice")
    bob = User.objects.create_user(email="bob@example.com", password="x", display_name="Bob")
    return alice, bob


@pytest.fixture
def game():
    return Game.objects.create(title="Test Game", source=Game.Source.MANUAL)


@pytest.fixture
def discipline():
    return Discipline.objects.get(name="Programming")  # seeded by data migration


@pytest.mark.django_db
def test_contributions_cascade_on_delete(users, game, discipline):
    alice, bob = users
    own = Contribution.objects.create(
        user=alice, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )
    others = Contribution.objects.create(
        user=bob, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )

    alice.delete()

    assert not Contribution.objects.filter(pk=own.pk).exists()
    assert Contribution.objects.filter(pk=others.pk).exists()  # third parties untouched


@pytest.mark.django_db
def test_vouches_emitted_are_anonymized_not_deleted(users, game, discipline):
    alice, bob = users
    bobs_contribution = Contribution.objects.create(
        user=bob, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )
    emitted = Vouch.objects.create(contribution=bobs_contribution, voter=alice)

    alice.delete()

    emitted.refresh_from_db()
    assert emitted.voter is None  # anonymized — Bob's trust graph preserved


@pytest.mark.django_db
def test_vouches_received_die_with_the_contribution(users, game, discipline):
    alice, bob = users
    alices_contribution = Contribution.objects.create(
        user=alice, game=game, discipline=discipline, job_title="Dev", start_date=date(2020, 1, 1)
    )
    received = Vouch.objects.create(contribution=alices_contribution, voter=bob)

    alice.delete()

    assert not Vouch.objects.filter(pk=received.pk).exists()


@pytest.mark.django_db
def test_contact_requests_anonymized_both_directions(users):
    alice, bob = users
    sent = ContactRequest.objects.create(sender=alice, recipient=bob, subject="s", message="m")
    received = ContactRequest.objects.create(sender=bob, recipient=alice, subject="s", message="m")

    alice.delete()

    sent.refresh_from_db()
    received.refresh_from_db()
    assert sent.sender is None and sent.recipient == bob  # abuse trail kept, anonymized
    assert received.recipient is None and received.sender == bob


@pytest.mark.django_db
def test_reports_keep_anonymized_trail(users):
    alice, _ = users
    report = Report.objects.create(
        reporter=alice, target_type=Report.TargetType.OTHER, reason="spam"
    )

    alice.delete()

    report.refresh_from_db()
    assert report.reporter is None
    assert report.reason == "spam"
