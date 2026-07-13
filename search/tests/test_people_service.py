"""search_people — trigram people search that never exposes private profiles."""

import pytest

from accounts.models import User
from search.services import search_people

pytestmark = pytest.mark.django_db


def test_finds_public_people_by_display_name() -> None:
    User.objects.create_user(email="a@example.com", password="x", display_name="Ada Lovelace")
    User.objects.create_user(email="b@example.com", password="x", display_name="Alan Turing")

    results = list(search_people("lovelace"))

    assert [u.display_name for u in results] == ["Ada Lovelace"]


def test_tolerates_typos() -> None:
    User.objects.create_user(email="a@example.com", password="x", display_name="Hideo Kojima")
    results = list(search_people("kojma"))  # missing letter
    assert results[0].display_name == "Hideo Kojima"


def test_never_returns_private_profiles() -> None:
    """Anti-exposure: a profile_public=False user is invisible to search."""
    User.objects.create_user(
        email="hidden@example.com", password="x", display_name="Secret Dev", profile_public=False
    )
    assert list(search_people("Secret Dev")) == []


def test_blank_query_returns_nothing() -> None:
    User.objects.create_user(email="a@example.com", password="x", display_name="Someone")
    assert list(search_people("   ")) == []
