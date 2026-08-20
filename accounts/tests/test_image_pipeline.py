"""The hardened image intake (spec 2026-08-20-profile-gallery §2). Every byte
a user uploads goes through process_image — these tests are the security
gate's contract. Pure module: no database."""

from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from accounts import images


def _upload(
    fmt: str = "JPEG",
    size: tuple[int, int] = (64, 64),
    exif: bool = False,
    name: str = "t.jpg",
) -> SimpleUploadedFile:
    buffer = BytesIO()
    img = Image.new("RGB", size, "red")
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "TestCam"  # Make — the marker the strip test hunts for
        img.save(buffer, format=fmt, exif=tags)
    else:
        img.save(buffer, format=fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/octet-stream")


def test_valid_jpeg_reencodes_to_webp_with_a_thumbnail() -> None:
    processed = images.process_image(_upload(), max_side=2560, thumbnail=True)
    out = Image.open(BytesIO(processed.image.read()))
    assert out.format == "WEBP"
    assert processed.thumbnail is not None
    thumb = Image.open(BytesIO(processed.thumbnail.read()))
    assert thumb.format == "WEBP"


def test_the_clients_filename_never_survives() -> None:
    processed = images.process_image(_upload(name="../../evil<svg>.jpg"), max_side=2560)
    assert processed.image.name is not None
    assert processed.image.name.endswith(".webp")
    assert "evil" not in processed.image.name
    assert "/" not in processed.image.name


def test_svg_is_rejected_even_renamed_to_png() -> None:
    svg = SimpleUploadedFile(
        "art.png",
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
        content_type="image/png",
    )
    with pytest.raises(ValidationError):
        images.process_image(svg, max_side=2560)


def test_gif_is_rejected() -> None:
    with pytest.raises(ValidationError):
        images.process_image(_upload(fmt="GIF", name="t.gif"), max_side=2560)


def test_oversize_upload_is_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 100)
    # Bytes that are both over the cap AND undecodable garbage — if the size
    # check ran after (or didn't gate) decode, this would fail with the "not a
    # valid image" message instead, proving the size check truly runs first.
    upload = SimpleUploadedFile("t.jpg", b"x" * 200, content_type="application/octet-stream")
    with pytest.raises(ValidationError, match="10 MB"):
        images.process_image(upload, max_side=2560)


def test_decompression_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Our own pre-load gate (MAX_IMAGE_PIXELS) must reject a canvas over the cap
    # on its own, independent of Pillow's global guard — which only hard-raises
    # past 2x its threshold (see test_pillow_hard_raise_is_translated for that
    # branch). A real >40MP fixture would bloat the repo, so the cap is
    # shrunk instead; a 64x64 (4096px) image stays well under Pillow's own
    # 40,000,000-pixel default, so only our pre-load check can catch this.
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(ValidationError):
        images.process_image(_upload(size=(64, 64)), max_side=2560)


def test_pillow_hard_raise_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pillow's own DecompressionBombError — raised inside Image.open() once a
    # header-declared size exceeds 2x Image.MAX_IMAGE_PIXELS — must still be
    # caught and translated to a ValidationError, independent of our own
    # pre-load MAX_IMAGE_PIXELS gate (untouched here).
    monkeypatch.setattr(images.Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(ValidationError):
        images.process_image(_upload(size=(64, 64)), max_side=2560)


def test_upload_with_unknown_size_is_rejected() -> None:
    # An upload whose size Django couldn't determine must fail closed, not
    # silently skip the cap. Content is a perfectly valid, decodable image —
    # the only defect being tested is the missing/None size itself.
    upload = _upload()
    upload.size = None  # ty: ignore[invalid-assignment]
    with pytest.raises(ValidationError, match="10 MB"):
        images.process_image(upload, max_side=2560)


def test_exif_is_destroyed() -> None:
    processed = images.process_image(_upload(exif=True), max_side=2560)
    data = processed.image.read()
    assert b"TestCam" not in data
    assert b"Exif" not in data and b"EXIF" not in data


def test_resize_caps_the_longest_side() -> None:
    processed = images.process_image(_upload(size=(300, 100)), max_side=200)
    out = Image.open(BytesIO(processed.image.read()))
    assert max(out.size) == 200
