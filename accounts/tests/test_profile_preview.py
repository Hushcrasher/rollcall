"""'View as member' — the owner previews their own profile as a logged-in
member sees it (docs/superpowers/specs/2026-08-04-profile-account-split-design.md)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


@pytest.fixture
def other() -> User:
    return User.objects.create_user(email="you@example.com", password="x", display_name="You")


def test_owner_sees_the_edit_and_preview_links(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url()).content
    assert b"Edit my profile" in body
    assert b"View as member" in body


def test_preview_hides_every_owner_control(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Edit my profile" not in body
    assert b"View as member" not in body
    assert b"Add a credit" not in body
    assert b"Back to my profile" in body


def test_preview_renders_contact_inert(client: Client, user: User) -> None:
    """The label is shown so the owner knows members can reach them, but it is
    not a link: contacting yourself is refused by the relay, a dead end."""
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Contact" in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) not in body


def test_preview_hides_contact_when_not_contactable(client: Client, user: User) -> None:
    user.contactable = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["contactable"])
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Contact" not in body


def test_preview_param_is_inert_for_a_visitor(client: Client, user: User, other: User) -> None:
    """A third party already sees the member view — the param must not give them
    a different page, and must not strip their real Contact link."""
    client.force_login(other)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Back to my profile" not in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) in body


def test_anonymous_visitor_is_unaffected(client: Client, user: User) -> None:
    response = client.get(user.get_absolute_url() + "?preview=member")
    assert response.status_code == 200
    assert b"Back to my profile" not in response.content
