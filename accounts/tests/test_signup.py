"""Signup — creates an unverified account, sends the verification email, and
shows the mandatory public-profile consent copy (docs/01-DESIGN.md §3.4)."""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

VALID = {
    "email": "newbie@example.com",
    "display_name": "Newbie",
    "password1": "Str0ngP@ssw0rd!",
    "password2": "Str0ngP@ssw0rd!",
    "consent": "on",
}


def test_signup_page_shows_public_consent_copy(client: Client) -> None:
    response = client.get(reverse("accounts:signup"))
    assert response.status_code == 200
    assert b"accessible to recruiters" in response.content


def test_valid_signup_creates_unverified_user_and_sends_email(client: Client) -> None:
    response = client.post(reverse("accounts:signup"), VALID)

    user = User.objects.get(email="newbie@example.com")
    assert user.display_name == "Newbie"
    assert user.email_verified_at is None  # unverified until they click the link
    assert len(mail.outbox) == 1
    assert response.status_code == 302


def test_signup_requires_consent(client: Client) -> None:
    response = client.post(reverse("accounts:signup"), {**VALID, "consent": ""})
    assert response.status_code == 200  # form redisplayed with error
    assert not User.objects.filter(email="newbie@example.com").exists()


def test_signup_rejects_duplicate_email(client: Client) -> None:
    User.objects.create_user(email="newbie@example.com", password="x", display_name="Existing")
    client.post(reverse("accounts:signup"), VALID)
    assert User.objects.filter(email="newbie@example.com").count() == 1


def test_signup_lowercases_the_email(client: Client) -> None:
    # Phones autocapitalize; "John@X.com" and "john@x.com" must be one account.
    client.post(reverse("accounts:signup"), {**VALID, "email": "Newbie@Example.COM"})
    assert User.objects.filter(email="newbie@example.com").exists()


def test_signup_rejects_case_variant_duplicate(client: Client) -> None:
    User.objects.create_user(email="newbie@example.com", password="x", display_name="Existing")
    response = client.post(reverse("accounts:signup"), {**VALID, "email": "NEWBIE@example.com"})
    assert response.status_code == 200  # form redisplayed with error
    assert User.objects.count() == 1
