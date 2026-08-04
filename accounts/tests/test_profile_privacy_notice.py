"""profile_public=False is a silent state: the owner keeps seeing their own
profile normally (_visible_users exempts them), so nothing would otherwise tell
them they are invisible everywhere."""

import pytest
from django.test import Client

from accounts.models import User

pytestmark = pytest.mark.django_db

NOTICE = b"Your profile is private"


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_private_profile_warns_its_owner(client: Client, user: User) -> None:
    user.profile_public = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["profile_public"])
    client.force_login(user)
    assert NOTICE in client.get(user.get_absolute_url()).content


def test_the_notice_survives_the_preview(client: Client, user: User) -> None:
    """The preview does not fake the visitor's 404 — it answers the real
    question, which is whether anyone can see the page at all."""
    user.profile_public = False  # ty: ignore[invalid-assignment]
    user.save(update_fields=["profile_public"])
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert NOTICE in body


def test_a_public_profile_has_no_notice(client: Client, user: User) -> None:
    assert user.profile_public is True
    client.force_login(user)
    assert NOTICE not in client.get(user.get_absolute_url()).content


def test_a_visitor_never_sees_the_notice(client: Client, user: User) -> None:
    other = User.objects.create_user(email="you@example.com", password="x", display_name="You")
    client.force_login(other)
    assert NOTICE not in client.get(user.get_absolute_url()).content
