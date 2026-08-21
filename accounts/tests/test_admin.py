"""Admin configuration guards.

`UserAdmin.fieldsets` lists User's fields explicitly, so a field missing from
it is invisible and uneditable for staff. No Django system check catches that
(a `blank=True` field is valid whether or not admin declares it), hence the
guard below.
"""

from io import BytesIO
from typing import Any

import pytest
from django.contrib.admin.utils import flatten_fieldsets
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.admin import UserAdmin
from accounts.models import ProfileImage, User


def test_all_editable_user_fields_are_reachable_in_admin() -> None:
    declared = set(flatten_fieldsets(UserAdmin.fieldsets))
    meta = User._meta  # ty: ignore[unresolved-attribute]  (metaclass-added attr)
    editable = {
        f.name for f in meta.get_fields() if getattr(f, "editable", False) and not f.auto_created
    }
    assert editable - declared == set()


def _jpeg_with_exif() -> SimpleUploadedFile:
    buffer = BytesIO()
    tags = Image.Exif()
    tags[0x010F] = "TestCam"  # Make — the marker the strip assertion hunts for
    Image.new("RGB", (900, 900), "green").save(buffer, format="JPEG", exif=tags)
    return SimpleUploadedFile("face.jpg", buffer.getvalue(), content_type="image/jpeg")


@pytest.mark.django_db
def test_admin_avatar_upload_goes_through_the_pipeline(client: Client) -> None:
    """The invariant is about the stored file, not about one form: an avatar
    posted through the admin must be re-encoded like any other (spec §2).
    Staff privilege is authority over the row, not permission to write raw
    bytes into the media bucket."""
    staff = User.objects.create_superuser(
        email="root@example.com", password="x", display_name="Root"
    )
    member = User.objects.create_user(
        email="member@example.com", password="x", display_name="Member"
    )
    client.force_login(staff)
    response = client.post(
        reverse("admin:accounts_user_change", args=[member.pk]),
        {
            "email": member.email,
            "display_name": member.display_name,
            "role": User.Role.MEMBER,
            "profile_public": "on",
            "contactable": "on",
            "is_active": "on",
            "avatar": _jpeg_with_exif(),
        },
    )
    assert response.status_code == 302  # a form error would render 200
    member.refresh_from_db()
    # avatar is a FieldFile at runtime; the type checker sees the ImageField.
    avatar: Any = member.avatar
    assert avatar.name.endswith(".webp")
    data = avatar.read()
    assert b"TestCam" not in data
    assert max(Image.open(BytesIO(data)).size) <= 512


@pytest.mark.django_db
def test_profile_image_changelist_survives_an_empty_thumbnail(client: Client) -> None:
    # Both files are always written by the upload pipeline, so this is
    # unreachable through it — but FieldFile.url raises ValueError on an
    # empty field, and a hand-made row (fixture, migration, admin shell)
    # would otherwise crash the entire changelist, not just its own row.
    staff = User.objects.create_superuser(
        email="root2@example.com", password="x", display_name="Root"
    )
    member = User.objects.create_user(
        email="member2@example.com", password="x", display_name="Member"
    )
    ProfileImage.objects.create(
        user=member,
        image=ContentFile(b"webp-bytes", name="a.webp"),
        thumbnail="",
    )
    client.force_login(staff)
    response = client.get(reverse("admin:accounts_profileimage_changelist"))
    assert response.status_code == 200
