"""`pending` — a credit that exists but is not published.

The deferred-registration funnel writes the credit at signup, before the email
is verified (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
What the email gate protects is that nothing unverified is *published*, so these
tests pin the invisibility, not the row.
"""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import email_verification_token
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending() -> Contribution:
    user = User.objects.create_user(email="me@example.com", password="x", display_name="Me")
    game = Game.objects.create(title="Pending Game", source=Game.Source.MANUAL)
    return Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2020, 1, 1),
        status=Contribution.Status.PENDING,
    )


def test_pending_is_absent_from_the_owner_profile(client: Client, pending: Contribution) -> None:
    body = client.get(pending.user.get_absolute_url()).content  # ty: ignore[unresolved-attribute]
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_game_page(client: Client, pending: Contribution) -> None:
    body = client.get(pending.game.get_absolute_url()).content  # ty: ignore[unresolved-attribute]
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_people_search(client: Client, pending: Contribution) -> None:
    response = client.get(
        reverse("home"),
        {"discipline": pending.discipline.pk},  # ty: ignore[unresolved-attribute]
    )
    assert b"Me" not in response.content


def test_verifying_the_email_publishes_the_pending_credit(
    client: Client, pending: Contribution
) -> None:
    user = pending.user
    url = _verify_url(user)  # ty: ignore[invalid-argument-type]

    client.get(url)

    pending.refresh_from_db()
    assert pending.status == Contribution.Status.ACTIVE
    body = client.get(user.get_absolute_url()).content  # ty: ignore[unresolved-attribute]
    assert b"Level Designer" in body


def test_verifying_twice_changes_nothing(client: Client, pending: Contribution) -> None:
    """The link is single-use, so the second hit lands on the invalid page. The
    credit must stay active either way — this pins that the flip is not undone."""
    url = _verify_url(pending.user)  # ty: ignore[invalid-argument-type]
    client.get(url)
    client.get(url)
    pending.refresh_from_db()
    assert pending.status == Contribution.Status.ACTIVE


def test_verification_without_a_pending_credit_still_works(client: Client) -> None:
    """The ordinary signup path has no pending credit — verification must not
    depend on one."""
    user = User.objects.create_user(email="plain@example.com", password="x", display_name="Plain")
    client.get(_verify_url(user))
    user.refresh_from_db()
    assert user.email_verified_at is not None


def _verify_url(user: User) -> str:
    return reverse(
        "accounts:verify_email",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": email_verification_token.make_token(user),
        },
    )
