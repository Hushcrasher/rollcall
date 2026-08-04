"""Account page — email verification, data export, deletion. Nothing else:
the profile fields live on /profile/edit/ (docs/superpowers/specs/
2026-08-04-profile-account-split-design.md)."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_account_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:account"))
    assert response.status_code == 302  # redirected to login


def test_account_offers_export_and_deletion(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("accounts:export_data") in body
    assert reverse("accounts:account_delete") in body


def test_account_warns_an_unverified_email(client: Client, user: User) -> None:
    assert user.email_verified_at is None
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert b"not verified yet" in response.content


def test_verified_email_gets_no_warning(client: Client, user: User) -> None:
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert b"not verified yet" not in response.content


def test_account_carries_no_profile_form(client: Client, user: User) -> None:
    """The profile fields moved out — the page must not edit them any more.
    Asserted on the field names, not on <form>: base.html carries a logout form
    on every page."""
    client.force_login(user)
    body = client.get(reverse("accounts:account")).content
    for field in (b"display_name", b"contactable", b"profile_public", b"github_url", b"avatar"):
        assert field not in body
