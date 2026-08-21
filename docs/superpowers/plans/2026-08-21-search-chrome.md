# Search chrome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stacked monospace ROLL/CALL wordmark (nav + OG cards), filters in two named rows, trimmed banner, `Message` buttons.

**Architecture:** Templates + `app.css` + one renderer change. No model, no migration, no new dependency; one vendored font file (JetBrains Mono Bold, OFL) for the card wordmark.

**Tech Stack:** Django templates, Pico classless, Pillow.

**Spec:** `docs/superpowers/specs/2026-08-21-search-chrome-design.md` — binding.

## Global Constraints

- Every user-facing string through i18n; typed Python; comments state constraints.
- `static/css/app.css` is functional-only — the ONE exception is the `.wordmark` font-family rule, which the spec mandates (owner decision 2026-08-21); say so in the comment.
- Tests scope nav assertions to `body[: body.index("</header>")]` and page assertions to `<main>`.
- Commits DCO (`git commit -s`) ending `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; gates before each: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`.

---

### Task 1: Stacked wordmark — nav and OG card

**Files:**
- Modify: `templates/base.html` (nav brand), `static/css/app.css`, `cards/render.py`, `config/tests/test_base_template.py`
- Create: `cards/fonts/JetBrainsMono-Bold.ttf`, `cards/fonts/OFL-JetBrainsMono.txt`
- Test: `cards/tests/test_render.py` (append), `config/tests/test_base_template.py` (edit)

- [ ] **Step 1: Vendor JetBrains Mono Bold**

```bash
cd /tmp && curl -fsSL -o jbm.zip https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip && unzip -o -q jbm.zip -d jbm && find jbm -name 'JetBrainsMono-Bold.ttf' -o -name 'OFL.txt' | head
```
Copy `fonts/ttf/JetBrainsMono-Bold.ttf` → `cards/fonts/JetBrainsMono-Bold.ttf` and the OFL text → `cards/fonts/OFL-JetBrainsMono.txt` (keep Inter's `OFL.txt` as is). `file` must say TrueType; size ~270 KB.

- [ ] **Step 2: Failing tests**

`config/tests/test_base_template.py` — in `test_anonymous_nav_leads_with_the_declare_cta`, replace `assert "ROLLCALL" in header` with:

```python
    # Stacked wordmark: two four-letter lines in a monospace face (spec
    # 2026-08-21-search-chrome §1) — never the one-word form.
    assert 'class="wordmark"' in header
    assert "ROLL<br>CALL" in header
    assert "ROLLCALL" not in header
```

Append to `cards/tests/test_render.py`:

```python
def test_wordmark_is_two_stacked_lines_in_the_mono_face() -> None:
    from cards.render import wordmark_lines

    assert [text for text, _font in wordmark_lines()] == ["ROLL", "CALL"]
    assert {font.getname()[0] for _text, font in wordmark_lines()} == {"JetBrains Mono"}


def test_card_still_renders_and_centres_with_the_stacked_wordmark() -> None:
    im = _png(CardData(kind="profile", title="Sasha Haddad", subtitle="Tools Programmer"))
    assert im.size == (WIDTH, HEIGHT)
    rows = [y for y in range(HEIGHT) if any(im.getpixel((x, y)) != (255, 255, 255) for x in range(0, WIDTH, 4))]
    assert abs(rows[0] - (HEIGHT - 1 - rows[-1])) <= 6
```

Run: `uv run pytest config/tests/test_base_template.py cards/tests/test_render.py -q` → FAIL (no `wordmark`, no `wordmark_lines`).

- [ ] **Step 3: Nav + CSS**

`templates/base.html`: `<li><a href="{% url 'home' %}"><strong>ROLLCALL</strong></a></li>` → `<li><a href="{% url 'home' %}"><strong class="wordmark">ROLL<br>CALL</strong></a></li>`.

`static/css/app.css`, near the nav rules:

```css
/* The wordmark: ROLL over CALL. Monospace is the mechanism, not decoration —
   two four-glyph lines are the same width by construction. The font-family
   here is the one aesthetic rule in this file, mandated by the owner on
   2026-08-21 (spec 2026-08-21-search-chrome §1). System stack, nothing vendored. */
.wordmark {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  display: inline-block; line-height: .95; letter-spacing: .04em;
}
```

- [ ] **Step 4: Renderer**

`cards/render.py`:
- Generalise the font loader: `def _font(face: str, size: int)` with `face in {"regular", "bold", "mono"}` mapping to `Inter-Regular.ttf` / `Inter-Bold.ttf` / `JetBrainsMono-Bold.ttf` (keep the `layout_engine=BASIC` comment). Update every call site (`_font(True, …)` → `_font("bold", …)`, `_font(False, …)` → `_font("regular", …)`).
- Add:

```python
WORDMARK_GAP = 4  # tighter than the 24 px rhythm: the two lines are one mark


def wordmark_lines() -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """ROLL over CALL, monospace, so both lines are the same width (spec
    2026-08-21-search-chrome §1)."""
    mono = _font("mono", 36)
    return [("ROLL", mono), ("CALL", mono)]
```

- The `lines` tuple gains a fifth element `gap_after: int`. Build it as: the two wordmark lines (`BLUE`, not footer, gap `WORDMARK_GAP` after `ROLL`, `GAP` after `CALL`), then the existing title/subtitle/stats/footer lines with `GAP`. `block_height = sum(font.size + gap for _t, font, _c, _f, gap in lines) - lines[-1][4]`; the draw loop advances `y += font.size + gap`. The centring code keeps using the first and last lines' ink bearings unchanged.

- [ ] **Step 5: Run** — the two test files green; then full gates. Existing render tests (`test_renders_a_1200x630_png`, vertical centring, fallback byte-equality) must pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add templates/base.html static/css/app.css cards/render.py cards/fonts/JetBrainsMono-Bold.ttf cards/fonts/OFL-JetBrainsMono.txt cards/tests/test_render.py config/tests/test_base_template.py
git commit -s -m "feat(ui): stacked ROLL/CALL wordmark in the nav and on the OG cards (JetBrains Mono, OFL)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Filters in two rows

**Files:**
- Modify: `templates/search/people_search.html` (filter form), `search/forms.py` (help texts), `static/css/app.css`
- Test: `search/tests/test_filter_rows.py` (new)

- [ ] **Step 1: Failing tests**

```python
"""Two named filter rows (spec 2026-08-21-search-chrome §2): the game row and
the person row, every filter visible without scrolling on a laptop."""

import re

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _fieldsets(body: str) -> dict[str, str]:
    return {
        re.search(r"<legend>([^<]+)</legend>", fs).group(1).strip(): fs  # type: ignore[union-attr]
        for fs in re.findall(r"<fieldset[^>]*>.*?</fieldset>", body, re.S)
    }


def test_two_rows_hold_the_right_filters(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    rows = _fieldsets(body)
    assert set(rows) == {"Games they worked on", "About the person"}
    game, person = rows["Games they worked on"], rows["About the person"]
    for name in ("engines", "genres", "min_rating"):
        assert f'name="{name}"' in game or f'id="id_{name}"' in game
    for name in ("discipline", "countries", "year_from", "open_to_work"):
        assert f'name="{name}"' in person or f'id="id_{name}"' in person


def test_data_caveats_are_one_footnote(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert main.count("Steam-linked games only") == 1
    assert "Matches games using any of the selected." not in main
```

Run → FAIL (no fieldsets).

- [ ] **Step 2: Form help texts** (`search/forms.py`): remove `help_text` from `engines`, `genres`, `countries`, `min_rating` (keep the comments explaining the data caveat, moved next to the template footnote). Keep labels.

- [ ] **Step 3: Template** — replace the form body (from `{{ form.non_field_errors }}` to the Search button) with:

```html
    {{ form.non_field_errors }}
    <fieldset class="filter-row">
      <legend>{% translate "Games they worked on" %}</legend>
      {% for field in form.game_fields %}
        <div class="filter">
          <label for="{{ field.id_for_label }}">{{ field.label }}</label>
          {{ field.errors }}{{ field }}
        </div>
      {% endfor %}
    </fieldset>
    <fieldset class="filter-row">
      <legend>{% translate "About the person" %}</legend>
      {% for field in form.person_fields %}
        <div class="filter">
          {% if field.name == "open_to_work" %}
            <label>{{ field }} {{ field.label }}</label>{{ field.errors }}
          {% else %}
            <label for="{{ field.id_for_label }}">{{ field.label }}</label>
            {{ field.errors }}{{ field }}
          {% endif %}
        </div>
      {% endfor %}
    </fieldset>
    {# The data caveat once, not per field: genre and rating data cover Steam-linked games only (ROADMAP "Non-Steam facet coverage"). #}
    <p><small class="muted">{% translate "Genre and rating data currently cover Steam-linked games only." %}</small></p>
    <button type="submit">{% translate "Search" %}</button>
```

Keep the existing `{% comment %}` about labels vs legends but amend it: legends are fine here because each control keeps its own `<label for>`; the help texts that caused the old repetition are gone.

`search/forms.py` — add next to `typeahead_fields()`:

```python
    def game_fields(self) -> list[forms.BoundField]:
        """Row 1 — what they worked on (spec 2026-08-21-search-chrome §2)."""
        return [self["engines"], self["genres"], self["min_rating"]]

    def person_fields(self) -> list[forms.BoundField]:
        """Row 2 — who they are."""
        return [self["discipline"], self["countries"], self["year_from"], self["open_to_work"]]
```

(`typeahead_fields()` stays — the chips JS and the payload-guard test depend on it.)

`static/css/app.css`:

```css
/* Filter rows (spec 2026-08-21-search-chrome §2): four columns on a laptop,
   two on a tablet, one on a phone. */
.filter-row { border: 0; padding: 0; margin: 0 0 .5rem; display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: 0 1rem; align-items: start; }
.filter-row legend { font-weight: bold; padding: 0; margin-bottom: .25rem; grid-column: 1 / -1; }
```

- [ ] **Step 4: Run** — new tests green; then the whole `search/` suite (the typeahead/chips tests and `test_empty_form_does_not_ship_a_choice_per_country` must still pass) and full gates.

- [ ] **Step 5: Commit**

```bash
git add templates/search/people_search.html search/forms.py static/css/app.css search/tests/test_filter_rows.py
git commit -s -m "feat(search): filters in two named rows — games they worked on, about the person

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Banner copy and `Message` buttons

**Files:**
- Modify: `templates/search/people_search.html` (banner + card link), `templates/accounts/profile.html`, `accounts/tests/test_profile_preview.py`
- Test: `accounts/tests/test_message_button.py` (new)

- [ ] **Step 1: Failing tests**

```python
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_visitor_sees_a_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    other = User.objects.create_user(email="o@example.com", password="x", display_name="Other")
    client.force_login(other)
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert f'<a role="button" href="{reverse("contact:contact", args=[target.slug])}">Message</a>' in main
    assert ">Contact<" not in main


def test_banner_has_no_trailing_clause(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    assert "Worked on a game?" in body
    assert "no account needed to start" not in body
```

Edit `accounts/tests/test_profile_preview.py`: `assert "Contact" in body` → `assert "Message" in body`; `assert b"Contact" not in body` → `assert b"Message" not in body`; the docstring's "real Contact link" → "real Message button". Run → FAIL.

- [ ] **Step 2: Templates**

`people_search.html` banner: `<p>{% translate "Worked on a game?" %} <a href="{% url 'contributions:declare' %}">{% translate "Add your credit" %}</a></p>` (drop the dash clause and its translate call; update the comment above it).
`people_search.html` card: `— <a href="{% url 'contact:contact' r.user.slug %}">{% translate "Contact" %}</a>` → `<a role="button" href="{% url 'contact:contact' r.user.slug %}">{% translate "Message" %}</a>`.
`profile.html`: preview placeholder `{% translate "Contact" %}` → `{% translate "Message" %}`; visitor link → `<p><a role="button" href="{% url 'contact:contact' profile_user.slug %}">{% translate "Message" %}</a></p>`.

- [ ] **Step 3: Run** — new + preview tests green; full gates; also `uv run pytest search/ accounts/ -q`.

- [ ] **Step 4: Commit**

```bash
git add templates/search/people_search.html templates/accounts/profile.html accounts/tests/test_profile_preview.py accounts/tests/test_message_button.py
git commit -s -m "feat(ui): Message buttons replace Contact links; banner trimmed

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Docs, gates, browser check

- [ ] `docs/01-DESIGN.md` §3.6: the two filter rows and their names; the `Message` button; the banner copy. `docs/03-TECH-STACK.md`: JetBrains Mono Bold (OFL) vendored under `cards/fonts/` for the card wordmark. `docs/superpowers/specs/2026-08-21-open-graph-cards-design.md` §2 table: wordmark row → "ROLL / CALL, two lines, JetBrains Mono Bold 36 px". `ROADMAP.md`: Phase 11 block (Search chrome ✅ with the four items).
- [ ] Gates incl. `docker build -q .`.
- [ ] Controller: 375px + laptop width — wordmark stacked, two rows visible without scrolling at 1280×800 logged-out, Message buttons on a profile and a card, banner text, a card PNG with the stacked mark.
- [ ] Commit `docs: record the search chrome (stacked wordmark, filter rows, Message button)`.
