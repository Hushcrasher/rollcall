"""Open Graph card renderer — a pure function from CardData to PNG bytes.

The layout values are the spec's §2 table (docs/superpowers/specs/
2026-08-21-open-graph-cards-design.md); change them there, then here. The
renderer takes no user-uploaded bytes: every input is text drawn by Pillow
with a vendored font."""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Literal

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
    # No footer: the stacked wordmark above the title already carries the
    # brand, so repeating it as a title *and* a footer duplicated it on the
    # card (review follow-up, 2026-08-21).
    return CardData(kind="default", title=str(DEFAULT_TAGLINE))


def covered(text: str) -> bool:
    return all(any(lo <= ord(ch) <= hi for lo, hi in _COVERED_RANGES) for ch in text)


_FACE_FILES = {
    "regular": "Inter-Regular.ttf",
    "bold": "Inter-Bold.ttf",
    "mono": "JetBrainsMono-Bold.ttf",
}


@lru_cache(maxsize=16)
def _font(face: Literal["regular", "bold", "mono"], size: int) -> ImageFont.FreeTypeFont:
    # layout_engine=BASIC, pinned rather than left to Pillow: Pillow picks RAQM
    # when libfribidi/harfbuzz are present at runtime (common on Linux CI,
    # absent on a stock macOS dev box) and RAQM's shaping changes kerning and
    # therefore getlength(), which would make title_size()/_ellipsize() — and
    # the pixels — platform-dependent. The cards need no complex shaping: text
    # Inter can't cover already falls back to the neutral card (see `covered`);
    # the mono face only ever draws the ASCII wordmark.
    return ImageFont.truetype(
        str(_FONTS / _FACE_FILES[face]),
        size,
        layout_engine=ImageFont.Layout.BASIC,
    )


def _width(text: str, font: ImageFont.FreeTypeFont) -> float:
    return font.getlength(text)


def title_size(title: str) -> int:
    for size in TITLE_SIZES:
        if _width(title, _font("bold", size)) <= WIDTH - 2 * MARGIN:
            return size
    return TITLE_SIZES[-1]


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> str:
    if _width(text, font) <= max_width:
        return text
    while text and _width(text + "…", font) > max_width:
        text = text[:-1]
    return text + "…"


WORDMARK_GAP = 4  # tighter than the 24 px rhythm: the two lines are one mark


def wordmark_lines() -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """ROLL over CALL, monospace, so both lines are the same width (spec
    2026-08-21-search-chrome §1)."""
    mono = _font("mono", 36)
    return [("ROLL", mono), ("CALL", mono)]


def render(data: CardData) -> bytes:
    if not all(
        covered(part) for part in (data.title, data.subtitle, data.stats, data.footer, data.badge)
    ):
        data = fallback_card()
    max_width = WIDTH - 2 * MARGIN
    # (text, font, colour, is_footer, gap_after) top to bottom; empty fields
    # are skipped so the block collapses instead of leaving gaps. is_footer is
    # carried explicitly rather than inferred from the line's position or font
    # object: the badge rides that line, and font identity would silently
    # move it if another line ever shared its size and weight. gap_after lets
    # the two wordmark lines sit closer to each other (WORDMARK_GAP) than to
    # the rest of the block (GAP) — they're one mark, not two lines. Drawn
    # from wordmark_lines() itself, not re-hardcoded, so a change there (or a
    # future third line) is what the renderer actually draws.
    marks = wordmark_lines()
    lines: list[tuple[str, ImageFont.FreeTypeFont, str, bool, int]] = [
        (text, font, BLUE, False, WORDMARK_GAP if i < len(marks) - 1 else GAP)
        for i, (text, font) in enumerate(marks)
    ]
    title_font = _font("bold", title_size(data.title))
    lines.append((_ellipsize(data.title, title_font, max_width), title_font, INK, False, GAP))
    if data.subtitle:
        lines.append(
            (
                _ellipsize(data.subtitle, _font("regular", 40), max_width),
                _font("regular", 40),
                INK,
                False,
                GAP,
            )
        )
    if data.stats:
        lines.append(
            (
                _ellipsize(data.stats, _font("regular", 36), max_width),
                _font("regular", 36),
                MUTED,
                False,
                GAP,
            )
        )
    if data.footer or data.badge:
        # A badge with no footer keeps this (empty-text) line: the badge is
        # then drawn at the margin on its own line — the layout collapses, the
        # badge still shows.
        lines.append((data.footer, _font("regular", 32), MUTED, True, GAP))

    block_height = sum(font.size + gap for _t, font, _c, _f, gap in lines) - lines[-1][4]
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    # draw.text positions each line by its ascender, not its ink: a line with
    # no ascenders (e.g. the all-caps wordmark) or one with descenders (e.g.
    # a subtitle with "g"/"p") leaves a different visual gap than font.size
    # implies. Centre on the actual ink of the first and last lines (measured
    # with getbbox), not the nominal font-size box, or the block drifts.
    first_text, first_font = lines[0][0], lines[0][1]
    last_text, last_font = lines[-1][0], lines[-1][1]
    top_bearing = first_font.getbbox(first_text)[1] if first_text else 0
    bottom_bearing = last_font.getbbox(last_text)[3] if last_text else last_font.size
    y = (HEIGHT - block_height) // 2 + (last_font.size - bottom_bearing - top_bearing) // 2
    for text, font, colour, is_footer, gap in lines:
        if text:
            draw.text((MARGIN, y), text, font=font, fill=colour)
        if is_footer and data.badge:
            # The badge sits on the footer line, right of the footer text.
            x = MARGIN + (_width(data.footer, font) + GAP * 2 if data.footer else 0)
            draw.text((x, y), data.badge, font=_font("bold", 32), fill=BLUE)
        y += font.size + gap

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
