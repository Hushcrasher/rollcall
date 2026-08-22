# Game capsules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the game's capsule on game pages and as a thumbnail on credit lines — from `cover_url` when the catalog has it, else derived from `steam_appid` on Steam's public CDN.

**Architecture:** One model property (`Game.capsule_url`, no column, no migration), three template touches, two functional CSS rules. No bytes pass through Rollcall.

**Spec:** `docs/superpowers/specs/2026-08-21-game-capsules-design.md` — binding.

## Global Constraints

- Typed Python; i18n; comments state constraints; TDD; `static/css/app.css` functional-only (sizes/layout).
- Steam-derived URLs carry `referrerpolicy="no-referrer"` (don't announce member profile URLs to a third party) and `onerror="this.remove()"` (a dead CDN URL leaves no broken-image icon) — both mandated by the spec; the inline `onerror` is the one inline handler in the templates, commented as such.
- Commits DCO (`git commit -s`) ending `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; gates before each: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`.

---

### Task 1: `Game.capsule_url`

**Files:** Modify `games/models.py`; Test `games/tests/test_capsule.py` (new).

- [ ] **Step 1: Failing tests**

```python
"""Game.capsule_url (spec 2026-08-21-game-capsules §1): the catalog's own image
first, else the public Steam CDN asset for the app id, else nothing."""

import pytest

from games.models import STEAM_CAPSULE_URL, Game

pytestmark = pytest.mark.django_db


def test_prefers_the_catalog_cover_url() -> None:
    game = Game.objects.create(title="A", source=Game.Source.MANUAL, cover_url="https://cdn.example/a.jpg", steam_appid=10)
    assert game.capsule_url == "https://cdn.example/a.jpg"


def test_derives_from_the_steam_appid() -> None:
    game = Game.objects.create(title="B", source=Game.Source.MANUAL, steam_appid=620)
    assert game.capsule_url == STEAM_CAPSULE_URL.format(appid=620)
    assert game.capsule_url.startswith("https://") and "/620/" in game.capsule_url


def test_empty_without_either() -> None:
    game = Game.objects.create(title="C", source=Game.Source.MANUAL)
    assert game.capsule_url == ""
```

- [ ] **Step 2: Run** → ImportError (`STEAM_CAPSULE_URL`).

- [ ] **Step 3: Model** — in `games/models.py`, above `class Game`:

```python
# Steam's public store asset for an app — the same 460x215 "header" the store
# pages use. One constant, so a CDN move is a one-line change (the legacy
# cdn.cloudflare.steamstatic.com/steam/apps/<appid>/header.jpg still redirects).
STEAM_CAPSULE_URL = (
    "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
)
```

and on `Game`, after `get_absolute_url`:

```python
    @property
    def capsule_url(self) -> str:
        """The catalog's own image when the seed/IGDB gave one, else the public
        Steam CDN asset for the app id — derived, never fetched or stored by us
        (spec 2026-08-21-game-capsules §1)."""
        if self.cover_url:
            return str(self.cover_url)
        if self.steam_appid:
            return STEAM_CAPSULE_URL.format(appid=self.steam_appid)
        return ""
```

- [ ] **Step 4: Run** green; full gates. **Step 5: Commit** `feat(games): Game.capsule_url — catalog cover, else the Steam CDN header by app id`.

---

### Task 2: Render the capsule on game pages, credit lines, company game lists

**Files:** Modify `templates/games/game_detail.html`, `templates/accounts/profile.html`, `templates/games/company_detail.html`, `static/css/app.css`; Test `games/tests/test_capsule.py` (append), `games/tests/test_pages.py` (the existing cover test must keep passing).

- [ ] **Step 1: Failing tests** (append to `games/tests/test_capsule.py`; imports: `date`, `Client`, `reverse`, `User`, `Contribution`, `Discipline`):

```python
def test_game_page_renders_the_derived_capsule_with_the_guards(client: Client) -> None:
    game = Game.objects.create(title="Derived", source=Game.Source.MANUAL, steam_appid=620)
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    tag = re.search(r'<img class="capsule"[^>]*>', body)
    assert tag, body
    assert STEAM_CAPSULE_URL.format(appid=620) in tag.group(0)
    assert 'referrerpolicy="no-referrer"' in tag.group(0)
    assert 'onerror="this.remove()"' in tag.group(0)
    assert 'loading="lazy"' in tag.group(0)


def test_game_page_without_any_image_has_no_capsule_tag(client: Client) -> None:
    game = Game.objects.create(title="Bare", source=Game.Source.MANUAL)
    assert 'class="capsule"' not in client.get(reverse("games:game", args=[game.slug])).content.decode()


def test_profile_credit_line_shows_a_thumbnail_only_when_there_is_a_url(client: Client) -> None:
    user = User.objects.create_user(email="p@example.com", password="x", display_name="P")
    design = Discipline.objects.get(name="Design")
    with_img = Game.objects.create(title="With", source=Game.Source.MANUAL, steam_appid=620)
    without = Game.objects.create(title="Without", source=Game.Source.MANUAL)
    for game in (with_img, without):
        Contribution.objects.create(user=user, game=game, discipline=design, job_title="Designer", start_date=date(2020, 1, 1))
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert body.count('class="capsule-sm"') == 1
    assert STEAM_CAPSULE_URL.format(appid=620) in body


def test_company_game_list_shows_thumbnails(client: Client) -> None:
    from games.models import Company, GameCompany

    studio = Company.objects.create(name="Studio", source=Company.Source.MANUAL)
    game = Game.objects.create(title="With", source=Game.Source.MANUAL, steam_appid=620)
    GameCompany.objects.create(game=game, company=studio, role=GameCompany.Role.DEVELOPER)
    body = client.get(reverse("games:company", args=[studio.slug])).content.decode()
    assert 'class="capsule-sm"' in body
```

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Templates + CSS**

`templates/games/game_detail.html` — replace the `{% if game.cover_url %}…{% endif %}` block with:

```html
    {% if game.capsule_url %}
      {# onerror is the one inline handler in the templates: a dead CDN URL must leave no broken-image icon (spec 2026-08-21-game-capsules §2). alt="" — the title below is the text. #}
      <img class="capsule" src="{{ game.capsule_url }}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">
    {% endif %}
```

`templates/accounts/profile.html` — inside `<div class="credit">`, before the game link:

```html
        {% if c.game.capsule_url %}<img class="capsule-sm" src="{{ c.game.capsule_url }}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">{% endif %}
```

`templates/games/company_detail.html` — inside each `<li>` of the games list, before the link, the same `capsule-sm` tag with `link.game.capsule_url`.

`static/css/app.css` — append:

```css
/* Game capsules (spec 2026-08-21-game-capsules): Steam's 460x215 header,
   scaled. Sizes only — the image is the decoration. */
.capsule { max-width: 460px; width: 100%; height: auto; display: block; margin-bottom: .5rem; }
.capsule-sm { width: 92px; height: 43px; object-fit: cover; vertical-align: middle; margin-right: .5rem; }
```

- [ ] **Step 4: Run** `games/tests/test_capsule.py games/tests/test_pages.py accounts/tests/test_profile_credits.py -q` (the existing `test_game_page_shows_cover_from_cdn` still passes — `cover_url` is preferred); full gates.
- [ ] **Step 5: Commit** `feat(ui): game capsules on game pages, credit lines and company game lists`.

---

### Task 3: Docs, gates, browser check

- [ ] `docs/01-DESIGN.md`: game page (capsule from `cover_url` or Steam CDN by app id, `no-referrer`, hidden on error) and the credit-line thumbnails; a one-line posture note (Steam-derived hot-linking, decision 2026-08-21). `ROADMAP.md`: Phase 13 block — "Game capsules ✅ (spec 2026-08-21)" with the three items and `- [ ]` follow-up "capsules in search result cards (measure first)".
- [ ] Gates incl. `docker build -q .`.
- [ ] Controller: a fixture game with `steam_appid` (e.g. `/g/<slug>/`) shows the capsule loaded from the Steam CDN; a profile with a credit on it shows the thumbnail; the company page list shows thumbnails; a game without either shows nothing.
- [ ] Commit `docs: record the game capsules`.
