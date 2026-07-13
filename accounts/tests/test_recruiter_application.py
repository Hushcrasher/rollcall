"""Recruiter application + manual approval (docs/01-DESIGN.md §3.6)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import RecruiterApplication, User

pytestmark = pytest.mark.django_db

APPLICATION = {
    "full_name": "Rita Recruiter",
    "company_name": "Studio HR",
    "work_email": "rita@studio.example",
    "linkedin_url": "https://linkedin.com/in/rita",
    "message": "We're hiring gameplay programmers.",
}


@pytest.fixture
def member() -> User:
    return User.objects.create_user(email="member@example.com", password="x", display_name="Member")


def test_apply_requires_login(client: Client) -> None:
    assert client.get(reverse("accounts:recruiter_apply")).status_code == 302


def test_member_can_apply(client: Client, member: User) -> None:
    client.force_login(member)
    response = client.post(reverse("accounts:recruiter_apply"), APPLICATION)

    application = RecruiterApplication.objects.get(user=member)
    assert application.status == RecruiterApplication.Status.PENDING
    assert application.full_name == "Rita Recruiter"
    assert response.status_code == 302


def test_cannot_file_a_second_pending_application(client: Client, member: User) -> None:
    RecruiterApplication.objects.create(user=member, **APPLICATION)
    client.force_login(member)

    client.post(reverse("accounts:recruiter_apply"), APPLICATION)

    assert RecruiterApplication.objects.filter(user=member).count() == 1


def test_approval_promotes_the_user_to_recruiter(member: User) -> None:
    admin = User.objects.create_superuser(
        email="admin@example.com", password="x", display_name="Admin"
    )
    application = RecruiterApplication.objects.create(user=member, **APPLICATION)

    application.approve(reviewer=admin)

    member.refresh_from_db()
    application.refresh_from_db()
    assert member.role == User.Role.RECRUITER
    assert member.is_recruiter is True
    assert application.status == RecruiterApplication.Status.APPROVED
    assert application.reviewed_by == admin
    assert application.reviewed_at is not None


def test_rejection_does_not_promote(member: User) -> None:
    admin = User.objects.create_superuser(
        email="admin@example.com", password="x", display_name="Admin"
    )
    application = RecruiterApplication.objects.create(user=member, **APPLICATION)

    application.reject(reviewer=admin)

    member.refresh_from_db()
    assert member.role == User.Role.MEMBER
    assert application.status == RecruiterApplication.Status.REJECTED
