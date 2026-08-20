"""The profile gallery (spec 2026-08-20-profile-gallery) — model, management
views, display, and the file lifecycle."""

from datetime import timedelta
from io import BytesIO
from typing import Any

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from PIL import Image

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


def _png_upload(name: str = "work.png") -> SimpleUploadedFile:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def test_upload_creates_reencoded_image_and_thumbnail(client: Client) -> None:
    user = _user()
    client.force_login(user)
    response = client.post(
        reverse("accounts:portfolio_add"), {"image": _png_upload(), "caption": "Boss fight"}
    )
    assert response.status_code == 302
    stored = user.portfolio_images.get()  # ty: ignore[unresolved-attribute]
    assert stored.caption == "Boss fight"
    assert stored.image.name.endswith(".webp")
    assert "work" not in stored.image.name  # client filename never survives
    assert stored.thumbnail.name.endswith(".webp")


def test_unverified_user_is_bounced_to_verification(client: Client) -> None:
    user = _user(verified=False)
    client.force_login(user)
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 302
    assert response.url == reverse("accounts:verification_sent")
    assert user.portfolio_images.count() == 0  # ty: ignore[unresolved-attribute]


def test_anonymous_is_sent_to_login(client: Client) -> None:
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_the_thirteenth_image_is_rejected(client: Client) -> None:
    user = _user()
    client.force_login(user)
    for _i in range(MAX_PORTFOLIO_IMAGES):
        _image(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert user.portfolio_images.count() == MAX_PORTFOLIO_IMAGES  # ty: ignore[unresolved-attribute]


def test_the_twelfth_image_lands(client: Client) -> None:
    # Pins the boundary the 13th-image test can't: a good upload at exactly
    # 11 existing images must still succeed, not be caught by an off-by-one.
    user = _user()
    client.force_login(user)
    for _i in range(MAX_PORTFOLIO_IMAGES - 1):
        _image(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert user.portfolio_images.count() == MAX_PORTFOLIO_IMAGES  # ty: ignore[unresolved-attribute]


def test_a_rejected_file_stores_nothing(client: Client) -> None:
    user = _user()
    client.force_login(user)
    svg = SimpleUploadedFile("a.png", b"<svg xmlns='x'/>", content_type="image/png")
    client.post(reverse("accounts:portfolio_add"), {"image": svg})
    assert user.portfolio_images.count() == 0  # ty: ignore[unresolved-attribute]


def test_upload_is_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    cache.clear()  # rate counters live in the cache
    user = _user()
    client.force_login(user)
    for _i in range(10):
        client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    response = client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 403


def test_rate_limit_is_per_user_not_shared(client: Client, settings: Any) -> None:
    # Pins key="user": a regression to key="ip" would let one user's uploads
    # exhaust another's quota (or a shared IP get blocked as one).
    settings.RATELIMIT_ENABLE = True
    cache.clear()
    user_a = _user()
    client.force_login(user_a)
    for _i in range(10):
        client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})

    user_b = _user(email="other@example.com")
    other_client = Client()
    other_client.force_login(user_b)
    response = other_client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    assert response.status_code == 302
    assert user_b.portfolio_images.count() == 1  # ty: ignore[unresolved-attribute]


def test_delete_removes_row_and_both_files(client: Client) -> None:
    user = _user()
    client.force_login(user)
    client.post(reverse("accounts:portfolio_add"), {"image": _png_upload()})
    stored = user.portfolio_images.get()  # ty: ignore[unresolved-attribute]
    image_storage, image_name = stored.image.storage, stored.image.name
    thumb_name = stored.thumbnail.name
    client.post(reverse("accounts:portfolio_delete", args=[stored.pk]))
    assert user.portfolio_images.count() == 0  # ty: ignore[unresolved-attribute]
    assert not image_storage.exists(image_name)
    assert not image_storage.exists(thumb_name)


def test_you_cannot_delete_someone_elses_image(client: Client) -> None:
    owner = _user()
    other = _user(email="other@example.com")
    stored = _image(owner)
    client.force_login(other)
    response = client.post(reverse("accounts:portfolio_delete", args=[stored.pk]))
    assert response.status_code == 404
    assert owner.portfolio_images.count() == 1  # ty: ignore[unresolved-attribute]


def test_profile_shows_the_work_section(client: Client) -> None:
    user = _user()
    _image(user, caption="Boss fight concept")
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "Work" in body
    assert "Boss fight concept" in body


def test_profile_without_images_has_no_work_section(client: Client) -> None:
    user = _user()
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert "portfolio-grid" not in main
