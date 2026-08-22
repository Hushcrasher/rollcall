# Dismissable autocomplete dropdowns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every autocomplete panel close on an outside press, on `Escape`, and when focus leaves its field — so a dropdown can never sit on top of the next form field and block it.

**Architecture:** One shared script, `static/js/autocomplete.js`, loaded from `base.html` and delegating at the document level. It never creates or fills a panel — htmx already does that — it only toggles the `hidden` attribute. Two CSS selectors describe all five panels on the site, so no template needs a new hook.

**Tech Stack:** Django templates, htmx (vendored), plain ES5-compatible JavaScript (no build step, no framework), Pico CSS v2 + `theme.css` + `app.css`.

**Spec:** [`docs/superpowers/specs/2026-08-22-autocomplete-dismiss-design.md`](../specs/2026-08-22-autocomplete-dismiss-design.md)

## Global Constraints

- **Every user-facing string goes through i18n** (`gettext` / `{% translate %}`), inline JS included.
- **Python is fully typed** — annotate every function, method and test. `uv run ty check` must pass.
- **TDD is the house style**: write the failing test first, watch it fail, then implement.
- **Commits are DCO signed-off**: `git commit -s`. CI rejects unsigned commits on a PR.
- **`app.css` carries functional layout only.** Colours, fonts and decoration belong in `theme.css` (amended 2026-08-22, ROADMAP Phase 15).
- The full toolchain must pass before every commit: `uv run pytest` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run ty check`.
- Postgres must be up for the tests: `docker compose up db`.
- Work on a branch — `feat/autocomplete-dismiss` — and open a PR; do not commit to `main`.

## File Structure

| File | Responsibility |
|---|---|
| `static/js/autocomplete.js` | **Create.** The whole dismissal behaviour. The site's only hand-written script outside a template. |
| `templates/base.html` | **Modify.** Load the script, deferred, after htmx. |
| `static/css/app.css` | **Modify.** Panel width, plus the comment recording that nothing here may set `display`. |
| `templates/search/_company_options.html` | **Modify.** Shorten the two employer hints. |
| `search/tests/test_autocomplete.py` | **Modify.** Three existing tests assert the old copy. |
| `config/tests/test_base_template.py` | **Modify.** Assert the new asset is loaded, in the right order. |
| `docs/01-DESIGN.md`, `docs/03-TECH-STACK.md`, `ROADMAP.md` | **Modify.** Record the behaviour and the new asset. |

Two tasks. Task 1 is a self-contained copy change with its own tests; Task 2 is the behaviour, and carries the width fix and the docs because neither is independently testable.

---

### Task 1: Shorten the two employer hints

The panel that traps the user is 126px tall, and most of that is these two sentences. They stay — a visitor who cannot find their studio needs them — but they shorten.

**Files:**
- Modify: `templates/search/_company_options.html:17-19` and `:31-33`
- Test: `search/tests/test_autocomplete.py:89-130` (three existing tests)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. No Python signature changes.

> **Read this before you start.** Three existing tests assert `b"optional"` — lowercase. Both new strings start with a capitalised `Optional`, so **those tests fail on the copy change alone**. That is why this task rewrites them first rather than adding new ones.

- [ ] **Step 1: Rewrite the three failing assertions**

In `search/tests/test_autocomplete.py`, replace the three `optional` assertions. Keep every docstring exactly as it is — they explain *why* there are two different hints, and that reasoning has not changed.

In `test_company_autocomplete_tells_an_anonymous_visitor_the_employer_is_optional`:

```python
    response = client.get(reverse("search:company_autocomplete"), {"q": "Nonexistent Studio"})
    assert b"No companies found." in response.content
    # Asserted on an ASCII fragment, not the whole sentence: the copy carries
    # an em dash, and a byte comparison against it is a needless trap.
    assert b"after signing up" in response.content
    assert b"{#" not in response.content
```

In `test_company_autocomplete_keeps_the_optional_hint_away_from_a_member`:

```python
    assert b"No companies found." in response.content
    assert b"Optional" not in response.content
    assert b"{#" not in response.content
```

In `test_company_autocomplete_tells_a_member_on_the_declare_funnels_step_2_the_employer_is_optional`, change its `optional` assertion to:

```python
    assert b"add it later" in response.content
```

- [ ] **Step 2: Run the three tests to verify they fail**

```bash
uv run pytest search/tests/test_autocomplete.py -k optional -v
```

Expected: 3 failed — the new fragments are not in the rendered content yet.

- [ ] **Step 3: Shorten the two strings**

In `templates/search/_company_options.html`, line 18:

```html
      {% translate "Optional — you can add it after signing up." %}
```

and line 32:

```html
      {% translate "Optional — you can add it later." %}
```

Change nothing else in that file: the two branches, their conditions and the `{% comment %}` blocks explaining them all stay exactly as they are.

- [ ] **Step 4: Run the three tests to verify they pass**

```bash
uv run pytest search/tests/test_autocomplete.py -k optional -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the whole suite and the linters**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

Expected: 587 passed, all checks clean. If another test asserted the old copy, it surfaces here.

- [ ] **Step 6: Commit**

```bash
git add templates/search/_company_options.html search/tests/test_autocomplete.py
git commit -s -m "fix(search): shorten the two employer hints

Their height is most of what made the company dropdown cover the field
below it. The two branches and the reasoning for having two are unchanged;
only the sentences shorten. Three tests asserted the lowercase 'optional'
that the new copy no longer contains, and move to ASCII fragments of the
new strings — the copy carries an em dash, and byte-comparing that is a
needless trap."
```

---

### Task 2: The dismissal module

**Files:**
- Create: `static/js/autocomplete.js`
- Modify: `templates/base.html:19` (add one `<script>` after htmx)
- Modify: `static/css/app.css:43-49`
- Modify: `config/tests/test_base_template.py`
- Modify: `docs/01-DESIGN.md` §3.3, `docs/03-TECH-STACK.md`, `ROADMAP.md`

**Interfaces:**
- Consumes: the DOM shapes already on the page. `.autocomplete` (four field panels) and `.nav-search` (the nav suggest box) are the *owners*; `.results` and `.nav-suggest` are the *panels*. Every owner already carries `position: relative` from `app.css`, and each contains exactly one panel.
- Produces: no Python and no template API. Later work relies only on the invariant that **a panel is hidden by setting its `hidden` attribute**.

- [ ] **Step 1: Write the failing test**

Add to `config/tests/test_base_template.py`:

```python
def test_every_page_loads_the_autocomplete_dismiss_script(client: Client) -> None:
    """Every page carries a dropdown — the nav search box — so the module that
    dismisses one is sitewide. Both properties asserted here are load-bearing:
    `defer`, because it binds document-level listeners and must not run before
    the DOM exists; and the order after htmx, because one of those listeners is
    for htmx's own `htmx:afterSwap` event (spec 2026-08-22-autocomplete-dismiss
    §1)."""
    body = client.get(reverse("home")).content.decode()
    htmx = body.index("vendor/htmx.min.js")
    module = body.index("js/autocomplete.js")
    assert htmx < module
    assert "defer" in body[module : module + 40]
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest config/tests/test_base_template.py::test_every_page_loads_the_autocomplete_dismiss_script -v
```

Expected: FAIL — `ValueError: substring not found` on `js/autocomplete.js`.

- [ ] **Step 3: Load the script from `base.html`**

In `templates/base.html`, directly after the htmx line (line 19):

```html
  <script src="{% static 'vendor/htmx.min.js' %}" defer></script>
  <script src="{% static 'js/autocomplete.js' %}" defer></script>
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest config/tests/test_base_template.py -v
```

Expected: PASS. (The file does not exist yet — the test asserts the tag, not the asset. Step 5 writes it, and `collectstatic` in the Docker build would fail without it, which the final check catches.)

- [ ] **Step 5: Write the module**

Create `static/js/autocomplete.js`:

```js
// Dismissable autocomplete panels — spec 2026-08-22-autocomplete-dismiss.
//
// htmx creates and fills every panel on this site; this module only ever
// toggles `hidden` on one. Two selectors describe all five panels (the nav
// suggest box, the credit form's game field, the shared employer field, and
// the three filter typeaheads), so no template needs a hook of its own.
//
// `hidden` is what actually hides a panel: the UA stylesheet's
// `[hidden] { display: none }` is specificity (0,1,0) and `app.css` sets no
// `display` on these two outside `:empty`. Adding one there would silently
// break every dismissal on the site — app.css carries a comment saying so.
//
// Panels are HIDDEN, never emptied: emptying loses the result set, so coming
// back to a field you dismissed would mean retyping.
(function () {
  "use strict";

  var OWNER = ".autocomplete, .nav-search";
  var PANEL = ".results, .nav-suggest";

  // Elements are the only event targets we care about; `document` and text
  // nodes have no closest().
  function panelFor(target) {
    if (!target || !target.closest) return null;
    var owner = target.closest(OWNER);
    return owner ? owner.querySelector(PANEL) : null;
  }

  function hideAllExcept(keep) {
    var panels = document.querySelectorAll(PANEL);
    for (var i = 0; i < panels.length; i++) {
      if (panels[i] !== keep) panels[i].hidden = true;
    }
  }

  // A fresh result set must appear even if the panel was dismissed a keystroke
  // ago, or the field looks broken on the next character typed.
  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.target;
    var panel = target && target.closest ? target.closest(PANEL) : null;
    panel = panel || panelFor(target);
    if (panel) panel.hidden = false;
  });

  // pointerdown, NOT click: click fires after focus has already moved, and
  // dismissing there would swallow the first press on whatever sits under the
  // panel. Here the panel is gone before the press lands, so the press reaches
  // the field underneath — which is the bug this module exists for.
  document.addEventListener("pointerdown", function (event) {
    hideAllExcept(panelFor(event.target));
  });

  // Escape closes the open panel, and calls preventDefault ONLY when one was
  // open — so a second Escape still reaches the browser's own behaviour on a
  // type=search input (clear the field).
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var panel = panelFor(event.target);
    if (panel && !panel.hidden) {
      panel.hidden = true;
      event.preventDefault();
    }
  });

  // Focus entering a field shows what that field last found; focus landing
  // anywhere else closes everything. This is what makes "hide, don't clear"
  // worth doing. A click on an option focuses that option's button, whose
  // owner is the same panel — so the panel survives long enough for the
  // existing per-template click handler to read it.
  document.addEventListener("focusin", function (event) {
    var panel = panelFor(event.target);
    if (panel && panel.innerHTML.trim() !== "") panel.hidden = false;
    hideAllExcept(panel);
  });
})();
```

- [ ] **Step 6: Fix the panel width and pin the `display` constraint**

In `static/css/app.css`, replace lines 43-49 with:

```css
.results, .nav-suggest {
  position: absolute; z-index: 100; left: 0; top: 100%;
  /* At least as wide as the field this hangs under, free to grow for a long
     game title. A flat 20rem made the panel jut out over its neighbour in the
     search form's narrow columns. */
  min-width: 100%; max-width: 90vw; max-height: 20rem; overflow-y: auto;
  background: var(--pico-background-color); color: inherit;
  border: 1px solid var(--pico-muted-border-color);
}
/* `static/js/autocomplete.js` dismisses a panel by setting the `hidden`
   attribute, which works only because nothing here gives these two a
   `display` outside `:empty`: the UA sheet's `[hidden] { display: none }` is
   (0,1,0) and would lose to any author rule added below. Do not give them
   one — no test can catch it, and it would break every dropdown at once. */
.results:empty, .nav-suggest:empty { display: none; }
```

- [ ] **Step 7: Verify in the browser**

The dismissal is client behaviour and the suite has **no JavaScript runner** — this checklist is the acceptance gate, not an optional extra. Start the dev server (`.claude/launch.json`, port 8010) and run all six on **each** of the five panels: the nav search box, the credit form's game field, the employer field on `/credits/new/`, the employer field on `/declare/details/`, and one filter typeahead on the home page.

1. Open a panel, then click a field below it → the click lands on that field.
2. Open a panel, press `Escape` → it closes. Press `Escape` again on the nav search box → the input clears.
3. Open a panel, Tab away → it closes. Shift-Tab back → the same results reappear, without retyping.
4. Dismiss a panel, type one more character → results reappear.
5. Pick an option → the panel clears and the choice is filled, exactly as before.
6. At 375px, no panel is wider than its field.

The reproduction case from the spec is #1 on the `/declare/details/` employer field: search a company that does not exist, then click `Discipline`.

- [ ] **Step 8: Record it in the docs**

In `docs/01-DESIGN.md` §3.3, after the employer-picker bullet, add:

```markdown
- **Autocomplete panels are dismissable** (added 2026-08-22, spec `docs/superpowers/specs/2026-08-22-autocomplete-dismiss-design.md`): every dropdown on the site — nav suggest, game, employer, and the three filter typeaheads — closes on an outside press, on `Escape`, and when focus leaves its field, and reopens on focus or on the next result set. Before this, a panel closed only when an option was picked, so "No companies found." plus its hint sat on top of the next field and blocked it. Panels are hidden, not emptied, so returning to a field shows what it last found.
```

In `docs/03-TECH-STACK.md`, in the Templates/front row, after the CSS clause:

```markdown
JS: htmx (vendored) plus one hand-written module, `static/js/autocomplete.js` (added 2026-08-22) — the site's only script outside a template, and deliberately the only one.
```

In `ROADMAP.md`, under "Post-roadmap additions":

```markdown
- [x] **Dismissable autocompletes** (2026-08-22): every dropdown closes on outside press, `Escape` and focus-out, and reopens on focus or the next swap — one shared `static/js/autocomplete.js`, document-level delegation, no template hook. `pointerdown` rather than `click` is load-bearing: `click` fires after focus moves, so dismissing there would swallow the first press on the field underneath, which is the whole bug. Panels are hidden, never emptied. The behaviour has no pytest coverage (no JS runner) — the spec carries a six-point browser checklist instead. Spec: `docs/superpowers/specs/2026-08-22-autocomplete-dismiss-design.md`.
```

- [ ] **Step 9: Run the full toolchain**

```bash
uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check && docker build -q . > /dev/null && echo "docker ok"
```

Expected: 588 passed, all checks clean, `docker ok`. The Docker build runs `collectstatic`, which is what proves the new asset exists at the path `base.html` names.

- [ ] **Step 10: Commit**

```bash
git add static/js/autocomplete.js templates/base.html static/css/app.css \
        config/tests/test_base_template.py docs/01-DESIGN.md docs/03-TECH-STACK.md ROADMAP.md
git commit -s -m "feat(search): dismissable autocomplete panels

A dropdown closed only when an option was picked, so 'No companies found.'
plus its hint sat on top of the Discipline field and blocked it — measured
at 282-408px against a label starting at 282px. No outside-click, Escape or
blur handling existed anywhere.

One shared static/js/autocomplete.js, document-level delegation, no
template hook: two selectors already describe all five panels. It never
creates or fills a panel, only toggles `hidden`.

pointerdown, not click: click fires after focus has moved, so dismissing
there would swallow the first press on whatever sits under the panel. Here
the panel is gone before the press lands.

Panels are hidden, never emptied, so returning to a field shows what it
last found. Escape calls preventDefault only when a panel was genuinely
open, so a second Escape still clears a search input.

The panel also stops being wider than its field. app.css gains a comment
pinning the one constraint that would silently break all of this: nothing
there may give these elements a `display` outside `:empty`."
```

---

## Self-review

**Spec coverage.** §1 the module → Task 2 steps 3-5; §1 the four events → all four are in the Step 5 code; §2 width → Task 2 step 6; §3 shorter hints → Task 1; out-of-scope items (ARIA combobox, arrow keys) are absent, as intended. Docs & tests section → Task 2 steps 1, 7, 8.

**Placeholders.** None: every code step carries the code, every command its expected output.

**Type consistency.** No Python signature is added or changed. The one cross-step contract is the `hidden` attribute, used identically in the module (Step 5) and pinned by the comment in `app.css` (Step 6).

**Known gap, deliberate.** The dismissal itself has no automated test. This is stated in the spec and in the ROADMAP entry rather than papered over with an assertion that does not exercise it. Arrow-key navigation and a full WAI-ARIA combobox are the natural follow-up and are out of scope here.
