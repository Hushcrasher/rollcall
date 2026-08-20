"""The profile gallery (spec 2026-08-20-profile-gallery) — model, management
views, display, and the file lifecycle."""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from accounts.models import MAX_PORTFOLIO_IMAGES, ProfileImage, User

pytestmark = pytest.mark.django_db


def _user(email: str = "artist@example.com", verified: bool = True, **kwargs: object) -> User:
    return User.objects.create_user(
        email=email,
        password="x",
        display_name="Artist",
        email_verified_at=timezone.now() if verified else None,
        **kwargs,
    )


def _image(user: User, caption: str = "") -> ProfileImage:
    # Stored files are irrelevant to model tests — tiny stand-ins are enough.
    return ProfileImage.objects.create(
        user=user,
        image=ContentFile(b"webp-bytes", name="a.webp"),
        thumbnail=ContentFile(b"webp-bytes", name="t.webp"),
        caption=caption,
    )


def test_gallery_is_newest_first_and_capped_constant_is_twelve() -> None:
    user = _user()
    first = _image(user, "first")
    second = _image(user, "second")
    ProfileImage.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=1))
    assert [
        i.pk
        for i in user.portfolio_images.all()  # ty: ignore[unresolved-attribute]
    ] == [second.pk, first.pk]
    assert MAX_PORTFOLIO_IMAGES == 12


def test_rows_cascade_with_the_user() -> None:
    user = _user()
    _image(user)
    user.delete()
    assert ProfileImage.objects.count() == 0
