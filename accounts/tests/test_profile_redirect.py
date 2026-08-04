"""/profile/ — the slugless entry point to one's own profile."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_my_profile_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:my_profile"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_my_profile_redirects_to_own_slug(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.get(reverse("accounts:my_profile"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:profile", kwargs={"slug": user.slug})
