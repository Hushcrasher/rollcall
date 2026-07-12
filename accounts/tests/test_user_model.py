"""User model behavior and skeleton smoke tests."""

import pytest
from django.contrib.auth import get_user_model


def test_custom_user_model_is_configured():
    user_model = get_user_model()
    assert user_model._meta.app_label == "accounts"
    assert user_model.__name__ == "User"


def test_email_is_the_login_identifier():
    user_model = get_user_model()
    assert user_model.USERNAME_FIELD == "email"
    assert user_model.username is None


def test_visibility_defaults_match_design():
    """docs/01-DESIGN.md §3.4 — profile_public/contactable default true, open_to_work false."""
    user_model = get_user_model()
    assert user_model._meta.get_field("profile_public").default is True
    assert user_model._meta.get_field("contactable").default is True
    assert user_model._meta.get_field("open_to_work").default is False


@pytest.mark.django_db
def test_slug_generated_from_display_name_with_collision_suffix():
    user_model = get_user_model()
    first = user_model.objects.create_user(
        email="a@example.com", password="x", display_name="Jane Doe"
    )
    second = user_model.objects.create_user(
        email="b@example.com", password="x", display_name="Jane Doe"
    )
    assert first.slug == "jane-doe"
    assert second.slug == "jane-doe-2"
