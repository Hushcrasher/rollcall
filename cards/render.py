"""Open Graph card renderer — a pure function from CardData to PNG bytes.

The layout values are the spec's §2 table (docs/superpowers/specs/
2026-08-21-open-graph-cards-design.md); change them there, then here. The
renderer takes no user-uploaded bytes: every input is text drawn by Pillow
with a vendored font."""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630
MARGIN, GAP = 60, 24
WHITE, INK, MUTED, BLUE = "#FFFFFF", "#111111", "#555555", "#0172AD"
TITLE_SIZES = (72, 56, 44)
DEFAULT_TAGLINE = _("Find people by what they've worked on")

_FONTS = Path(__file__).parent / "fonts"

# Inter covers Latin (with extensions), Greek and Cyrillic, plus the
# punctuation the cards use. Anything else would print .notdef boxes, so the
# card falls back to the neutral layout instead (spec §2, "Non-Latin names").
_COVERED_RANGES = (
    (0x0020, 0x007E),  # Basic Latin
    (0x00A0, 0x024F),  # Latin-1 Supplement, Latin Extended-A/B
    (0x0370, 0x03FF),  # Greek
    (0x0400, 0x04FF),  # Cyrillic
    (0x1E00, 0x1EFF),  # Latin Extended Additional
    (0x2000, 0x206F),  # General Punctuation (en dash, ellipsis…)
)


@dataclass(frozen=True)
class CardData:
    kind: str
    title: str
    subtitle: str = ""
    stats: str = ""
    footer: str = ""
    badge: str = ""


def fallback_card() -> CardData:
    return CardData(kind="default", title="ROLLCALL", footer=str(DEFAULT_TAGLINE))


def covered(text: str) -> bool:
    return all(any(lo <= ord(ch) <= hi for lo, hi in _COVERED_RANGES) for ch in text)


@lru_cache(maxsize=16)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        str(_FONTS / ("Inter-Bold.ttf" if bold else "Inter-Regular.ttf")), size
    )


def _width(text: str, font: ImageFont.FreeTypeFont) -> float:
    return font.getlength(text)


def title_size(title: str) -> int:
    for size in TITLE_SIZES:
        if _width(title, _font(True, size)) <= WIDTH - 2 * MARGIN:
            return size
    return TITLE_SIZES[-1]


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str:
    if _width(text, font) <= max_width:
        return text
    while text and _width(text + "…", font) > max_width:
        text = text[:-1]
    return text + "…"


def render(data: CardData) -> bytes:
    if not all(
        covered(part) for part in (data.title, data.subtitle, data.stats, data.footer, data.badge)
    ):
        data = fallback_card()
    max_width = WIDTH - 2 * MARGIN
    # (text, font, colour) top to bottom; empty fields are skipped so the
    # block collapses instead of leaving gaps.
    lines: list[tuple[str, ImageFont.FreeTypeFont, str]] = [("ROLLCALL", _font(True, 36), BLUE)]
    title_font = _font(True, title_size(data.title))
    lines.append((_ellipsize(data.title, title_font, max_width), title_font, INK))
    if data.subtitle:
        lines.append(
            (_ellipsize(data.subtitle, _font(False, 40), max_width), _font(False, 40), INK)
        )
    if data.stats:
        lines.append((_ellipsize(data.stats, _font(False, 36), max_width), _font(False, 36), MUTED))
    if data.footer or data.badge:
        lines.append((data.footer, _font(False, 32), MUTED))

    block_height = sum(font.size for _, font, _ in lines) + GAP * (len(lines) - 1)
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    # draw.text positions each line by its ascender, not its ink: a line with
    # no ascenders (e.g. the all-caps wordmark) or one with descenders (e.g.
    # a subtitle with "g"/"p") leaves a different visual gap than font.size
    # implies. Centre on the actual ink of the first and last lines (measured
    # with getbbox), not the nominal font-size box, or the block drifts.
    first_text, first_font, _ = lines[0]
    last_text, last_font, _ = lines[-1]
    top_bearing = first_font.getbbox(first_text)[1] if first_text else 0
    bottom_bearing = last_font.getbbox(last_text)[3] if last_text else last_font.size
    y = (HEIGHT - block_height) // 2 + (last_font.size - bottom_bearing - top_bearing) // 2
    for text, font, colour in lines:
        if text:
            draw.text((MARGIN, y), text, font=font, fill=colour)
        if font is lines[-1][1] and data.badge:
            # The badge sits on the footer line, right of the footer text.
            x = MARGIN + (_width(data.footer, font) + GAP * 2 if data.footer else 0)
            draw.text((x, y), data.badge, font=_font(True, 32), fill=BLUE)
        y += font.size + GAP

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
