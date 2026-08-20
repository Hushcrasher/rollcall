"""Login (by email), logout, and password reset."""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngP@ssw0rd!"


@pytest.fixture
def user() -> User:
    return User.objects.create_user(
        email="member@example.com", password=PASSWORD, display_name="Member"
    )


def test_login_page_asks_for_email(client: Client) -> None:
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert b"Email" in response.content


def test_login_with_email_and_password(client: Client, user: User) -> None:
    response = client.post(
        reverse("accounts:login"), {"username": user.email, "password": PASSWORD}
    )
    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_login_ignores_email_case(client: Client, user: User) -> None:
    response = client.post(
        reverse("accounts:login"), {"username": "Member@Example.COM", "password": PASSWORD}
    )
    assert response.status_code == 302
    assert response.wsgi_request.user.is_authenticated


def test_login_redirects_to_own_profile(client: Client, user: User) -> None:
    response = client.post(
        reverse("accounts:login"), {"username": user.email, "password": PASSWORD}
    )
    assert response["Location"] == reverse("accounts:my_profile")


def test_logout(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert not response.wsgi_request.user.is_authenticated


def test_password_reset_emails_a_known_address(client: Client, user: User) -> None:
    response = client.post(reverse("accounts:password_reset"), {"email": user.email})
    assert response.status_code == 302
    assert len(mail.outbox) == 1


def test_password_reset_stays_silent_for_unknown_address(client: Client) -> None:
    response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
    assert response.status_code == 302  # never reveals whether the address exists
    assert len(mail.outbox) == 0
