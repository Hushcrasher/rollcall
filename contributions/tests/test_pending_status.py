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
from games.models import Company, Game

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
    """Logged in as the owner: they're who would most expect to see their own
    credit, so this is the stronger version of the assertion — a pending
    credit is invisible even to its own author."""
    client.force_login(pending.user)
    body = client.get(pending.user.get_absolute_url()).content  # ty: ignore[unresolved-attribute]
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_game_page(client: Client, pending: Contribution) -> None:
    body = client.get(pending.game.get_absolute_url()).content  # ty: ignore[unresolved-attribute]
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_company_page(client: Client) -> None:
    user = User.objects.create_user(email="cp@example.com", password="x", display_name="CP")
    game = Game.objects.create(title="Company Page Game", source=Game.Source.MANUAL)
    company = Company.objects.create(name="Pending Employer", source=Company.Source.MANUAL)
    Contribution.objects.create(
        user=user,
        game=game,
        company=company,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2020, 1, 1),
        status=Contribution.Status.PENDING,
    )
    body = client.get(company.get_absolute_url()).content
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_sitemap(client: Client, pending: Contribution) -> None:
    response = client.get(reverse("sitemap"))
    assert b"Level Designer" not in response.content


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
    """The token folds `email_verified_at` into its hash
    (accounts.tokens.EmailVerificationTokenGenerator), so it stops checking
    out the moment verification sets that field — the second hit lands on the
    invalid-link page rather than silently re-running the publish. The credit
    must stay active either way — this pins that the flip is not undone."""
    url = _verify_url(pending.user)  # ty: ignore[invalid-argument-type]
    client.get(url)
    second = client.get(url)
    assert b"This link is invalid or has expired" in second.content
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
