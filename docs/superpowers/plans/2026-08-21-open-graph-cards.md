# Open Graph cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rich link previews for profiles, game pages and the site: server-rendered 1200×630 PNG cards, `og:*`/`twitter:*` meta tags, and an owner-only share row on the profile.

**Architecture:** A new small `cards` app: `render.py` is a pure function (CardData → PNG bytes, Pillow + vendored Inter), `data.py` maps a user/game to CardData (the per-user aggregate lives in `search/services.py`), `views.py` serves cached, rate-limited PNGs, `context_processors.py` provides meta defaults that `ProfileView`/`GameDetailView` override. Templates add the tags and the share row.

**Tech Stack:** Django 6, Pillow (dependency already present), django-ratelimit, Redis cache in prod / locmem in tests, Inter font (SIL OFL 1.1) vendored.

**Spec:** `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md` — binding; read it first.

## Global Constraints

- Every user-facing string through i18n (`gettext` / `{% translate %}`); fully typed Python (`ty` has no Django plugin — reuse existing accommodations: `Any`-bridges, targeted `# ty: ignore[...]`; never new patterns).
- Privacy (project non-negotiables): a card or tag may carry only `display_name`, job title, counts/years, `location_display`, "Open to work"; only `active` credits; only `profile_public=True` profiles get a card (404 otherwise); no tag ever contains an email.
- Rendering values are the spec's §2 table: 1200×630, white, Inter, wordmark 36 px Bold `#0172AD`, title 72→56→44 Bold `#111111` (then ellipsis), subtitle 40 Regular `#111111`, stats 36 Regular `#555555`, footer 32 Regular `#555555`, badge 32 Bold `#0172AD`; 60 px side margins, 24 px rhythm; **text block vertically centred**; no shapes.
- `search/services.py` is the only home of search logic (CLAUDE.md) — the per-user aggregate helper goes there.
- Commits DCO signed-off: `git commit -s`, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Gates before every commit: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check` (Postgres dev DB running via docker compose).
- Comments state constraints/reasons, never narration. `static/css/app.css` stays functional-only.
- Out of scope, do NOT fix here (file as issues if noticed): the game page lists credits of non-public profiles (pre-existing); a Noto fallback font chain.

---

### Task 1: `cards` app skeleton, vendored Inter, pure renderer

**Files:**
- Create: `cards/__init__.py`, `cards/apps.py`, `cards/render.py`, `cards/fonts/Inter-Regular.ttf`, `cards/fonts/Inter-Bold.ttf`, `cards/fonts/OFL.txt`, `cards/tests/__init__.py`
- Modify: `config/settings/base.py` (`INSTALLED_APPS`: add `"cards"` after `"contributions"`/`"search"` — keep the existing ordering style)
- Test: `cards/tests/test_render.py` (new)

**Interfaces:**
- Produces: `cards.render.CardData` (frozen dataclass: `kind: str`, `title: str`, `subtitle: str = ""`, `stats: str = ""`, `footer: str = ""`, `badge: str = ""`), `cards.render.render(data: CardData) -> bytes`, `cards.render.covered(text: str) -> bool`, `cards.render.title_size(title: str) -> int`, constants `WIDTH = 1200`, `HEIGHT = 630`, `DEFAULT_TAGLINE` (lazy i18n string), `default_card() -> CardData` lives in Task 3's `data.py`, so `render.py` exposes `fallback_card() -> CardData` for the non-Latin case.

- [ ] **Step 1: Vendor Inter**

```bash
mkdir -p cards/fonts && cd /tmp && curl -fsSL -o inter.zip https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip && unzip -o -q inter.zip -d inter && find inter -iname 'Inter-Regular.ttf' -o -iname 'Inter-Bold.ttf' -o -iname 'LICENSE.txt' | head
```
Copy the two static TTFs (under `extras/ttf/` in the 4.x zips — locate with the `find` above) to `cards/fonts/Inter-Regular.ttf` and `cards/fonts/Inter-Bold.ttf`, and the OFL licence text to `cards/fonts/OFL.txt`. Sanity: each TTF is 300–450 KB; `file cards/fonts/Inter-Bold.ttf` says TrueType. Then `cd` back to the repo. (~10 MB download, from the font's official GitHub releases; the spec mandates vendoring Inter.)

- [ ] **Step 2: Write the failing tests**

Create `cards/tests/__init__.py` (empty) and `cards/tests/test_render.py`:

```python
"""The card renderer is a pure function: CardData in, PNG bytes out. These
tests pin the spec's §2 layout rules without pixel-matching a design."""

from io import BytesIO

from PIL import Image

from cards.render import HEIGHT, WIDTH, CardData, covered, fallback_card, render, title_size


def _png(data: CardData) -> Image.Image:
    return Image.open(BytesIO(render(data)))


def test_renders_a_1200x630_png() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    assert im.format == "PNG"
    assert im.size == (WIDTH, HEIGHT)


def test_title_shrinks_then_ellipsizes() -> None:
    assert title_size("Sasha Haddad") == 72
    assert title_size("Christelle Bayn-Delacroix de Montmorency") == 56
    assert title_size("A" * 60) == 44  # still too long at 44 → the renderer ellipsizes


def test_text_block_is_vertically_centred() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    rows = [y for y in range(HEIGHT) if any(im.getpixel((x, y)) != (255, 255, 255) for x in range(0, WIDTH, 4))]
    top, bottom = rows[0], HEIGHT - 1 - rows[-1]
    assert abs(top - bottom) <= 6


def test_empty_fields_collapse() -> None:
    full = _png(CardData(kind="profile", title="A", subtitle="B", stats="C", footer="D", badge="E"))
    bare = _png(CardData(kind="profile", title="A"))
    ink = lambda im: sum(1 for y in range(0, HEIGHT, 2) for x in range(0, WIDTH, 2) if im.getpixel((x, y)) != (255, 255, 255))
    assert ink(full) > ink(bare)


def test_coverage_check() -> None:
    assert covered("Zoë Müller-Łukasz · Lyon — 2016–present…")
    assert covered("Ярослав Ковальчук")
    assert not covered("山田 太郎")
    assert not covered("أحمد")


def test_non_latin_name_renders_the_fallback_card() -> None:
    data = CardData(kind="profile", title="山田 太郎", subtitle="Tools Programmer")
    assert render(data) == render(fallback_card())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest cards/tests/test_render.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cards'`.

- [ ] **Step 4: App + renderer**

`cards/__init__.py`: empty. `cards/apps.py`:

```python
from django.apps import AppConfig


class CardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cards"
```

`config/settings/base.py`: add `"cards",` to `INSTALLED_APPS` next to the other project apps.

`cards/render.py`:

```python
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
    return ImageFont.truetype(str(_FONTS / ("Inter-Bold.ttf" if bold else "Inter-Regular.ttf")), size)


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
    if not all(covered(part) for part in (data.title, data.subtitle, data.stats, data.footer, data.badge)):
        data = fallback_card()
    max_width = WIDTH - 2 * MARGIN
    # (text, font, colour) top to bottom; empty fields are skipped so the
    # block collapses instead of leaving gaps.
    lines: list[tuple[str, ImageFont.FreeTypeFont, str]] = [("ROLLCALL", _font(True, 36), BLUE)]
    title_font = _font(True, title_size(data.title))
    lines.append((_ellipsize(data.title, title_font, max_width), title_font, INK))
    if data.subtitle:
        lines.append((_ellipsize(data.subtitle, _font(False, 40), max_width), _font(False, 40), INK))
    if data.stats:
        lines.append((_ellipsize(data.stats, _font(False, 36), max_width), _font(False, 36), MUTED))
    if data.footer or data.badge:
        lines.append((data.footer, _font(False, 32), MUTED))

    block_height = sum(font.size for _, font, _ in lines) + GAP * (len(lines) - 1)
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    y = (HEIGHT - block_height) // 2
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
```

Implementation notes: `ImageFont.FreeTypeFont.size` exists on Pillow ≥ 10; if `ty` flags the PIL types, use a targeted `# ty: ignore[...]`. The badge branch keys on the last line being the footer line — if you restructure, keep the badge on the footer's baseline. `optimize=True` keeps files ~20–40 KB.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest cards/tests/test_render.py -v`
Expected: 6 PASS. If `test_text_block_is_vertically_centred` is off by more than 6 px, the cause is font ascent/descent — measure with `font.getbbox` instead of `font.size` for the first/last lines; do not loosen the tolerance.

- [ ] **Step 6: Full gates + commit**

```bash
git add cards config/settings/base.py
git commit -s -m "feat(cards): app skeleton, vendored Inter (OFL), pure card renderer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `profile_summary()` in `search/services.py`

**Files:**
- Modify: `search/services.py` (extract the per-user aggregate; `_assemble_results` keeps using it)
- Test: `search/tests/test_profile_summary.py` (new)

**Interfaces:**
- Produces: `ProfileSummary` (frozen dataclass: `credits_count: int`, `games_count: int`, `first_year: int`, `last_year: int | None`), `profile_summaries(user_ids: list[int]) -> dict[int, ProfileSummary]`, `profile_summary(user: User) -> ProfileSummary | None` (None when the user has no `active` credit), `ProfileSummary.years_label` property → `"2016–present"` or `"2016–2021"`.

- [ ] **Step 1: Write the failing tests**

```python
"""profile_summary(): the career aggregate the search cards and the OG cards
share. Active credits only — the display rule everywhere (docs/00 #7)."""

from datetime import date

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game
from search.services import profile_summary

pytestmark = pytest.mark.django_db


def _user() -> User:
    return User.objects.create_user(email="s@example.com", password="x", display_name="S")


def _credit(user: User, title: str, start: date, end: date | None, status: str = Contribution.Status.ACTIVE) -> None:
    Contribution.objects.create(
        user=user, game=Game.objects.create(title=title, source=Game.Source.MANUAL),
        discipline=Discipline.objects.get(name="Design"), job_title="Designer",
        start_date=start, end_date=end, status=status,
    )


def test_no_active_credit_means_no_summary() -> None:
    user = _user()
    _credit(user, "Pending Game", date(2020, 1, 1), None, status=Contribution.Status.PENDING)
    assert profile_summary(user) is None


def test_counts_games_distinctly_and_reads_present_from_an_open_end() -> None:
    user = _user()
    _credit(user, "A", date(2016, 3, 1), date(2018, 1, 1))
    _credit(user, "B", date(2019, 1, 1), None)
    s = profile_summary(user)
    assert s is not None
    assert (s.credits_count, s.games_count, s.first_year, s.last_year) == (2, 2, 2016, None)
    assert s.years_label == "2016–present"


def test_closed_career_reads_the_last_year() -> None:
    user = _user()
    _credit(user, "A", date(2010, 1, 1), date(2012, 6, 1))
    s = profile_summary(user)
    assert s is not None and s.years_label == "2010–2012"
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest search/tests/test_profile_summary.py -q` → ImportError.

- [ ] **Step 3: Extract the aggregate**

In `search/services.py`, add (near `PersonResult`):

```python
@dataclass(frozen=True)
class ProfileSummary:
    """Career-wide aggregate over ACTIVE credits — shared by the search cards
    and the OG cards so the two never disagree."""

    credits_count: int
    games_count: int
    first_year: int
    last_year: int | None  # None = an open end exists, i.e. "present"

    @property
    def years_label(self) -> str:
        return f"{self.first_year}–{self.last_year if self.last_year else _('present')}"


def profile_summaries(user_ids: list[int]) -> dict[int, ProfileSummary]:
    rows = (
        Contribution.objects.filter(status=Contribution.Status.ACTIVE, user_id__in=user_ids)
        .values("user_id")
        .annotate(
            credits_count=Count("id"),
            games_count=Count("game", distinct=True),
            first_start=Min("start_date"),
            last_end=Max("end_date"),
            open_count=Count("id", filter=Q(end_date__isnull=True)),
        )
    )
    summaries: dict[int, ProfileSummary] = {}
    for row in rows:
        # open_count > 0 is what "present" means. Max(end_date) can't answer it:
        # SQL MAX ignores NULLs, so an ongoing credit is invisible to it.
        still_active = row["open_count"] > 0
        summaries[row["user_id"]] = ProfileSummary(
            credits_count=row["credits_count"],
            games_count=row["games_count"],
            first_year=row["first_start"].year,
            last_year=None if still_active else row["last_end"].year,
        )
    return summaries


def profile_summary(user: User) -> ProfileSummary | None:
    return profile_summaries([user.pk]).get(user.pk)
```

(`_` = `gettext` — import `from django.utils.translation import gettext as _` if the module lacks it.) Then make `_assemble_results` use it: replace its `stats` dict construction and the `row = stats[user.pk]` / `still_active` logic with `summaries = profile_summaries(user_ids)` and `summary = summaries[user.pk]`, passing `credits_count=summary.credits_count`, `games_count=summary.games_count`, `first_year=summary.first_year`, `last_year=summary.last_year`. Keep the "indexed, not .get()" comment and behavior. Remove the now-unused imports only if they become unused.

- [ ] **Step 4: Run** — the new file and the whole search suite: `uv run pytest search/ -q` → all green (the people-search query is a non-negotiable test zone; nothing may change there).

- [ ] **Step 5: Full gates + commit**

```bash
git add search/services.py search/tests/test_profile_summary.py
git commit -s -m "refactor(search): extract profile_summary() — one career aggregate for search and cards

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `cards/data.py`, the three PNG endpoints, cache + rate limit

**Files:**
- Create: `cards/data.py`, `cards/views.py`, `cards/urls.py`
- Modify: `config/urls.py` (include `cards.urls` at root, before the accounts/games includes is fine — the `card.png` suffix makes the routes unambiguous)
- Test: `cards/tests/test_views.py` (new), `cards/tests/test_data.py` (new)

**Interfaces:**
- Produces: `cards.data.profile_card(user) -> CardData`, `game_card(game) -> CardData`, `default_card() -> CardData`, `token(data) -> str` (10 hex chars), `card_url(request, url_name, data, *args) -> str` (absolute, with `?v=`); URL names `cards:profile` (`u/<slug>/card.png`), `cards:game` (`g/<slug>/card.png`), `cards:default` (`card.png`).

- [ ] **Step 1: Write the failing tests**

`cards/tests/test_data.py`:

```python
from datetime import date

import pytest

from accounts.models import User
from cards.data import default_card, game_card, profile_card, token
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _user(**kw) -> User:
    return User.objects.create_user(email=kw.pop("email", "p@example.com"), password="x", display_name="Sasha Haddad", **kw)


def _credit(user: User, game: Game, job: str, start: date, end: date | None) -> None:
    Contribution.objects.create(user=user, game=game, discipline=Discipline.objects.get(name="Design"),
                                job_title=job, start_date=start, end_date=end)


def test_profile_card_maps_name_latest_job_stats_location_badge() -> None:
    user = _user(open_to_work=True, location="Lyon", country="FR")
    g1 = Game.objects.create(title="A", source=Game.Source.MANUAL)
    g2 = Game.objects.create(title="B", source=Game.Source.MANUAL)
    _credit(user, g1, "Junior Designer", date(2016, 1, 1), date(2018, 1, 1))
    _credit(user, g2, "Tools Programmer", date(2019, 1, 1), None)
    data = profile_card(user)
    assert data.kind == "profile" and data.title == "Sasha Haddad"
    assert data.subtitle == "Tools Programmer"
    assert data.stats == "2 credits · 2 games · 2016–present"
    assert data.footer == user.location_display and "Lyon" in data.footer
    assert data.badge == "Open to work"


def test_profile_card_without_credits_has_no_stats() -> None:
    data = profile_card(_user())
    assert data.subtitle == "" and data.stats == "" and data.badge == ""


def test_game_card_counts_public_people_only() -> None:
    game = Game.objects.create(title="Lost Depths", source=Game.Source.MANUAL, release_date=date(2021, 5, 1))
    _credit(_user(email="a@example.com"), game, "Artist", date(2020, 1, 1), None)
    _credit(_user(email="b@example.com", profile_public=False), game, "Artist", date(2020, 1, 1), None)
    data = game_card(game)
    assert data.title == "Lost Depths" and data.subtitle == "Released 2021"
    assert data.stats == "1 person credited on Rollcall"


def test_game_card_with_nobody_invites_the_first_claim() -> None:
    game = Game.objects.create(title="Empty", source=Game.Source.MANUAL)
    assert game_card(game).stats == "Be the first to claim a credit"


def test_token_changes_with_the_data() -> None:
    a = default_card()
    assert len(token(a)) == 10
    assert token(a) != token(profile_card(_user()))
```

`cards/tests/test_views.py`:

```python
from io import BytesIO
from typing import Any
from unittest import mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from PIL import Image

from accounts.models import User
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


def _png(response: Any) -> Image.Image:
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    return Image.open(BytesIO(response.content))


def test_profile_card_is_a_png_with_cache_headers(client: Client) -> None:
    user = User.objects.create_user(email="p@example.com", password="x", display_name="P")
    response = client.get(reverse("cards:profile", args=[user.slug]))
    assert _png(response).size == (1200, 630)
    assert "max-age=3600" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"


def test_private_profile_has_no_card(client: Client) -> None:
    user = User.objects.create_user(email="h@example.com", password="x", display_name="H", profile_public=False)
    assert client.get(reverse("cards:profile", args=[user.slug])).status_code == 404
    client.force_login(user)  # not even for the owner: crawlers never carry a session
    assert client.get(reverse("cards:profile", args=[user.slug])).status_code == 404


def test_game_and_default_cards(client: Client) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    assert _png(client.get(reverse("cards:game", args=[game.slug]))).size == (1200, 630)
    assert _png(client.get(reverse("cards:default"))).size == (1200, 630)
    assert client.get("/u/nobody-here/card.png").status_code == 404


def test_second_request_is_served_from_cache(client: Client) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    url = reverse("cards:profile", args=[user.slug])
    with mock.patch("cards.views.render", wraps=__import__("cards.render", fromlist=["render"]).render) as spy:
        client.get(url)
        client.get(url)
    assert spy.call_count == 1


def test_cards_are_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.PROFILE_RATELIMIT = "2/m"
    cache.clear()
    url = reverse("cards:default")
    client.get(url)
    client.get(url)
    assert client.get(url).status_code == 403
```

- [ ] **Step 2: Run to verify failure** — both files: `ModuleNotFoundError: cards.data` / `NoReverseMatch`.

- [ ] **Step 3: data, views, urls**

`cards/data.py`:

```python
"""CardData builders — the only fields a card may ever show (spec §2)."""

import hashlib
from dataclasses import astuple
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from accounts.models import User
from cards.render import DEFAULT_TAGLINE, CardData
from contributions.models import Contribution
from games.models import Game
from search.services import profile_summary


def default_card() -> CardData:
    return CardData(kind="default", title="ROLLCALL", footer=str(DEFAULT_TAGLINE))


def profile_card(user: User) -> CardData:
    latest = (
        Contribution.objects.filter(user=user, status=Contribution.Status.ACTIVE)
        .order_by("-start_date", "-id")
        .values_list("job_title", flat=True)
        .first()
    )
    summary = profile_summary(user)
    stats = ""
    if summary:
        stats = " · ".join(
            [
                ngettext("%(n)d credit", "%(n)d credits", summary.credits_count) % {"n": summary.credits_count},
                ngettext("%(n)d game", "%(n)d games", summary.games_count) % {"n": summary.games_count},
                summary.years_label,
            ]
        )
    return CardData(
        kind="profile",
        title=user.display_name,
        subtitle=latest or "",
        stats=stats,
        footer=user.location_display,
        badge=_("Open to work") if user.open_to_work else "",
    )


def game_card(game: Game) -> CardData:
    people = (
        Contribution.objects.filter(game=game, status=Contribution.Status.ACTIVE, user__profile_public=True)
        .values("user_id")
        .distinct()
        .count()
    )
    stats = (
        ngettext("%(n)d person credited on Rollcall", "%(n)d people credited on Rollcall", people) % {"n": people}
        if people
        else _("Be the first to claim a credit")
    )
    release: Any = game.release_date
    return CardData(
        kind="game",
        title=game.title,
        subtitle=_("Released %(year)d") % {"year": release.year} if release else "",
        stats=stats,
    )


def token(data: CardData) -> str:
    """Short, stable digest of what the card shows — a changed profile gets a
    new image URL, so networks that cache og:image for days refetch it."""
    return hashlib.sha256(repr(astuple(data)).encode()).hexdigest()[:10]


def card_url(request: HttpRequest, url_name: str, data: CardData, *args: Any) -> str:
    return request.build_absolute_uri(reverse(url_name, args=args)) + "?v=" + token(data)
```

`cards/views.py`:

```python
"""The card endpoints: cached, rate-limited PNGs. Only public profiles have a
card — crawlers fetch without a session, so the owner exemption of the profile
page does not apply here."""

from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django_ratelimit.decorators import ratelimit

from accounts.models import User
from cards.data import default_card, game_card, profile_card, token
from cards.render import CardData, render
from games.models import Game

CACHE_SECONDS = 3600
# Named group, house rule: an unnamed decorator derives its group from the
# view's qualname, so a rename would silently move the counter.
_RATELIMIT_GROUP = "card"


def _card_rate(group: str, request: HttpRequest) -> str:
    return settings.PROFILE_RATELIMIT


def _png_response(kind: str, key: str, data: CardData) -> HttpResponse:
    png = cache.get_or_set(f"card:{kind}:{key}:{token(data)}", lambda: render(data), CACHE_SECONDS)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method="GET", block=True)
def profile_card_view(request: HttpRequest, slug: str) -> HttpResponse:
    user = get_object_or_404(User, slug=slug, profile_public=True)
    return _png_response("profile", slug, profile_card(user))


@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method="GET", block=True)
def game_card_view(request: HttpRequest, slug: str) -> HttpResponse:
    game = get_object_or_404(Game, slug=slug)
    return _png_response("game", slug, game_card(game))


@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method="GET", block=True)
def default_card_view(request: HttpRequest) -> HttpResponse:
    return _png_response("default", "site", default_card())
```

(`Callable` import only if used; drop otherwise. `cache.get_or_set` with a lambda is the house-compatible form — if `ty` complains about the lambda's type, bind `def _render() -> bytes: return render(data)`.)

`cards/urls.py`:

```python
from django.urls import path

from cards import views

app_name = "cards"

urlpatterns = [
    path("u/<slug:slug>/card.png", views.profile_card_view, name="profile"),
    path("g/<slug:slug>/card.png", views.game_card_view, name="game"),
    path("card.png", views.default_card_view, name="default"),
]
```

`config/urls.py`: add `path("", include("cards.urls")),` next to the other root includes.

- [ ] **Step 4: Run** — `uv run pytest cards/ -q` → green. If `test_second_request_is_served_from_cache` fails because the test cache backend is dummy, check `config/settings/test.py`: tests need a real in-memory cache (`django.core.cache.backends.locmem.LocMemCache`) — add it there if absent, with a comment that the card views and rate limits depend on it.

- [ ] **Step 5: Full gates + commit**

```bash
git add cards config/urls.py config/settings/test.py
git commit -s -m "feat(cards): profile, game and default card endpoints — cached, rate-limited, public profiles only

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Meta tags — context processor, `base.html`, view overrides

**Files:**
- Create: `cards/context_processors.py`
- Modify: `config/settings/base.py` (TEMPLATES `context_processors`: add `"cards.context_processors.og_defaults"`), `templates/base.html` (`{% block meta %}` in `<head>`), `accounts/views.py` (`ProfileView.get_context_data`), `games/views.py` (`GameDetailView.get_context_data`)
- Test: `cards/tests/test_meta.py` (new)

**Interfaces:**
- Consumes: `card_url`, `profile_card`, `game_card`, `default_card` (Task 3).
- Produces: context keys `og_title`, `meta_description`, `og_type`, `og_url`, `og_image` on every page.

- [ ] **Step 1: Write the failing tests**

```python
"""Every page carries Open Graph tags; profiles and games override them.
Absolute URLs, a cache-busting token, and never an email (spec §1)."""

import re
from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _meta(body: str, prop: str) -> str:
    match = re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', body)
    assert match, f"no {prop} tag"
    return match.group(1)


def test_home_carries_default_tags_with_absolute_urls(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    assert _meta(body, "og:title") == "Rollcall"
    assert _meta(body, "og:url").startswith("http://testserver/")
    assert _meta(body, "og:image").startswith("http://testserver/card.png?v=")
    assert _meta(body, "twitter:card") == "summary_large_image"
    assert _meta(body, "og:image:width") == "1200"


def test_profile_overrides_and_token_tracks_the_data(client: Client) -> None:
    user = User.objects.create_user(email="m@example.com", password="x", display_name="Mina Okafor")
    url = reverse("accounts:profile", args=[user.slug])
    before = _meta(client.get(url).content.decode(), "og:image")
    assert before.startswith(f"http://testserver{reverse('cards:profile', args=[user.slug])}?v=")
    Contribution.objects.create(
        user=user, game=Game.objects.create(title="G", source=Game.Source.MANUAL),
        discipline=Discipline.objects.get(name="Design"), job_title="Producer", start_date=date(2020, 1, 1),
    )
    body = client.get(url).content.decode()
    assert _meta(body, "og:image") != before
    assert _meta(body, "og:title") == "Mina Okafor · Rollcall"
    assert _meta(body, "og:type") == "profile"
    assert "1 credit" in _meta(body, "og:description")
    assert _meta(body, "og:url") == f"http://testserver{url}"


def test_game_overrides(client: Client) -> None:
    game = Game.objects.create(title="Lost Depths", source=Game.Source.MANUAL, release_date=date(2021, 1, 1))
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    assert _meta(body, "og:title") == "Lost Depths (2021) · Rollcall"
    assert _meta(body, "og:image").startswith(f"http://testserver{reverse('cards:game', args=[game.slug])}?v=")


def test_no_meta_tag_ever_carries_an_email(client: Client) -> None:
    user = User.objects.create_user(email="leak@example.com", password="x", display_name="Leak Test")
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    for content in re.findall(r'<meta [^>]*content="([^"]*)"', body):
        assert "@" not in content
```

- [ ] **Step 2: Run to verify failure** — no `og:title` tag.

- [ ] **Step 3: Context processor, template, views**

`cards/context_processors.py`:

```python
"""Open Graph defaults for every page; profile and game views override them
(spec §1). og:url drops the query string — the canonical page, not a filter set."""

from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext as _

from cards.data import card_url, default_card


def og_defaults(request: HttpRequest) -> dict[str, Any]:
    return {
        "og_title": "Rollcall",
        "meta_description": _("Find people by what they've worked on — a public credits register for the game industry."),
        "og_type": "website",
        "og_url": request.build_absolute_uri(request.path),
        "og_image": card_url(request, "cards:default", default_card()),
    }
```

`config/settings/base.py`: append `"cards.context_processors.og_defaults",` to the `context_processors` list.

`templates/base.html`, after the `<title>` line:

```html
  {% block meta %}
  <meta name="description" content="{{ meta_description }}">
  <meta property="og:site_name" content="Rollcall">
  <meta property="og:type" content="{{ og_type }}">
  <meta property="og:title" content="{{ og_title }}">
  <meta property="og:description" content="{{ meta_description }}">
  <meta property="og:url" content="{{ og_url }}">
  <meta property="og:image" content="{{ og_image }}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  {% endblock %}
```

`accounts/views.py` `ProfileView.get_context_data`, before `return context` (imports: `from cards.data import card_url, profile_card`):

```python
        card = profile_card(self.object)
        context["og_title"] = f"{self.object.display_name} · Rollcall"
        context["og_type"] = "profile"
        context["og_url"] = self.request.build_absolute_uri(self.object.get_absolute_url())
        context["og_image"] = card_url(self.request, "cards:profile", card, self.object.slug)
        if card.stats:
            context["meta_description"] = card.stats
```

`games/views.py` `GameDetailView.get_context_data` (imports: `from cards.data import card_url, game_card`):

```python
        card = game_card(self.object)
        year = f" ({self.object.release_date.year})" if self.object.release_date else ""
        context["og_title"] = f"{self.object.title}{year} · Rollcall"
        context["og_url"] = self.request.build_absolute_uri(self.object.get_absolute_url())
        context["og_image"] = card_url(self.request, "cards:game", card, self.object.slug)
        context["meta_description"] = card.stats
```

(`release_date` is a `DateField` — if `ty` sees it as the field, bridge with `release: Any = self.object.release_date`.)

- [ ] **Step 4: Run** — `uv run pytest cards/tests/test_meta.py -q` → green; then the full suite (template-string tests elsewhere must still pass — the `<head>` grew, nothing in `<main>` changed).

- [ ] **Step 5: Full gates + commit**

```bash
git add cards/context_processors.py config/settings/base.py templates/base.html accounts/views.py games/views.py cards/tests/test_meta.py
git commit -s -m "feat(cards): Open Graph meta tags on every page; profiles and games override them

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Share row on the owner's profile

**Files:**
- Modify: `templates/accounts/profile.html`, `accounts/views.py` (one context key), `static/css/app.css` (one functional rule, only if the row needs inline-flex)
- Test: `accounts/tests/test_share_row.py` (new)

**Interfaces:**
- Consumes: `is_owner`, `private_notice`, `og_url` (Task 4), `cards:profile`.

- [ ] **Step 1: Write the failing tests**

```python
"""The share row — the nudge that starts the share loop. Owner-only; a private
profile gets the invitation to go public instead (spec §3)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def _main(body: str) -> str:
    return body[body.index("<main") : body.index("</main>")]


def test_owner_sees_copy_link_networks_and_preview(client: Client) -> None:
    user = User.objects.create_user(email="o@example.com", password="x", display_name="Owner")
    client.force_login(user)
    main = _main(client.get(reverse("accounts:profile", args=[user.slug])).content.decode())
    assert "Share your profile" in main and "Copy link" in main
    assert "linkedin.com/sharing/share-offsite/?url=http%3A%2F%2Ftestserver%2Fu%2F" in main
    assert "bsky.app/intent/compose?text=" in main
    assert "twitter.com/intent/tweet?" in main
    assert reverse("cards:profile", args=[user.slug]) in main


def test_visitors_never_see_the_row(client: Client) -> None:
    owner = User.objects.create_user(email="o@example.com", password="x", display_name="Owner")
    other = User.objects.create_user(email="v@example.com", password="x", display_name="V")
    client.force_login(other)
    assert "Share your profile" not in _main(client.get(reverse("accounts:profile", args=[owner.slug])).content.decode())
    client.logout()
    assert "Share your profile" not in _main(client.get(reverse("accounts:profile", args=[owner.slug])).content.decode())


def test_private_owner_is_invited_to_go_public(client: Client) -> None:
    user = User.objects.create_user(email="p@example.com", password="x", display_name="P", profile_public=False)
    client.force_login(user)
    main = _main(client.get(reverse("accounts:profile", args=[user.slug])).content.decode())
    assert "make it public to share it" in main
    assert "Copy link" not in main
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Template + context**

`accounts/views.py` `ProfileView.get_context_data`: add `context["share_url"] = context["og_url"]` (set after `og_url`), and `context["share_text"] = _("%(name)s on Rollcall") % {"name": self.object.display_name}` (use the module's `gettext`).

`templates/accounts/profile.html`, right after the `{% if is_owner %}…Edit my profile / View as member…{% endif %}` paragraph, add:

```html
    {% if is_owner %}
      {% if profile_user.profile_public %}
        <p class="share-row">
          <span>{% translate "Share your profile:" %}</span>
          <button type="button" data-copy="{{ share_url }}">{% translate "Copy link" %}</button>
          <noscript><code>{{ share_url }}</code></noscript>
          <a href="https://www.linkedin.com/sharing/share-offsite/?url={{ share_url|urlencode:'' }}" target="_blank" rel="noopener">LinkedIn</a> ·
          <a href="https://bsky.app/intent/compose?text={{ share_text|urlencode:'' }}%20{{ share_url|urlencode:'' }}" target="_blank" rel="noopener">Bluesky</a> ·
          <a href="https://twitter.com/intent/tweet?url={{ share_url|urlencode:'' }}&amp;text={{ share_text|urlencode:'' }}" target="_blank" rel="noopener">X</a> ·
          <a href="{% url 'cards:profile' profile_user.slug %}" target="_blank" rel="noopener">{% translate "Preview your card" %}</a>
        </p>
        <script>
          document.querySelector(".share-row [data-copy]").addEventListener("click", function () {
            var button = this, label = button.textContent;
            navigator.clipboard.writeText(button.dataset.copy).then(function () {
              button.textContent = "{% translate 'Copied' %}";
              setTimeout(function () { button.textContent = label; }, 2000);
            });
          });
        </script>
      {% else %}
        <p class="share-row">{% translate "Your profile is private — make it public to share it." %} <a href="{% url 'accounts:profile_edit' %}">{% translate "Change this" %}</a></p>
      {% endif %}
    {% endif %}
```

`static/css/app.css` (functional only): `.share-row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline; }` and `.share-row button { width: auto; margin: 0; }` (Pico makes buttons full-width by default — width is layout). If the `Copy link` button renders solid-primary and competes with the page, de-emphasize it the same way the nav log-out button is (`background: none; border: none; color: var(--pico-primary);` with attribute-selector specificity) — see the existing comment in `app.css`.

- [ ] **Step 4: Run** — `uv run pytest accounts/tests/test_share_row.py accounts/tests/test_profile_preview.py -q` (the preview test must keep passing: the row is under `is_owner`, which is False in preview).

- [ ] **Step 5: Full gates + commit**

```bash
git add templates/accounts/profile.html accounts/views.py static/css/app.css accounts/tests/test_share_row.py
git commit -s -m "feat(profile): owner-only share row — copy link, LinkedIn/Bluesky/X, card preview

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Docs, final gates, browser verification

**Files:**
- Modify: `docs/01-DESIGN.md` (profile §: share row + card; SEO/meta §), `docs/02-ARCHITECTURE.md` (apps list: `cards`), `docs/03-TECH-STACK.md` (Inter, OFL, vendored under `cards/fonts/`), `ROADMAP.md` (new phase entry, after the last one)

- [ ] **Step 1: Docs** — in each doc's own voice: every page carries OG/twitter tags; profiles (public only) and games have generated 1200×630 cards at `/u/<slug>/card.png`, `/g/<slug>/card.png`, default `/card.png`, cached 1 h, rate-limited, cache-busted by a data token; the owner's share row; the non-Latin fallback (v2: Noto). ROADMAP block:

```markdown
## Phase 10 — Open Graph cards ✅ (spec 2026-08-21)

Goal: a Rollcall link previews richly wherever it is pasted; sharing a profile is one click.

- [x] `cards` app: pure Pillow renderer (Inter, OFL), `CardData` = the only fields a card may show
- [x] `/u/<slug>/card.png` (public profiles only), `/g/<slug>/card.png`, `/card.png` — cached 1 h, rate-limited, `?v=` token
- [x] `og:*` / `twitter:card` tags on every page; profile and game overrides; no tag ever carries an email
- [x] `profile_summary()` in `search/services.py` — one career aggregate for search cards and OG cards
- [x] Owner-only share row: copy link, LinkedIn / Bluesky / X, card preview
- [ ] v2: Noto fallback chain for non-Latin names (v1 renders the neutral card)
```

- [ ] **Step 2: Final gates** — `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check && docker build -q .` (the font files ride in the image like any package file; if the Dockerfile copies an allow-list of paths, add `cards/`).

- [ ] **Step 3: Browser verification (controller)** — dev server: `/card.png`, a profile card, a game card render as 1200×630 PNGs; the profile page source shows the tags with absolute URLs; the owner's share row renders and `Copy link` works; a private profile's card 404s; the meta block doesn't break the mobile layout.

- [ ] **Step 4: Commit**

```bash
git add docs/01-DESIGN.md docs/02-ARCHITECTURE.md docs/03-TECH-STACK.md ROADMAP.md
git commit -s -m "docs: record the Open Graph cards (tags, card endpoints, share row)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
