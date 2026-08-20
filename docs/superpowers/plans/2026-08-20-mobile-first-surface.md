# Mobile-first surface (Pico, home reorder, feed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the validated 2026-08-20 surface spec: Pico CSS v2 classless as the style layer, a filters-first home page with a latest-credits feed, `MM/YYYY` credit dates, an About page, and the light English copy pass.

**Architecture:** Pure presentation + one read-only query. The only view change is `PeopleSearchView.get_context_data` growing a `latest_credits` queryset; everything else is templates, two static files, one `TemplateView` route, and label edits. No model change, no migration, no new dependency.

**Tech Stack:** Django 6 templates, Pico CSS v2 (classless build, vendored), htmx (already vendored), pytest-django.

**Spec:** `docs/superpowers/specs/2026-08-20-mobile-first-surface-design.md` — read it first; it is binding.

## Global Constraints

- Every user-facing string goes through i18n (`{% translate %}` / `{% blocktranslate %}` / `gettext_lazy`) — including new copy in this plan.
- `static/css/app.css` carries **functional layout only**: positioning, flex/grid, widths, spacing. No colors/fonts/radii/shadows; where a color is unavoidable use Pico variables (`var(--pico-...)`), never literals.
- All commits DCO signed-off: `git commit -s`, ending the message with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Gates that must pass before every commit: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`.
- Comments state constraints/reasons, never narration. Match surrounding style.
- Test scoping idiom used throughout: nav assertions scope to `body[: body.index("</header>")]`; page-content assertions scope to `body[body.index("<main") : body.index("</main>")]` — `base.html` has a second `<nav>` in the footer and the nav CTA shares strings with page content, so whole-body asserts go quiet or lie.
- The dev DB: `docker compose up db -d` must be running for pytest.

---

### Task 1: Vendor Pico CSS v2 classless + `app.css` + `base.html` wiring

**Files:**
- Create: `static/vendor/pico.classless.min.css` (downloaded)
- Create: `static/css/app.css`
- Modify: `templates/base.html` (head: add links, delete inline `<style>`)
- Modify: `templates/search/people_search.html` (extra_head: delete the static `<style>` rules, keep canonical + `<noscript>`)
- Modify: `templates/contributions/declare_game.html` (drop `size=35` — Pico sizes inputs)
- Test: `config/tests/test_base_template.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces: the two stylesheet links every later task renders under; `app.css` class contract unchanged from today's templates (`.nav-search`, `.autocomplete`, `.results`, `.nav-suggest`, `.autocomplete-option`, `.igdb-option`, `.igdb-trigger`, `.suggest-item`, `.muted`, `.preview-bar`, `.notice`, `.filter`, `.chips`, `.chip`, `.chip-remove`, `.autocomplete-empty`, `.noscript-note`, `.pagination`).

- [ ] **Step 1: Write the failing test**

Create `config/tests/test_base_template.py`:

```python
"""base.html wiring — the style layer is two stylesheets, Pico (vendored) and
the functional-only app.css (spec 2026-08-20-mobile-first-surface §1)."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_every_page_links_pico_then_app_css(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    pico = body.index("vendor/pico.classless.min.css")
    app = body.index("css/app.css")
    # Order matters: app.css must be able to override Pico.
    assert pico < app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest config/tests/test_base_template.py -v`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Step 3: Download Pico and create app.css**

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css -o static/vendor/pico.classless.min.css
head -c 200 static/vendor/pico.classless.min.css
```

Expected: the file starts with a `/*! ... Pico CSS ... v2.x.y ... */` banner. If the banner carries no version, prepend one line: `/* Pico CSS v<version from https://cdn.jsdelivr.net/npm/@picocss/pico@2/package.json> (classless) — MIT — picocss.com */`.

Create `static/css/app.css` — the inline styles of `base.html` and `people_search.html`, minus what Pico now covers (`article` card framing replaces `.person-card`'s) and with system-color hacks swapped for Pico variables:

```css
/* Functional layout only — aesthetics come from Pico (vendored). The review
   bar for edits here: positioning, flex/grid, widths, spacing. No colors,
   fonts, radii or shadows; unavoidable colors use Pico variables. */

/* Nav search + autocomplete dropdowns (base.html, contribution forms). */
.nav-search, .autocomplete { position: relative; display: inline-block; }
.nav-search { flex: 1; min-width: 0; }
.nav-search input { width: 100%; min-width: 0; margin-bottom: 0; }
.results, .nav-suggest {
  position: absolute; z-index: 100; left: 0; top: 100%;
  min-width: 20rem; max-width: 90vw; max-height: 20rem; overflow-y: auto;
  background: var(--pico-background-color); color: inherit;
  border: 1px solid var(--pico-muted-border-color);
}
.results:empty, .nav-suggest:empty { display: none; }
.autocomplete-option, .igdb-option, .igdb-trigger, .suggest-item {
  display: block; width: 100%; text-align: left; box-sizing: border-box;
  padding: .35rem .6rem; background: none; border: none; cursor: pointer;
  color: inherit; text-decoration: none; font: inherit;
}
.autocomplete-option:hover, .igdb-option:hover,
.igdb-trigger:hover, .suggest-item:hover {
  background: var(--pico-primary-background); color: var(--pico-primary-inverse);
}
.igdb-trigger { border-top: 1px solid var(--pico-muted-border-color); font-style: italic; }
.suggest-item small { opacity: .6; }

/* Used by profile.html, _github_block.html and the search cards — global,
   so it isn't only styled on whichever page happens to define it. */
.muted { opacity: .7; }
.preview-bar, .notice { border: 1px solid var(--pico-muted-border-color); padding: .4rem .6rem; }

/* People search (home): filter blocks and typeahead chips. */
.filter { margin: .6rem 0; }
.filter > label { font-weight: bold; display: block; }
.filter .helptext { margin: 0 0 .3rem; }
.chips { list-style: none; margin: 0 0 .3rem; padding: 0; display: flex; flex-wrap: wrap; gap: .3rem; }
.chips:empty { display: none; }
.chip {
  display: inline-flex; align-items: center; gap: .3rem;
  border: 1px solid var(--pico-muted-border-color); padding: .1rem .3rem .1rem .6rem;
}
.chip-remove {
  background: none; border: none; cursor: pointer; color: inherit;
  font: inherit; line-height: 1; padding: .1rem .3rem;
}
.chip-remove:hover {
  background: var(--pico-primary-background); color: var(--pico-primary-inverse);
}
.autocomplete-empty { padding: .35rem .6rem; margin: 0; }
/* Shown only when people_search.html's <noscript> block un-hides it. */
.noscript-note { display: none; }
.pagination { margin: 1rem 0; }
```

- [ ] **Step 4: Wire base.html, strip the moved styles**

In `templates/base.html`, replace the whole inline `<style>…</style>` block (lines 8–30) with:

```html
  <link rel="stylesheet" href="{% static 'vendor/pico.classless.min.css' %}">
  <link rel="stylesheet" href="{% static 'css/app.css' %}">
```

In `templates/search/people_search.html`'s `{% block extra_head %}`: delete the `<style>…</style>` block (the rules now in app.css). Keep `<link rel="canonical" …>`, the `{% comment %}` about no-JS, and the `<noscript><style>…</style></noscript>` block exactly as they are.

Also delete the `.person-card h3/ul` margin rules with the block (Pico's `article` spacing replaces the card frame) and remove `class="person-card"` from the `<article>` in the results loop — a bare `<article>` is Pico's card.

In `templates/contributions/declare_game.html`, drop ` size=35` from the game search input (spec §1 sweep — Pico sizes inputs full-width).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest config/tests/test_base_template.py -v`
Expected: PASS

- [ ] **Step 6: Full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: all pass — this task must not break any template-string test.

- [ ] **Step 7: Browser sanity check (dev server)**

Start the dev server (`.claude/launch.json` → `rollcall-dev`, port 8010) and load `/` at mobile width (375px), in light **and** dark mode. Verify: sans-serif type, readable headings in dark mode (the defect this fixes), autocomplete dropdown still overlays (type in the nav search box).

- [ ] **Step 8: Commit**

```bash
git add static/vendor/pico.classless.min.css static/css/app.css templates/base.html templates/search/people_search.html templates/contributions/declare_game.html config/tests/test_base_template.py
git commit -s -m "feat(ui): Pico CSS v2 classless as the style layer, app.css for functional layout

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Nav bar — ROLLCALL wordmark, `Add your credit` CTA

**Files:**
- Modify: `templates/base.html` (the `<header><nav>` block)
- Test: `config/tests/test_base_template.py` (append)

**Interfaces:**
- Consumes: Task 1's stylesheets (`.nav-search` now flexes).
- Produces: the string `Add your credit` in the header for every visitor — later page-level tests must scope to `<main>` (see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Append to `config/tests/test_base_template.py`:

```python
def _header(body: str) -> str:
    return body[: body.index("</header>")]


def test_anonymous_nav_leads_with_the_declare_cta(client: Client) -> None:
    """The most visible nav control is the worker CTA (spec §1): role=button
    renders as Pico's one solid button on the bar. Sign up leaves the nav —
    the declare funnel IS the signup path; the login page keeps a direct link."""
    header = _header(client.get(reverse("home")).content.decode())
    assert "ROLLCALL" in header
    assert 'role="button"' in header
    assert reverse("contributions:declare") in header
    assert "Add your credit" in header
    assert "Sign up" not in header


def test_member_nav_cta_goes_to_the_credit_form(client: Client) -> None:
    user = User.objects.create_user(email="nav@example.com", password="x", display_name="N")
    client.force_login(user)
    header = _header(client.get(reverse("home")).content.decode())
    assert reverse("contributions:create") in header
    assert "Add your credit" in header
```

Add the import at the top of the file: `from accounts.models import User`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest config/tests/test_base_template.py -v`
Expected: the two new tests FAIL (`ROLLCALL`/`role="button"` not found).

- [ ] **Step 3: Restructure the nav**

In `templates/base.html`, replace the `<nav>…</nav>` inside `<header>` with Pico's list idiom:

```html
    <nav>
      <ul>
        <li><a href="{% url 'home' %}"><strong>ROLLCALL</strong></a></li>
      </ul>
      <ul class="nav-search">
        <li>
          <form action="{% url 'search:search' %}" method="get" role="search">
            <input type="search" name="q" autocomplete="off"
                   placeholder="{% translate 'Search games, companies and people' %}"
                   hx-get="{% url 'search:suggest' %}" hx-trigger="keyup changed delay:250ms"
                   hx-target="#nav-suggest">
          </form>
          <div id="nav-suggest" class="nav-suggest"></div>
        </li>
      </ul>
      <ul>
        {% if user.is_authenticated %}
          <li><a role="button" href="{% url 'contributions:create' %}">{% translate "Add your credit" %}</a></li>
          <li><a href="{% url 'accounts:my_profile' %}">{% translate "My profile" %}</a></li>
          <li><a href="{% url 'accounts:account' %}">{% translate "Account" %}</a></li>
          <li>
            <form action="{% url 'accounts:logout' %}" method="post">
              {% csrf_token %}
              <button type="submit" class="outline secondary">{% translate "Log out" %}</button>
            </form>
          </li>
        {% else %}
          <li><a role="button" href="{% url 'contributions:declare' %}">{% translate "Add your credit" %}</a></li>
          <li><a href="{% url 'accounts:login' %}">{% translate "Log in" %}</a></li>
        {% endif %}
      </ul>
    </nav>
```

Notes for the implementer:
- The `size=35` attribute and its comment are gone — `.nav-search` (Task 1) sizes the input.
- `.nav-search` moved from a `<span>` onto the middle `<ul>`; the `position: relative` anchor for `#nav-suggest` must remain on an ancestor of both the input and the dropdown. If the dropdown misplaces, put `class="nav-search"` on the `<li>` instead and give the `<ul>` `flex: 1; min-width: 0;` via a new `.nav-grow` rule in app.css.
- `style="display:inline"` attributes are gone; app.css/Pico handle layout.
- On mobile Pico stacks nav `<ul>`s; add `nav { flex-wrap: wrap; }` to app.css only if the 375px check shows overflow.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest config/tests/test_base_template.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: all pass. If a nav-string test elsewhere breaks (e.g. `search/tests/test_nav_search_box.py` pinned `size=35`), update that test to assert the input exists with its placeholder, not its hardcoded width.

- [ ] **Step 6: Browser check**

375px, `/`: the CTA renders as the single solid button; the logout button (log in first, e.g. fixtures user — or check visually with the two auth states via an incognito pair) renders outlined, not competing. If `class="outline secondary"` has no effect in the classless build, drop the classes and de-emphasize via app.css `nav form button { background: none; border: none; color: var(--pico-primary); }` — functional exception, note it in the file comment.

- [ ] **Step 7: Commit**

```bash
git add templates/base.html static/css/app.css config/tests/test_base_template.py
git commit -s -m "feat(nav): ROLLCALL wordmark, Add-your-credit primary CTA, flexible search box

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Home reorder — filters first, one-line worker banner, `#results` anchor

**Files:**
- Modify: `templates/search/people_search.html`
- Modify: `games/tests/test_home.py` (three tests rewritten)
- Modify: `contributions/tests/test_declare_game.py` (two tests rewritten)

**Interfaces:**
- Consumes: nav CTA from Task 2 (the banner is the *second* declare entry point).
- Produces: `<section id="results">` for search results; the `{% else %}` branch where Task 4's feed will render; H1 `Find people by what they've worked on` for every visitor.

- [ ] **Step 1: Rewrite the affected tests (they pin the old order)**

In `games/tests/test_home.py`, replace `PITCH` and the three tests:

```python
PITCH = b"Worked on a game?"


def test_home_is_public_and_renders_the_search_form(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    # Filters-first (spec 2026-08-20): one H1 for everyone, the tool under it.
    assert b"Find people by what they" in response.content
    assert b"discipline" in response.content.lower()


def test_home_banner_invites_an_anonymous_visitor_to_declare(client: Client) -> None:
    """Success metric #1 is workers declaring their work. The funnel moved to
    /declare/; the home keeps a one-line banner. Scoped to <main> — the nav
    CTA satisfies a looser assertion."""
    body = client.get(reverse("home")).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert "Worked on a game?" in main
    assert reverse("contributions:declare") in main


def test_a_member_gets_the_tool_without_the_pitch(client: Client) -> None:
    """They already have an account — the pitch is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert PITCH not in response.content
    assert b"discipline" in response.content.lower()  # the tool is still there
```

Delete the now-unused `import re` if nothing else in the file uses it.

In `contributions/tests/test_declare_game.py`, replace the two home-facing tests:

```python
def test_home_routes_anonymous_visitors_to_declare(client: Client) -> None:
    """The question and its game form live at /declare/ now; the home page
    links there from a one-line banner (spec 2026-08-20 supersedes the
    2026-08-11 funnel-first order)."""
    body = client.get(reverse("home")).content.decode()
    assert "Which game did you work on?" not in body
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contributions:declare") in main


def test_home_does_not_pitch_a_member(client: Client) -> None:
    """They already have an account — the invitation is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    body = client.get(reverse("home")).content
    assert b"Worked on a game?" not in body
    assert b"Find people by what they" in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest games/tests/test_home.py contributions/tests/test_declare_game.py -v`
Expected: the rewritten tests FAIL against the current template (old order still renders).

- [ ] **Step 3: Reorder the template**

In `templates/search/people_search.html`, replace everything in `{% block content %}` from the top through the `<h2>{% translate "Looking for someone?" %}</h2>` line (the auth conditional, funnel H1/form/pitch) with:

```html
  <h1>{% translate "Find people by what they've worked on" %}</h1>
  {% if not user.is_authenticated %}
    {% comment %}
      One line, not the funnel: /declare/ carries the question and the game
      form. Fragmented across three translate calls to keep the links —
      acceptable while LANGUAGES = [en] only.
    {% endcomment %}
    <p>{% translate "Worked on a game?" %} <a href="{% url 'contributions:declare' %}">{% translate "Add your credit" %}</a> — {% translate "no account needed to start." %}</p>
  {% endif %}
```

Then two surgical edits below:
- The filter form tag becomes: `<form method="get" action="{% url 'home' %}#results">` — a submit lands the viewport on the results without JavaScript (mobile defect #4).
- The results section tag becomes: `<section id="results">`.

The comment block explaining the anonymous H1 choice (crawlers index the question) is now false — delete it; the SEO reversal is recorded in the spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest games/tests/test_home.py contributions/tests/test_declare_game.py -v`
Expected: PASS.

- [ ] **Step 5: Full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: all pass. Any other test pinning the old home order gets the same treatment as Step 1 (assert the new order, scope to `<main>`).

- [ ] **Step 6: Commit**

```bash
git add templates/search/people_search.html games/tests/test_home.py contributions/tests/test_declare_game.py
git commit -s -m "feat(home): filters first for everyone; worker pitch becomes a one-line banner

Supersedes the anonymous funnel-first order of the 2026-08-11 spec (see
docs/superpowers/specs/2026-08-20-mobile-first-surface-design.md §2).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Latest-credits feed

**Files:**
- Modify: `search/views.py` (`PeopleSearchView.get_context_data`)
- Modify: `templates/search/people_search.html` (feed section)
- Test: `search/tests/test_latest_credits_feed.py` (new)

**Interfaces:**
- Consumes: Task 3's `{% if searched %}` / results section structure.
- Produces: context key `latest_credits: QuerySet[Contribution]`, present only on the bare front door (no query string).

- [ ] **Step 1: Write the failing tests**

Create `search/tests/test_latest_credits_feed.py`:

```python
"""The home feed — social proof on the bare front door. The guards ARE the
feature: only active credits of public profiles, nothing else about the user
(spec 2026-08-20-mobile-first-surface §3)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _credit(
    email: str,
    name: str,
    *,
    status: str = Contribution.Status.ACTIVE,
    profile_public: bool = True,
    title: str = "Card Game",
) -> Contribution:
    game, _ = Game.objects.get_or_create(title=title, defaults={"source": Game.Source.MANUAL})
    user = User.objects.create_user(
        email=email, password="x", display_name=name, profile_public=profile_public
    )
    return Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2024, 8, 1),
        end_date=date(2025, 3, 1),
        status=status,
    )


def test_feed_shows_active_public_credits_with_mm_yyyy_dates(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    body = client.get(reverse("home")).content.decode()
    assert "Latest credits" in body
    assert "Ada Artist" in body
    assert "added a credit on" in body
    assert "Card Game" in body
    assert "Level Designer" in body
    assert "08/2024" in body and "03/2025" in body


def test_feed_never_shows_pending_credits(client: Client) -> None:
    _credit("p@example.com", "Pending Person", status=Contribution.Status.PENDING)
    body = client.get(reverse("home")).content.decode()
    assert "Pending Person" not in body


def test_feed_never_shows_private_profiles(client: Client) -> None:
    _credit("h@example.com", "Hidden Person", profile_public=False)
    body = client.get(reverse("home")).content.decode()
    assert "Hidden Person" not in body


def test_feed_is_absent_once_a_search_ran(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    design = Discipline.objects.get(name="Design")
    body = client.get(reverse("home"), {"discipline": str(design.pk)}).content.decode()
    assert "Latest credits" not in body


def test_feed_is_newest_first_and_capped_at_ten(client: Client) -> None:
    for i in range(11):
        _credit(f"u{i}@example.com", f"Person {i:02d}", title=f"Game {i:02d}")
    body = client.get(reverse("home")).content.decode()
    assert "Person 10" in body  # newest
    assert "Person 00" not in body  # 11th-newest fell off
    assert body.index("Person 10") < body.index("Person 01")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest search/tests/test_latest_credits_feed.py -v`
Expected: FAIL — `Latest credits` not in the page.

- [ ] **Step 3: View + template**

In `search/views.py`, add to the imports: `from contributions.models import Contribution`.
In `PeopleSearchView.get_context_data`, after the existing `if self.request.GET and form.is_valid():` block, add:

```python
        if not self.request.GET:
            # The bare front door only: a search (valid or not) replaces the
            # feed. Guards are the feature — only publishable rows render
            # (docs/00 #7), and only for people who are findable at all.
            context["latest_credits"] = (
                Contribution.objects.filter(
                    status=Contribution.Status.ACTIVE, user__profile_public=True
                )
                .select_related("user", "game")
                .order_by("-created_at")[:10]
            )
        return context
```

(The method already ends with `return context`; keep exactly one.)

In `templates/search/people_search.html`, right after the `{% if searched %} … {% endif %}` results block, add:

```html
  {% if latest_credits %}
    <section>
      <h2>{% translate "Latest credits" %}</h2>
      {% comment %}
        Sentence fragmented around the two links — acceptable while
        LANGUAGES = [en] only. No timestamps beyond the credit's own dates:
        "2 hours ago" would advertise activity patterns (spec §3).
      {% endcomment %}
      <ul>
        {% for c in latest_credits %}
          <li>
            <a href="{% url 'accounts:profile' c.user.slug %}">{{ c.user.display_name }}</a>
            {% translate "added a credit on" %}
            <a href="{% url 'games:game' c.game.slug %}">{{ c.game.title }}</a>:
            {{ c.job_title }}
            ({{ c.start_date|date:"m/Y" }} – {% if c.end_date %}{{ c.end_date|date:"m/Y" }}{% else %}{% translate "present" %}{% endif %})
          </li>
        {% endfor %}
      </ul>
    </section>
  {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest search/tests/test_latest_credits_feed.py -v`
Expected: PASS.

- [ ] **Step 5: Full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add search/views.py templates/search/people_search.html search/tests/test_latest_credits_feed.py
git commit -s -m "feat(home): latest-credits feed on the bare front door

Only active credits of public profiles; replaced by results once a search
runs. No caching — one indexed query (spec 2026-08-20 §3).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `MM/YYYY` credit dates everywhere credits render

**Files:**
- Modify: `templates/accounts/profile.html` (lines with `date:"M Y"`)
- Modify: `templates/games/game_detail.html` (lines with `date:"M Y"`)
- Modify: `templates/search/people_search.html` (result-card credit line, `date:"Y"`)
- Test: `accounts/tests/test_profile_credits.py` (append one test)
- Test: `games/tests/test_credit_date_display.py` (new)
- Test: `search/tests/test_latest_credits_feed.py` (append one test)

**Interfaces:**
- Consumes: nothing new. The feed (Task 4) already renders `m/Y`.
- Produces: the sitewide display rule — credit ranges are `m/Y`, career/release years stay `Y`.

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests/test_profile_credits.py` (reuse the file's existing user/credit fixtures if it has helpers; otherwise this is self-contained — mirror the imports it already has, adding any of these that are missing: `from datetime import date`, `Contribution`, `Discipline`, `Game`):

```python
def test_profile_credit_dates_render_mm_yyyy(client: Client) -> None:
    """Display rule (spec 2026-08-20 §4): credit ranges are numeric m/Y —
    entry stays the native month picker; only rendering changes."""
    user = User.objects.create_user(
        email="dates@example.com", password="x", display_name="Date Person"
    )
    Contribution.objects.create(
        user=user,
        game=Game.objects.create(title="Date Game", source=Game.Source.MANUAL),
        discipline=Discipline.objects.get(name="Design"),
        job_title="Animator",
        start_date=date(2024, 8, 1),
        end_date=date(2025, 3, 1),
    )
    body = client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "08/2024" in body and "03/2025" in body
    assert "Aug 2024" not in body
```

Create `games/tests/test_credit_date_display.py`:

```python
"""Game-page team list — same m/Y display rule as profiles (spec 2026-08-20 §4)."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def test_game_page_credit_dates_render_mm_yyyy(client: Client) -> None:
    game = Game.objects.create(title="Date Game", source=Game.Source.MANUAL)
    user = User.objects.create_user(
        email="dates@example.com", password="x", display_name="Date Person"
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Animator",
        start_date=date(2024, 8, 1),
        end_date=date(2025, 3, 1),
    )
    body = client.get(reverse("games:game", args=[game.slug])).content.decode()
    assert "08/2024" in body and "03/2025" in body
    assert "Aug 2024" not in body
```

Append to `search/tests/test_latest_credits_feed.py`:

```python
def test_result_card_credit_dates_render_mm_yyyy(client: Client) -> None:
    _credit("a@example.com", "Ada Artist")
    design = Discipline.objects.get(name="Design")
    body = client.get(reverse("home"), {"discipline": str(design.pk)}).content.decode()
    assert "08/2024" in body and "03/2025" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest accounts/tests/test_profile_credits.py games/tests/test_credit_date_display.py search/tests/test_latest_credits_feed.py -v`
Expected: the three new tests FAIL (`Aug 2024` renders today; cards render years only).

- [ ] **Step 3: Change the three templates**

Every credit-range `date:"M Y"` becomes `date:"m/Y"`; the result card's per-credit `date:"Y"` pair becomes `date:"m/Y"`:

`templates/accounts/profile.html` — the `.dates` span:

```html
        <span class="dates">
          {{ c.start_date|date:"m/Y" }} –
          {% if c.end_date %}{{ c.end_date|date:"m/Y" }}{% else %}{% translate "present" %}{% endif %}
        </span>
```

`templates/games/game_detail.html` — same substitution on its `.dates` span (lines 42–43).

`templates/search/people_search.html` — the per-credit line inside the result card:

```html
                <span class="dates">{{ c.start_date|date:"m/Y" }}–{% if c.end_date %}{{ c.end_date|date:"m/Y" }}{% else %}{% translate "present" %}{% endif %}</span>
```

Leave untouched: the career summary `{{ r.first_year }}–{{ r.last_year }}` (years), `game.release_date|date:"Y"` in `game_detail.html`/`declare_game.html`, and `_github_block.html`'s "On GitHub since Y" — they are years, not credit ranges.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest accounts/tests/test_profile_credits.py games/tests/test_credit_date_display.py search/tests/test_latest_credits_feed.py -v`
Expected: PASS.

- [ ] **Step 5: Full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`
Expected: all pass. If an existing test pinned `Aug`-style dates, update it to `m/Y`.

- [ ] **Step 6: Commit**

```bash
git add templates/accounts/profile.html templates/games/game_detail.html templates/search/people_search.html accounts/tests/test_profile_credits.py games/tests/test_credit_date_display.py search/tests/test_latest_credits_feed.py
git commit -s -m "feat(dates): credit ranges display as MM/YYYY sitewide

Entry keeps the native month picker (it localizes per visitor). Career and
release years stay years (spec 2026-08-20 §4).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: About page

**Files:**
- Create: `templates/about.html`
- Modify: `config/urls.py` (one path)
- Modify: `templates/base.html` (footer link)
- Test: `config/tests/test_about_page.py` (new)

**Interfaces:**
- Consumes: base template/footer from Tasks 1–2.
- Produces: URL name `about`.

- [ ] **Step 1: Write the failing tests**

Create `config/tests/test_about_page.py`:

```python
"""The About page — trust surface for a site asking people to document their
careers, and the open-source invitation (spec 2026-08-20 §5)."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_about_renders_the_four_sections(client: Client) -> None:
    body = client.get(reverse("about")).content.decode()
    assert "What this is" in body
    assert "Where the data comes from" in body
    assert "Open source" in body
    assert "github.com/Micro-SAS/rollcall" in body
    assert "AGPL" in body


def test_footer_links_to_about(client: Client) -> None:
    body = client.get(reverse("home")).content.decode()
    footer = body[body.index("<footer") :]
    assert reverse("about") in footer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest config/tests/test_about_page.py -v`
Expected: FAIL — `NoReverseMatch: 'about'`.

- [ ] **Step 3: Route, template, footer link**

`config/urls.py` — after the `privacy` path:

```python
    path("about/", TemplateView.as_view(template_name="about.html"), name="about"),
```

Create `templates/about.html`:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "About" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "About Rollcall" %}</h1>

  <h2>{% translate "What this is" %}</h2>
  <p>{% blocktranslate %}Rollcall is a public credits register for the game industry. People who make games declare what they shipped; anyone can find them by what they actually worked on — discipline, engine, genre, country.{% endblocktranslate %}</p>
  <p>{% blocktranslate %}The industry has been through unprecedented layoff waves since 2024. A résumé says what you claim; a credits register shows what you shipped. Rollcall exists so that record works for the people who built it.{% endblocktranslate %}</p>

  <h2>{% translate "Where the data comes from" %}</h2>
  <p>{% blocktranslate %}The games catalog is seeded from IGDB and Steam-derived data. Credits are declared by the people themselves — never scraped, never imported on someone's behalf.{% endblocktranslate %}</p>

  <h2>{% translate "Open source" %}</h2>
  <p>{% blocktranslate %}Rollcall is open source under AGPL v3. The code is public and contributions are welcome; user data is not part of the code and stays private.{% endblocktranslate %}</p>
  <p><a href="https://github.com/Micro-SAS/rollcall">{% translate "Source code on GitHub" %}</a></p>

  <h2>{% translate "Contact and safety" %}</h2>
  <p>{% blocktranslate %}Personal email addresses are never shown anywhere on Rollcall. Contacting someone goes through a relay, and only when they have allowed it. Signed-in members can report any profile or page from the footer.{% endblocktranslate %}</p>
{% endblock %}
```

`templates/base.html` — in the footer `<nav>`, before the Terms link:

```html
        <a href="{% url 'about' %}">{% translate "About" %}</a>
```

(No static-pages sitemap exists — `config/sitemaps.py` lists users/games/companies only; not adding one for a single static page.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest config/tests/test_about_page.py -v`
Expected: PASS.

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add templates/about.html config/urls.py templates/base.html config/tests/test_about_page.py
git commit -s -m "feat(about): About page — mission, data provenance, AGPL, safety

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: English copy pass

**Files:**
- Modify: `search/forms.py` (`year_from` label)
- Modify: `templates/accounts/profile.html` (owner "Add a credit" link)
- Modify: `templates/contributions/contribution_form.html` (title + H1)
- Modify: `accounts/tests/test_profile_preview.py` (scoped assertion)

**Interfaces:**
- Consumes: the nav CTA string from Task 2 (`Add your credit` is now in every page's header — the reason for the scoped assertion below).
- Produces: `Add your credit` as the one canonical CTA string; `Worked on a game since (year)` as the filter label.

- [ ] **Step 1: Update the preview test first (it breaks by design)**

`accounts/tests/test_profile_preview.py` line 39 asserts `b"Add a credit" not in body` to prove owner controls hide in preview. After this task the string is `Add your credit`, which the *nav* now always carries for a logged-in user — so scope to `<main>`:

```python
    main = body.decode()
    main = main[main.index("<main") : main.index("</main>")]
    assert "Add your credit" not in main
```

(Adapt to the variable names around line 39; the intent — owner's add-credit control absent in preview — must survive, not the literal string.)

- [ ] **Step 2: Run it — expected PASS (protective edit, not red/green)**

Run: `uv run pytest accounts/tests/test_profile_preview.py -v`
Expected: PASS, both before and after Step 3 — this edit carries the test's *intent* (owner controls hidden in preview) across the string rename. The rename itself is pinned by Step 4's grep check, not by this test.

- [ ] **Step 3: Apply the copy changes**

`search/forms.py` — the `year_from` field:

```python
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Worked on a game since (year)")
    )
```

`templates/accounts/profile.html` line 59:

```html
      <p><a href="{% url 'contributions:create' %}">{% translate "Add your credit" %}</a></p>
```

`templates/contributions/contribution_form.html` title and H1 (`Edit credit` branch unchanged):

```html
{% block title %}{% translate "Add your credit" %} · Rollcall{% endblock %}
...
  <h1>{% if form.instance.pk %}{% translate "Edit credit" %}{% else %}{% translate "Add your credit" %}{% endif %}</h1>
```

- [ ] **Step 4: Run tests + verify the rename is complete**

Run: `uv run pytest accounts/tests/ search/tests/ contributions/tests/ -q`
Expected: PASS — including the reworked preview test.

Run: `grep -rn "Add a credit" templates/ --include="*.html"`
Expected: **no matches** — the old string is fully retired (the old home pitch `Add a credit to your name` left in Task 3).

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`

```bash
git add search/forms.py templates/accounts/profile.html templates/contributions/contribution_form.html accounts/tests/test_profile_preview.py
git commit -s -m "fix(copy): one canonical CTA string, clearer year-filter label

'Add your credit' everywhere a worker is invited to declare;
'Worked on a game since (year)' says what the filter filters.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Docs, final gates, mobile verification

**Files:**
- Modify: `docs/01-DESIGN.md`
- Modify: `docs/03-TECH-STACK.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: everything above, landed.
- Produces: docs that match behavior (a docs/behavior mismatch is a bug in this repo).

- [ ] **Step 1: docs/01-DESIGN.md**

Locate the section describing the home page / people search (added by the 2026-08-11 spec; search for "home"). Update it to state, in its own prose style:
- The home page leads with the search for **every** visitor; the anonymous worker pitch is a one-line banner linking to `/declare/`, and the nav's primary CTA is `Add your credit`.
- The bare front door shows the ten latest active credits of public profiles ("Latest credits"); any search replaces the feed with results.
- Credit date ranges display as `MM/YYYY` sitewide; entry is the native month picker.
- An About page exists at `/about/` (mission, data provenance, AGPL, contact/safety), linked from the footer.
- Add a pointer: "Superseded order: spec 2026-08-11 put the funnel first for anonymous visitors; spec 2026-08-20 reversed it."

- [ ] **Step 2: docs/03-TECH-STACK.md**

In the Templates/front row, replace `CSS: keep it simple (vanilla or a light utility framework — implementer's choice, not architectural).` with:

```
CSS: Pico CSS v2 classless, vendored (chosen 2026-08-20) + one functional-only app.css; still not architectural — swapping it stays cheap.
```

- [ ] **Step 3: ROADMAP.md**

After the Phase 7 section, add:

```markdown
## Phase 8 — Mobile-first surface ✅ (spec 2026-08-20)

Goal: a styled, mobile-first site without custom design — Pico CSS v2 classless.

- [x] Pico CSS v2 classless vendored; `app.css` = functional layout only (dark mode fixed)
- [x] Nav: ROLLCALL wordmark, `Add your credit` primary CTA (declare funnel for anonymous)
- [x] Home: filters first for everyone; worker pitch = one-line banner; `#results` anchor
- [x] Latest-credits feed (active credits of public profiles only)
- [x] Credit dates display as MM/YYYY sitewide
- [x] About page (`/about/`) — mission, data provenance, AGPL, safety
- [x] English copy pass (canonical CTA, year-filter label)
```

- [ ] **Step 4: Final gates, all of them**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check && docker build -q .`
Expected: all pass, image builds (the vendored CSS ships via collectstatic/whitenoise like htmx does — no Dockerfile change should be needed; if the build fails, that assumption broke, fix forward).

- [ ] **Step 5: Mobile verification (evidence, not vibes)**

Dev server at 375px width, light **and** dark:
1. `/` anonymous — CTA solid in nav, banner one line, filters full width, feed lists ≤10 entries, no horizontal scroll.
2. `/?discipline=<id>` — page lands scrolled at `#results`; result cards read as cards; dates `01/2020–06/2021`-style.
3. A profile page and a game page — dark-mode readable, dates `m/Y`.
4. `/about/` — renders, footer link present.

Fix anything broken (source edits, then re-run gates), and capture one light + one dark screenshot of `/` for the session log.

- [ ] **Step 6: Commit**

```bash
git add docs/01-DESIGN.md docs/03-TECH-STACK.md ROADMAP.md
git commit -s -m "docs: record the mobile-first surface (Pico, filters-first home, feed, MM/YYYY, About)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
