"""Email-verification token — must invalidate once the email is verified
(replay protection), unlike a plain signed link."""

import pytest
from django.utils import timezone

from accounts.models import User
from accounts.tokens import email_verification_token


@pytest.mark.django_db
def test_token_validates_for_its_user() -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")
    token = email_verification_token.make_token(user)
    assert email_verification_token.check_token(user, token) is True


@pytest.mark.django_db
def test_token_is_invalidated_once_email_is_verified() -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")
    token = email_verification_token.make_token(user)

    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])

    assert email_verification_token.check_token(user, token) is False


@pytest.mark.django_db
def test_token_does_not_validate_for_a_different_user() -> None:
    user = User.objects.create_user(email="a@example.com", password="x", display_name="A")
    other = User.objects.create_user(email="b@example.com", password="x", display_name="B")
    token = email_verification_token.make_token(user)
    assert email_verification_token.check_token(other, token) is False
