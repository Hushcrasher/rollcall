"""User model behavior and skeleton smoke tests."""

import pytest
from django.contrib.auth import get_user_model
from django_countries.fields import Country

from accounts.models import User


def test_custom_user_model_is_configured() -> None:
    assert get_user_model() is User
    meta = User._meta
    assert meta.app_label == "accounts"


def test_email_is_the_login_identifier() -> None:
    assert User.USERNAME_FIELD == "email"
    assert User.username is None


def test_visibility_defaults_match_design() -> None:
    """docs/01-DESIGN.md §3.4 — profile_public/contactable default true, open_to_work false."""
    meta = User._meta  # ty: ignore[unresolved-attribute]  (metaclass-added attr)
    assert meta.get_field("profile_public").default is True
    assert meta.get_field("contactable").default is True
    assert meta.get_field("open_to_work").default is False


@pytest.mark.django_db
def test_slug_generated_from_display_name_with_collision_suffix() -> None:
    first = User.objects.create_user(email="a@example.com", password="x", display_name="Jane Doe")
    second = User.objects.create_user(email="b@example.com", password="x", display_name="Jane Doe")
    assert first.slug == "jane-doe"
    assert second.slug == "jane-doe-2"


@pytest.mark.django_db
def test_country_is_optional_and_stores_iso_code() -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    assert not user.country  # blank by default

    user.country = Country("FR")  # ty: ignore[invalid-assignment]
    user.save(update_fields=["country"])
    user.refresh_from_db()
    assert user.country.code == "FR"  # ty: ignore[unresolved-attribute]
    assert user.country.name == "France"


@pytest.mark.parametrize(
    ("location", "country", "expected"),
    [
        ("Lyon", "FR", "Lyon · France"),
        ("Lyon", "", "Lyon"),
        ("", "FR", "France"),
        ("", "", ""),
        ("Lyon", "ZZ", "Lyon"),  # invalid code: truthy, but renders nothing
    ],
)
def test_location_display(location: str, country: str, expected: str) -> None:
    user = User(display_name="X", location=location, country=country)
    assert user.location_display == expected
