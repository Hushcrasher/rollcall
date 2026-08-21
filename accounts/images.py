"""Hardened image intake — the ONLY path user image bytes take into storage
(spec docs/superpowers/specs/2026-08-20-profile-gallery-design.md §2).

Re-encoding is the core defense: decode fully, resize, write a fresh WebP.
A polyglot payload, appended archive or crafted metadata does not survive a
re-encode, and EXIF — GPS position included — is dropped because Pillow
writes none unless asked."""

import struct
from io import BytesIO
from typing import NamedTuple
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# SVG is script-capable XML and must stay impossible; GIF/animation is out of
# scope (spec). The check reads the *decoded* format, never name or headers.
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
WEBP_QUALITY = 82
THUMBNAIL_SIDE = 400

# Checked by hand in process_image before load() — Pillow's own guard (set from
# this same value below) only hard-raises past 2x MAX_IMAGE_PIXELS, so relying
# on it alone would let a canvas between 1x and 2x the cap fully decode first.
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ProcessedImage(NamedTuple):
    image: ContentFile
    thumbnail: ContentFile | None


def _encode(source: Image.Image, max_side: int) -> tuple[ContentFile, Image.Image]:
    """Encode one WebP and hand back the resized image it was written from, so
    the caller can derive a thumbnail from that instead of re-resizing the
    full-size original — the peak of this module is one decoded bitmap."""
    out = source.copy()
    if out.mode not in ("RGB", "RGBA"):
        # P/LA can carry transparency; anything else flattens to RGB.
        out = out.convert("RGBA") if out.mode in ("P", "LA", "PA") else out.convert("RGB")
    out.thumbnail((max_side, max_side))  # no-op when already smaller
    # Metadata stripping must not depend on save()'s per-format defaults —
    # clear Pillow's info dict (EXIF/ICC profile/comments) explicitly.
    out.info.clear()
    buffer = BytesIO()
    out.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return ContentFile(buffer.getvalue(), name=f"{uuid4().hex}.webp"), out


def process_image(
    uploaded: UploadedFile, *, max_side: int, thumbnail: bool = False
) -> ProcessedImage:
    """Validate and re-encode one upload; ValidationError on anything that is
    not a plain JPEG/PNG/WebP within the caps."""
    # Fail closed: an unreadable size is treated as over the cap, never skipped.
    if uploaded.size is None or uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Images can be at most 10 MB."))
    uploaded.seek(0)  # some upload handlers leave the stream past position 0
    try:
        source = Image.open(uploaded)  # ty: ignore[invalid-argument-type]
    except Image.DecompressionBombError as exc:
        raise ValidationError(_("This image's dimensions are too large.")) from exc
    except (UnidentifiedImageError, OSError, ValueError, EOFError, struct.error) as exc:
        # A well-formed IHDR followed by a malformed ancillary chunk (e.g. a
        # truncated pHYs) makes Pillow's format plugins raise bare ValueError/
        # EOFError/struct.error from inside Image.open() itself — none of
        # which are OSError, so they used to escape as a 500.
        raise ValidationError(_("Upload a JPEG, PNG or WebP image.")) from exc
    if source.format not in ALLOWED_FORMATS:
        raise ValidationError(_("Upload a JPEG, PNG or WebP image."))
    # Reject before the full pixel buffer is allocated — width/height come from
    # the header alone, so this runs before load() decodes any pixel data.
    if source.width * source.height > MAX_IMAGE_PIXELS:
        raise ValidationError(_("This image's dimensions are too large."))
    if source.format == "JPEG":
        # DCT-domain downscale, decided before any pixel is decoded: JPEG can be
        # unpacked at 1/2, 1/4 or 1/8 scale for free, so a phone photo headed for
        # a 512px avatar never materialises at full size. 2x max_side keeps a
        # margin above the target, so the real resize below never upsamples;
        # a no-op on anything already small enough, and on every other format.
        source.draft("RGB", (2 * max_side, 2 * max_side))
    try:
        source.load()
        encoded, resized = _encode(source, max_side)
        # From the resized copy, not a second pass over the original.
        thumb = _encode(resized, THUMBNAIL_SIDE)[0] if thumbnail else None
    except (OSError, ValueError, EOFError, struct.error) as exc:
        # Malformed pixel data past a valid header can raise any of these from
        # load(), and convert() (inside _encode) can raise ValueError on
        # exotic modes — all are "not a real image", never a 500.
        raise ValidationError(_("Upload a JPEG, PNG or WebP image.")) from exc
    return ProcessedImage(image=encoded, thumbnail=thumb)
