"""Settings — edit profile + the three visibility booleans (docs/01-DESIGN.md §3.4)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_settings_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:settings"))
    assert response.status_code == 302  # redirected to login


def test_settings_exposes_the_contactable_toggle(client: Client, user: User) -> None:
    """The contactable toggle must be easy to find (ease of exit, no dark pattern)."""
    client.force_login(user)
    response = client.get(reverse("accounts:settings"))
    assert response.status_code == 200
    assert b"contactable" in response.content


def test_update_profile_fields(client: Client, user: User) -> None:
    client.force_login(user)
    client.post(
        reverse("accounts:settings"),
        {"display_name": "Renamed", "bio": "Gameplay dev", "location": "Lyon"},
    )
    user.refresh_from_db()
    assert user.display_name == "Renamed"
    assert user.bio == "Gameplay dev"


def test_toggle_visibility_booleans(client: Client, user: User) -> None:
    assert user.profile_public is True and user.open_to_work is False
    client.force_login(user)

    # Unchecked checkboxes aren't submitted → they become False; open_to_work on.
    client.post(
        reverse("accounts:settings"),
        {"display_name": "Me", "open_to_work": "on"},
    )

    user.refresh_from_db()
    assert user.profile_public is False
    assert user.contactable is False
    assert user.open_to_work is True
