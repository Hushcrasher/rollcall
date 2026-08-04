"""Email verification — the token link flips email_verified_at, is single-use,
and resend works only while unverified."""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import email_verification_token

pytestmark = pytest.mark.django_db


def _verify_url(user: User, token: str | None = None) -> str:
    return reverse(
        "accounts:verify_email",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": token if token is not None else email_verification_token.make_token(user),
        },
    )


def test_valid_link_verifies_the_email(client: Client) -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")

    response = client.get(_verify_url(user))

    user.refresh_from_db()
    assert user.email_verified_at is not None
    assert response.status_code == 302


def test_valid_link_redirects_to_the_profile(client: Client) -> None:
    """The success message says "you can now add credits" — the profile is
    where that happens, not the account page."""
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")

    response = client.get(_verify_url(user))

    assert response["Location"] == reverse("accounts:my_profile")


def test_invalid_token_does_not_verify(client: Client) -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")

    client.get(_verify_url(user, token="bogus-token"))

    user.refresh_from_db()
    assert user.email_verified_at is None


def test_link_is_single_use(client: Client) -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")
    url = _verify_url(user)

    client.get(url)
    user.refresh_from_db()
    first_verified_at = user.email_verified_at

    client.get(url)  # replay the now-consumed link
    user.refresh_from_db()
    assert user.email_verified_at == first_verified_at  # not re-stamped


def test_resend_sends_a_new_email_while_unverified(client: Client) -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")
    client.force_login(user)

    client.post(reverse("accounts:resend_verification"))

    assert len(mail.outbox) == 1


def test_resend_is_a_noop_once_verified(client: Client) -> None:
    from django.utils import timezone

    user = User.objects.create_user(
        email="a@example.com", password="x", display_name="A", email_verified_at=timezone.now()
    )
    client.force_login(user)

    client.post(reverse("accounts:resend_verification"))

    assert len(mail.outbox) == 0
