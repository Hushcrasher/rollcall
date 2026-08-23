# Profile-only Message Button & Layout Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The profile page becomes the single `Message` entry point (visible to anonymous visitors too, gone from search cards), the search filter rows and the header nav row get pixel-aligned, and the footer anchors to the viewport bottom on short pages.

**Architecture:** Template + CSS changes only — no view, URL, model or migration work. Behavior changes (button visibility) are pinned by pytest against rendered HTML; pure-CSS changes are verified in the browser (house rule: no test asserts computed styles). Spec: `docs/superpowers/specs/2026-08-24-profile-message-and-layout-polish-design.md`.

**Tech Stack:** Django 6 templates, Pico CSS (classless, vendored), pytest, uv. Dev server via the Claude Browser pane (`preview_start {name: "rollcall-dev"}`, port 8010; Postgres via `docker compose up -d db`).

## Global Constraints

- Every commit: `git commit -s` (DCO — CI rejects unsigned commits). Append your harness's Co-Authored-By trailer if its instructions require one.
- Direct commits on `main` (owner's standing preference).
- No new user-facing strings anywhere in this plan; every existing string already goes through i18n. Do not add any.
- Never expose the account email; the contact relay, `contact/` app and `search/services.py` are untouched by this plan.
- `static/css/app.css` is layout-only (its header comment): positioning, flex/grid, widths, spacing. No colors/fonts/radii.
- Comments state constraints and reasons ("why"), never narrate the next line.
- Browser verification uses the running dev server: `docker compose up -d db`, then `preview_start {name: "rollcall-dev"}`. After a CSS edit, reload the page (Django serves static files directly in DEBUG; no cache-busting needed, but force-reload if a stale style is suspected).
- Tasks 4–7 need the Browser pane for verification — if executing with subagents, keep those verifications in the orchestrating session.

---

### Task 1: Profile shows `Message` to every viewer but the owner

**Files:**
- Modify: `templates/accounts/profile.html` (the `contactable` block, ~line 69)
- Test: `accounts/tests/test_message_button.py`

**Interfaces:**
- Consumes: `ProfileView` context — `is_owner` (bool: owner viewing normally), `preview` (bool: owner's `?preview=member`), `profile_user.contactable`. All already exist (`accounts/views.py:177-180`); no view change.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test (plus two regression pins)**

Append to `accounts/tests/test_message_button.py` (imports and `pytestmark` already present in the file):

```python
def test_anonymous_visitor_sees_a_message_button(client: Client) -> None:
    """Spec 2026-08-24 §2: the profile is the recruiter's landing surface,
    so the contact action must be discoverable logged-out — the relay's own
    login + verified-email gates still guard the actual send."""
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    contact_url = reverse("contact:contact", args=[target.slug])
    assert f'<a role="button" href="{contact_url}">Message</a>' in main


def test_owner_sees_no_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    client.force_login(target)
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contact:contact", args=[target.slug]) not in main


def test_uncontactable_profile_shows_no_message_button(client: Client) -> None:
    target = User.objects.create_user(email="t@example.com", password="x", display_name="Target")
    target.contactable = False
    target.save(update_fields=["contactable"])
    body = client.get(reverse("accounts:profile", args=[target.slug])).content.decode()
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contact:contact", args=[target.slug]) not in main
    assert ">Message<" not in main
```

- [ ] **Step 2: Run the file — anonymous test fails, the two pins pass**

Run: `uv run pytest accounts/tests/test_message_button.py -v`
Expected: `test_anonymous_visitor_sees_a_message_button` FAILS (the button currently requires `is_visitor` = authenticated); the other three tests PASS.

- [ ] **Step 3: Widen the template condition**

In `templates/accounts/profile.html`, replace:

```django
    {% if profile_user.contactable %}
      {% if preview %}
        <p><span class="muted">{% translate "Message" %}</span></p>
      {% elif is_visitor %}
        <p><a role="button" href="{% url 'contact:contact' profile_user.slug %}">{% translate "Message" %}</a></p>
      {% endif %}
    {% endif %}
```

with:

```django
    {% if profile_user.contactable %}
      {% if preview %}
        <p><span class="muted">{% translate "Message" %}</span></p>
      {% elif not is_owner %}
        {# Anonymous included (spec 2026-08-24 §2): the relay's login + verified-email gates do the guarding, not the button's visibility. #}
        <p><a role="button" href="{% url 'contact:contact' profile_user.slug %}">{% translate "Message" %}</a></p>
      {% endif %}
    {% endif %}
```

Leave the `Report this profile` block below it exactly as is (`is_visitor` stays in use there).

- [ ] **Step 4: Run the suite slice**

Run: `uv run pytest accounts/tests/ -v`
Expected: ALL PASS — including `test_profile_preview.py` (the preview placeholder branch is untouched).

- [ ] **Step 5: Commit**

```bash
git add templates/accounts/profile.html accounts/tests/test_message_button.py
git commit -s -m "profile: show the Message button to everyone but the owner"
```

---

### Task 2: Search result cards lose the `Message` button

**Files:**
- Modify: `templates/search/people_search.html` (result card `<h3>`, ~line 132)
- Test: `search/tests/test_people_search_view.py`

**Interfaces:**
- Consumes: the `_candidate()` fixture already defined at the top of `search/tests/test_people_search_view.py` (creates a user + one credit in the pre-seeded "Design" discipline).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

Append to `search/tests/test_people_search_view.py` (imports already present):

```python
def test_result_card_has_no_message_button(client: Client) -> None:
    """Spec 2026-08-24 §2: the profile is the single contact entry point —
    a card links to the person, never to the relay."""
    user = _candidate()
    design = Discipline.objects.get(name="Design")
    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()
    assert reverse("accounts:profile", args=[user.slug]) in content
    assert reverse("contact:contact", args=[user.slug]) not in content
```

- [ ] **Step 2: Run it — must fail**

Run: `uv run pytest search/tests/test_people_search_view.py::test_result_card_has_no_message_button -v`
Expected: FAIL — the card currently renders the relay link for contactable users.

- [ ] **Step 3: Remove the card's button**

In `templates/search/people_search.html`, the card heading currently reads:

```django
          <h3>
            <a href="{% url 'accounts:profile' r.user.slug %}">{{ r.user.display_name }}</a>
            {% if r.user.open_to_work %}<span class="badge">{% translate "Open to work" %}</span>{% endif %}
            {% if r.user.contactable %}
              <a role="button" href="{% url 'contact:contact' r.user.slug %}">{% translate "Message" %}</a>
            {% endif %}
          </h3>
```

Delete the `{% if r.user.contactable %}…{% endif %}` block so it reads:

```django
          <h3>
            <a href="{% url 'accounts:profile' r.user.slug %}">{{ r.user.display_name }}</a>
            {% if r.user.open_to_work %}<span class="badge">{% translate "Open to work" %}</span>{% endif %}
          </h3>
```

- [ ] **Step 4: Run the full suite (other tests may reference the card markup)**

Run: `uv run pytest`
Expected: ALL PASS (~430+ tests). If anything else asserted the card button, fix that test to match the spec's matrix — the card never carries the relay URL.

- [ ] **Step 5: Commit**

```bash
git add templates/search/people_search.html search/tests/test_people_search_view.py
git commit -s -m "search: drop the Message button from result cards"
```

---

### Task 3: Amend the docs the behavior change makes false

**Files:**
- Modify: `docs/01-DESIGN.md` (§"Contact via relay form" bullet)
- Modify: `docs/superpowers/specs/2026-08-21-search-chrome-design.md` (§4)
- Modify: `ROADMAP.md` ("Post-roadmap additions")

**Interfaces:** none — documentation only. Must land in the same session/push as Tasks 1–2 (house rule: behavior change and docs travel together).

- [ ] **Step 1: docs/01-DESIGN.md**

In the §"Contact via relay form" bullet, replace the fragment:

```
, on the profile and on search result cards — the relay endpoint and its form's own title stay "Contact", since that page still is one)
```

with:

```
; on the **profile only** since 2026-08-24 — search result cards lost the button and the profile shows it to every viewer but the owner, anonymous included (spec `docs/superpowers/specs/2026-08-24-profile-message-and-layout-polish-design.md`) — the relay endpoint and its form's own title stay "Contact", since that page still is one)
```

- [ ] **Step 2: search-chrome spec amendment note**

In `docs/superpowers/specs/2026-08-21-search-chrome-design.md`, directly under the `## 4. `Message` button` heading, insert:

```markdown
> **Amended 2026-08-24** (spec
> `2026-08-24-profile-message-and-layout-polish-design.md`): the result-card
> button below is gone — the profile is the single contact entry point and
> shows the button to every viewer but the owner, anonymous included. The
> "Docs & tests" section's "`Message` on profile and cards" is likewise
> superseded.
```

- [ ] **Step 3: ROADMAP entry**

In `ROADMAP.md`, append to the end of "## Post-roadmap additions" (after the "Dismissable autocompletes" bullet, before "## Known follow-ups"):

```markdown
- [x] **Profile-only Message button + layout polish** (2026-08-24): search result cards lose their `Message` button — the profile is the single contact entry point and now shows the button to every viewer but the owner, anonymous included (the relay's login + verified-email gates are unchanged). Alignment fixes, measured in the browser: the typeahead chips list renders truly empty so `.chips:empty` finally hides it (the dead list's margin pushed the Engines/Genres/Countries inputs 5px under their row neighbours), the open-to-work checkbox sits on its row's input line, and the nav's search field / CTA / links share one 37px box. The footer anchors to the viewport bottom on short pages via a flex-column `body` (`min-height: 100dvh`), never `position: fixed`. Spec: `docs/superpowers/specs/2026-08-24-profile-message-and-layout-polish-design.md`.
```

- [ ] **Step 4: Commit**

```bash
git add docs/01-DESIGN.md docs/superpowers/specs/2026-08-21-search-chrome-design.md ROADMAP.md
git commit -s -m "docs: the profile is the single Message entry point (spec 2026-08-24)"
```

---

### Task 4: Render the empty chips list truly empty

**Files:**
- Modify: `search/templates/search/widgets/typeahead_select.html` (the `<ul class="chips">` block)
- Test: `search/tests/test_filter_rows.py`

**Interfaces:**
- Consumes: `app.css`'s existing `.chips:empty { display: none }` (do NOT touch that rule — its comment explains why no author `display` may exist outside `:empty`).
- Produces: the exact empty-widget markup `<ul class="chips" data-chips></ul>` that the test below pins.

- [ ] **Step 1: Write the failing test**

Append to `search/tests/test_filter_rows.py` (imports and `pytestmark` already present):

```python
def test_empty_chips_list_renders_truly_empty(client: Client) -> None:
    """`.chips:empty { display:none }` is the hiding mechanism (app.css) — a
    lone whitespace text node defeats `:empty`, and the dead list's bottom
    margin pushed the three typeahead inputs 5px under their row neighbours
    (spec 2026-08-24 §3.1)."""
    content = client.get(reverse("home")).content.decode()
    assert content.count('<ul class="chips" data-chips></ul>') == 3
```

- [ ] **Step 2: Run it — must fail**

Run: `uv run pytest search/tests/test_filter_rows.py::test_empty_chips_list_renders_truly_empty -v`
Expected: FAIL — count is 0 today (the template leaves newline/indent text nodes inside the `<ul>`).

- [ ] **Step 3: Collapse the widget's chips block to one line**

In `search/templates/search/widgets/typeahead_select.html`, replace:

```django
  <ul class="chips" data-chips>
    {% for value, label in widget.chips %}
      {% include "search/widgets/_chip.html" with name=widget.name value=value label=label %}
    {% endfor %}
  </ul>
```

with:

```django
  {% comment %}
    One physical line, so an empty selection renders zero text nodes:
    app.css hides the empty list with `.chips:empty`, and `:empty` fails
    on a lone whitespace node (spec 2026-08-24 §3.1).
  {% endcomment %}
  <ul class="chips" data-chips>{% for value, label in widget.chips %}{% include "search/widgets/_chip.html" with name=widget.name value=value label=label %}{% endfor %}</ul>
```

- [ ] **Step 4: Run the search tests**

Run: `uv run pytest search/ -v`
Expected: ALL PASS — with chips selected the list has element children and stays visible; only the empty rendering changed.

- [ ] **Step 5: Browser check**

With the dev server tab on `http://localhost:8010` (viewport ≥1280px wide), run in the browser's JS tool:

```js
(() => {
  const tops = [...document.querySelectorAll('.filter')].map(f => {
    const input = f.querySelector('input:not([type=hidden]), select');
    return {label: f.querySelector('label')?.textContent.trim().slice(0, 20),
            top: Math.round(input.getBoundingClientRect().top)};
  });
  return JSON.stringify(tops);
})();
```

Expected: within each row, every `top` equal (Engines = Genres = Min. rating; Discipline = Countries = year). Before this fix the typeahead ones sat 5px lower. (`Open to work only` is Task 5 — still misaligned here.)

- [ ] **Step 6: Commit**

```bash
git add search/templates/search/widgets/typeahead_select.html search/tests/test_filter_rows.py
git commit -s -m "search: render the empty chips list truly empty so :empty hides it"
```

---

### Task 5: Align the open-to-work checkbox with its row's inputs

**Files:**
- Modify: `templates/search/people_search.html` (the person-row `.filter` div, ~line 75)
- Modify: `static/css/app.css` (after the `.filter > label` rule)

**Interfaces:**
- Consumes: the `.filter-row` grid (`align-items: start`) and `.filter { margin: .6rem 0 }` already in app.css.
- Produces: the `filter-checkbox` class name used only by the CSS added here.

- [ ] **Step 1: Tag the checkbox cell in the template**

In `templates/search/people_search.html`, inside the "About the person" fieldset loop, replace:

```django
      {% for field in form.person_fields %}
        <div class="filter">
```

with:

```django
      {% for field in form.person_fields %}
        {# The checkbox cell has no input row of its own — app.css bottom-aligns it onto the row's input line (spec 2026-08-24 §3.2). #}
        <div class="filter{% if field.name == 'open_to_work' %} filter-checkbox{% endif %}">
```

(The game-row loop above it keeps its plain `<div class="filter">`.)

- [ ] **Step 2: Bottom-align and lift the cell in CSS**

In `static/css/app.css`, directly after the `.filter > label { … }` rule, add:

```css
/* The inline checkbox has no input box under its label, so at the grid's
   `align-items: start` it floats at label height. Bottom-align the cell
   (both cells share .filter's .6rem bottom margin, so bottoms coincide)
   and pad half the neighbours' 37px input height minus half the checkbox
   line, centering the box on the input line. One-column layouts are
   unaffected: a cell alone in its row has nothing to align against. */
.filter-checkbox { align-self: end; padding-bottom: .55rem; }
```

- [ ] **Step 3: Browser check**

Reload `http://localhost:8010` (viewport ≥1280px) and run:

```js
(() => {
  const mid = (el) => { const b = el.getBoundingClientRect(); return Math.round(b.top + b.height / 2); };
  const year = document.querySelector('#id_year_from') || document.querySelector('input[name=year_from]');
  const otw = document.querySelector('input[name=open_to_work]');
  return JSON.stringify({year: mid(year), checkbox: mid(otw)});
})();
```

Expected: `|year − checkbox| ≤ 3`. If it's off by more, adjust `padding-bottom` in `.05rem` steps and re-measure. Also resize to mobile width (375px) and confirm the stacked single-column layout still reads normally (the checkbox simply follows its label rhythm).

- [ ] **Step 4: Run the search tests (template touched)**

Run: `uv run pytest search/ -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/search/people_search.html static/css/app.css
git commit -s -m "search: align the open-to-work checkbox with its row's inputs"
```

---

### Task 6: Align the header nav row's three controls

**Files:**
- Modify: `static/css/app.css` (the nav-search section, after `.nav-search input { … }`)

**Interfaces:**
- Consumes: `base.html`'s header markup — the search `<form>` inside `.nav-search`, the `<a role="button">` CTA, plain nav links. No markup change.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the alignment rules**

In `static/css/app.css`, directly after the `.nav-search input { width: 100%; min-width: 0; margin-bottom: 0; }` rule, add:

```css
/* Nav row alignment (spec 2026-08-24 §3.3). Pico's default form bottom
   margin inflated the search <li> downward, hoisting the field ~5px above
   its center-aligned neighbours; and the input (35px), the CTA (34px) and
   the nav links (37px) all carried different boxes, so no two top edges
   met. One 37px box — the nav links' natural height — for all three. */
.nav-search form { margin-bottom: 0; }
header nav input[type="search"],
header nav a[role="button"] { height: 37px; padding-block: 0; }
header nav a[role="button"] { display: inline-flex; align-items: center; }
```

- [ ] **Step 2: Browser check, desktop**

Reload `http://localhost:8010` at 1280×800 and run:

```js
(() => {
  const top = (el) => Math.round(el.getBoundingClientRect().top);
  const h = (el) => Math.round(el.getBoundingClientRect().height);
  const search = document.querySelector('header nav input[type=search]');
  const cta = document.querySelector('header nav a[role=button]');
  const login = document.querySelector('header nav a[href*="login"]');
  return JSON.stringify({search: [top(search), h(search)], cta: [top(cta), h(cta)],
                         login: login ? [top(login), h(login)] : null});
})();
```

Expected: the three `top` values within 1px of each other; heights 37 (login may read 37 from padding rather than height — that is the box being matched). Before: tops 26 / 30 / 31.

- [ ] **Step 3: Browser check, narrow**

Resize to 375px wide and reload. Expected: the search group still wraps onto its own row (the `@media (max-width: 767px)` block is untouched), nothing overlaps, the CTA and `Log in` share their row cleanly. Also verify logged-in state if dev fixtures provide a session, or skip — the logged-in nav uses the same `a[role=button]` selector.

- [ ] **Step 4: Commit**

```bash
git add static/css/app.css
git commit -s -m "chrome: align the nav row's search field, CTA and links"
```

---

### Task 7: Anchor the footer to the viewport bottom on short pages

**Files:**
- Modify: `static/css/app.css` (new section at the end of the file)

**Interfaces:**
- Consumes: Pico classless already gives `body > header/main/footer` `width: 100%; margin-inline: auto; max-width: …px`, so flex-column children keep their centered width (verified against the vendored file).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Add the flex-column page frame**

At the end of `static/css/app.css`, add:

```css
/* Footer on the viewport's bottom edge for short pages (spec 2026-08-24
   §4) — via flow, never position:fixed: the page column fills the viewport
   and <main> absorbs the slack. Safe with Pico's classless centering:
   body > header/main/footer already carry width:100% + max-width + auto
   inline margins, so becoming flex items changes nothing horizontally.
   100vh first: dvh is the correct mobile unit, vh the fallback where dvh
   is unknown. */
body { min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column; }
body > main { flex: 1 0 auto; }
```

- [ ] **Step 2: Browser check, short page**

From `http://localhost:8010`, search any discipline, open any person's profile (a dev-fixture profile is short enough), then run:

```js
(() => {
  const f = document.querySelector('body > footer').getBoundingClientRect();
  return JSON.stringify({short: document.body.scrollHeight <= innerHeight + 1,
                         footerBottom: Math.round(f.bottom), viewport: innerHeight});
})();
```

Expected: `short: true` and `footerBottom` within 1px of `viewport`. If `short` is false the profile has too much content to prove the point — use a sparser page (e.g. `/about/` or an empty search) instead.

- [ ] **Step 3: Browser check, long page**

Back on home, run a search returning results (or open any page taller than the viewport). Expected: normal scrolling, footer after the content exactly as before — `document.body.scrollHeight > innerHeight` and the footer only visible at scroll end.

- [ ] **Step 4: Commit**

```bash
git add static/css/app.css
git commit -s -m "layout: anchor the footer to the viewport bottom on short pages"
```

---

### Task 8: Full gate and visual proof

**Files:** none created — verification only.

- [ ] **Step 1: The CI quartet**

```bash
uv run pytest
```
Expected: all tests pass.

```bash
uv run ruff check . && uv run ruff format --check .
```
Expected: no findings.

```bash
uv run ty check
```
Expected: no errors (no Python changed outside tests, so this is a formality).

- [ ] **Step 2: Docker build (fresh-clone gate — CI runs it; run it once here since templates/static land in the image)**

```bash
docker build .
```
Expected: image builds.

- [ ] **Step 3: Browser sweep + screenshots for the owner**

At 1280×800 and at 375px: home page (filter rows aligned, header row aligned), a profile logged-out (Message button present, footer on the viewport bottom edge). Take screenshots of home and one profile and share them with the owner as proof.

- [ ] **Step 4: Verify the working tree is clean and pushed state is intended**

```bash
git status && git log --oneline -8
```
Expected: clean tree; the seven commits from Tasks 1–7 on `main`. Do not push unless the owner asks.
