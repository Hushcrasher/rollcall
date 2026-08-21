"""The hardened image intake (spec 2026-08-20-profile-gallery §2). Every byte
a user uploads goes through process_image — these tests are the security
gate's contract. Pure module: no database."""

import struct
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from PIL.JpegImagePlugin import JpegImageFile

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
    with pytest.raises(ValidationError, match="dimensions"):
        images.process_image(_upload(size=(64, 64)), max_side=2560)


def test_oversized_canvas_is_rejected_before_load(monkeypatch: pytest.MonkeyPatch) -> None:
    # Header declares 300x300; pixel data is cut. Pre-load rejection reports
    # dimensions; a post-load check would hit OSError("truncated") and report
    # the format message instead — so the message pins the ordering.
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 1000)
    buffer = BytesIO()
    Image.new("RGB", (300, 300), "red").save(buffer, format="PNG")
    upload = SimpleUploadedFile("t.png", buffer.getvalue()[:120], content_type="image/png")
    with pytest.raises(ValidationError, match="dimensions"):
        images.process_image(upload, max_side=2560)


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


def test_thumbnail_side_is_pinned_and_independent_of_the_main_cap() -> None:
    # The thumbnail is derived from the already-resized main image, so a bug
    # there would silently ship a 2560px "thumbnail" on every gallery page.
    processed = images.process_image(_upload(size=(1200, 900)), max_side=1000, thumbnail=True)
    assert processed.thumbnail is not None
    thumb = Image.open(BytesIO(processed.thumbnail.read()))
    main = Image.open(BytesIO(processed.image.read()))
    assert max(thumb.size) == images.THUMBNAIL_SIDE
    assert max(main.size) == 1000  # the two caps are not the same number


def test_no_thumbnail_is_written_unless_asked() -> None:
    # The avatar path relies on this: one file, not two.
    assert images.process_image(_upload(), max_side=512).thumbnail is None


def test_transparency_survives_the_reencode() -> None:
    # Flattening alpha to a black (or white) box would quietly ruin every
    # transparent PNG a concept artist uploads.
    buffer = BytesIO()
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(buffer, format="PNG")
    upload = SimpleUploadedFile("t.png", buffer.getvalue(), content_type="image/png")
    out = Image.open(BytesIO(images.process_image(upload, max_side=2560).image.read()))
    assert out.mode == "RGBA"
    assert out.getchannel("A").getextrema()[1] == 0  # still fully transparent


@pytest.mark.parametrize(("fmt", "name"), [("PNG", "t.png"), ("WEBP", "t.webp")])
def test_png_and_webp_are_accepted_inputs(fmt: str, name: str) -> None:
    # ALLOWED_FORMATS lists three; only JPEG had coverage.
    processed = images.process_image(_upload(fmt=fmt, name=name), max_side=2560)
    assert Image.open(BytesIO(processed.image.read())).format == "WEBP"


def test_the_jpeg_draft_fast_path_actually_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # No fixture elsewhere in this file is larger than 2x max_side, so the
    # DCT-domain downscale branch (source.draft(...)) never ran under test —
    # a Pillow bump could silently disable it and nothing would fail. The
    # final size alone wouldn't pin this: out.thumbnail() in _encode resizes
    # to the target regardless of whether draft() ran first. Spying on the
    # call is what actually proves the fast path was taken.
    calls: list[tuple[str, tuple[int, int]]] = []
    original_draft = JpegImageFile.draft

    def spy_draft(self: JpegImageFile, mode: str, size: tuple[int, int]) -> None:
        calls.append((mode, size))
        original_draft(self, mode, size)

    monkeypatch.setattr(JpegImageFile, "draft", spy_draft)
    buffer = BytesIO()
    Image.new("RGB", (2400, 2400), "red").save(buffer, format="JPEG")
    upload = SimpleUploadedFile("t.jpg", buffer.getvalue(), content_type="image/jpeg")
    processed = images.process_image(upload, max_side=512)
    assert calls == [("RGB", (1024, 1024))]  # 2x max_side, per process_image
    out = Image.open(BytesIO(processed.image.read()))
    assert max(out.size) == 512


def test_mpo_wrapped_jpegs_from_phone_cameras_are_accepted() -> None:
    # Samsung/iPhone photos are sometimes multi-frame MPO containers; Pillow
    # reports source.format == "MPO", which a plain JPEG allow-list rejects
    # even though the user just took a normal photo. Only frame 0 survives
    # the re-encode — there is no multi-frame WebP output.
    buffer = BytesIO()
    frame0 = Image.new("RGB", (64, 64), "red")
    frame1 = Image.new("RGB", (64, 64), "blue")
    frame0.save(buffer, format="MPO", append_images=[frame1])
    upload = SimpleUploadedFile("t.jpg", buffer.getvalue(), content_type="image/jpeg")
    processed = images.process_image(upload, max_side=2560)
    out = Image.open(BytesIO(processed.image.read()))
    assert out.format == "WEBP"
    pixel = out.getpixel((0, 0))
    assert pixel[:3] == (255, 0, 0)  # ty: ignore[not-subscriptable]  # frame 0 (red), not frame 1


def test_the_mpo_draft_fast_path_actually_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # MpoImageFile subclasses JpegImageFile and doesn't override draft(), so
    # the same DCT-domain downscale should fire for MPO as for plain JPEG —
    # but the guard checked source.format == "JPEG" literally, which is
    # never true for an MPO container, so the fast path was silently skipped.
    calls: list[tuple[str, tuple[int, int]]] = []
    original_draft = JpegImageFile.draft

    def spy_draft(self: JpegImageFile, mode: str, size: tuple[int, int]) -> None:
        calls.append((mode, size))
        original_draft(self, mode, size)

    monkeypatch.setattr(JpegImageFile, "draft", spy_draft)
    buffer = BytesIO()
    frame0 = Image.new("RGB", (2400, 2400), "red")
    frame1 = Image.new("RGB", (2400, 2400), "blue")
    frame0.save(buffer, format="MPO", append_images=[frame1])
    upload = SimpleUploadedFile("t.jpg", buffer.getvalue(), content_type="image/jpeg")
    processed = images.process_image(upload, max_side=512)
    assert calls == [("RGB", (1024, 1024))]  # 2x max_side, per process_image
    out = Image.open(BytesIO(processed.image.read()))
    assert max(out.size) == 512


def test_a_malformed_chunk_past_the_header_is_rejected_not_a_500() -> None:
    # A valid IHDR followed by a truncated ancillary chunk (here pHYs, from
    # dpi=) makes Pillow's PNG plugin raise a bare ValueError deep inside
    # Image.open() — neither UnidentifiedImageError nor OSError, so it used to
    # escape process_image entirely and surface as a 500 instead of the i18n
    # message. struct.error/EOFError are siblings of the same gap and are
    # exercised together by the broadened handler.
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "red").save(buffer, format="PNG", dpi=(72, 72))
    data = bytearray(buffer.getvalue())
    chunk_at = data.find(b"pHYs")
    assert chunk_at != -1, "fixture must actually contain a pHYs chunk"
    struct.pack_into(">I", data, chunk_at - 4, 4)  # declare a too-short length
    upload = SimpleUploadedFile("t.png", bytes(data), content_type="image/png")
    with pytest.raises(ValidationError, match="Upload a JPEG"):
        images.process_image(upload, max_side=2560)
