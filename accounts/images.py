"""Hardened image intake — the ONLY path user image bytes take into storage
(spec docs/superpowers/specs/2026-08-20-profile-gallery-design.md §2).

Re-encoding is the core defense: decode fully, resize, write a fresh WebP.
A polyglot payload, appended archive or crafted metadata does not survive a
re-encode, and EXIF — GPS position included — is dropped because Pillow
writes none unless asked."""

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

# Parsing a header that promises a >40MP canvas must raise, not allocate.
Image.MAX_IMAGE_PIXELS = 40_000_000


class ProcessedImage(NamedTuple):
    image: ContentFile
    thumbnail: ContentFile | None


def _encode(source: Image.Image, max_side: int) -> ContentFile:
    out = source.copy()
    if out.mode not in ("RGB", "RGBA"):
        # P/LA can carry transparency; anything else flattens to RGB.
        out = out.convert("RGBA") if out.mode in ("P", "LA", "PA") else out.convert("RGB")
    out.thumbnail((max_side, max_side))  # no-op when already smaller
    buffer = BytesIO()
    out.save(buffer, format="WEBP", quality=WEBP_QUALITY)
    return ContentFile(buffer.getvalue(), name=f"{uuid4().hex}.webp")


def process_image(
    uploaded: UploadedFile, *, max_side: int, thumbnail: bool = False
) -> ProcessedImage:
    """Validate and re-encode one upload; ValidationError on anything that is
    not a plain JPEG/PNG/WebP within the caps."""
    if uploaded.size is not None and uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Images can be at most 10 MB."))
    try:
        source = Image.open(uploaded)  # ty: ignore[invalid-argument-type]
        source.load()
    except Image.DecompressionBombError as exc:
        raise ValidationError(_("This image's dimensions are too large.")) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError(_("Upload a JPEG, PNG or WebP image.")) from exc
    if source.format not in ALLOWED_FORMATS:
        raise ValidationError(_("Upload a JPEG, PNG or WebP image."))
    if source.width * source.height > Image.MAX_IMAGE_PIXELS:  # ty: ignore[unsupported-operator]
        raise ValidationError(_("This image's dimensions are too large."))
    return ProcessedImage(
        image=_encode(source, max_side),
        thumbnail=_encode(source, THUMBNAIL_SIDE) if thumbnail else None,
    )
