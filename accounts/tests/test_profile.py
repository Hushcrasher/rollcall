"""Public profile page — honors profile_public and never leaks the email."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def _profile_url(user: User) -> str:
    return reverse("accounts:profile", kwargs={"slug": user.slug})


def test_public_profile_is_visible_to_anonymous(client: Client) -> None:
    user = User.objects.create_user(
        email="pub@example.com", password="x", display_name="Public Person"
    )
    response = client.get(_profile_url(user))
    assert response.status_code == 200
    assert b"Public Person" in response.content


def test_email_never_appears_on_the_profile(client: Client) -> None:
    """Non-negotiable #1: personal emails are never exposed anywhere."""
    user = User.objects.create_user(
        email="secret@example.com", password="x", display_name="Hidden Email"
    )
    response = client.get(_profile_url(user))
    assert b"secret@example.com" not in response.content


def test_private_profile_is_hidden_from_others(client: Client) -> None:
    user = User.objects.create_user(
        email="priv@example.com", password="x", display_name="Private", profile_public=False
    )
    assert client.get(_profile_url(user)).status_code == 404


def test_owner_can_view_their_own_private_profile(client: Client) -> None:
    user = User.objects.create_user(
        email="priv@example.com", password="x", display_name="Private", profile_public=False
    )
    client.force_login(user)
    assert client.get(_profile_url(user)).status_code == 200


def test_open_to_work_badge_shown_when_set(client: Client) -> None:
    user = User.objects.create_user(
        email="otw@example.com", password="x", display_name="Seeker", open_to_work=True
    )
    response = client.get(_profile_url(user))
    assert b"Open to work" in response.content


@pytest.mark.parametrize(
    ("location", "country", "expected"),
    [("Lyon", "FR", "Lyon · France"), ("", "FR", "France")],
)
def test_profile_shows_city_and_country(
    client: Client, location: str, country: str, expected: str
) -> None:
    """The guard consults location_display, so a country-only user keeps the line.

    The four join branches are the model's concern (see test_location_display).
    """
    user = User.objects.create_user(
        email=f"loc-{location or 'nocity'}@example.com",
        password="x",
        display_name=f"Located {location or 'nocity'}",
        location=location,
        country=country,
    )
    response = client.get(reverse("accounts:profile", kwargs={"slug": user.slug}))
    assert expected in response.content.decode()
