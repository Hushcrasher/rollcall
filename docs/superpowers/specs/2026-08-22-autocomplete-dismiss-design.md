# Autocomplete dropdowns: dismissable, and sized to their field — design

> Status: proposed 2026-08-22, decisions validated with the product owner the
> same day. Presentation and client behaviour only — no model, no migration,
> no view change. Touches `templates/base.html`, `static/css/app.css`,
> `templates/search/_company_options.html`, and adds one file,
> `static/js/autocomplete.js`.

## Problems

1. **A dropdown never closes, and it covers the next field.** Only picking an
   option empties it. Reproduced on `/declare/details/` on 2026-08-22:
   searching an employer that does not exist leaves `No companies found.` plus
   its hint sitting from y=282 to y=408, while the `Discipline` label it
   overlays starts at y=282 — the field underneath cannot be clicked. There is
   no outside-click handler, no `Escape` handler and no blur handler anywhere
   in the codebase; every one of the four call sites can trap the user this
   way, the game field and the nav search included.
2. **A dropdown is wider than the field it belongs to.** `app.css` gives
   `.results` / `.nav-suggest` a flat `min-width: 20rem`, so on the narrow
   filter columns of the home page the panel juts out over its neighbour.
3. **There is no shared behaviour to fix.** Each call site carries its own
   inline `<script>`; the dropdown is the one interaction the whole site
   repeats and the one with no common owner.

### Where the dropdowns are

| Panel | Owner | Filled by |
|---|---|---|
| `#nav-suggest` | `.nav-search` (`base.html`) | `search:suggest` |
| `.results` (game) | `.autocomplete` (`contribution_form.html`) | `search:game_autocomplete` |
| `.results` (employer) | `.autocomplete#employer-field` (`_employer_field.html`, shared by `contribution_form.html` and `declare_details.html`) | `search:company_autocomplete` |
| `.results` (engines / genres / countries) | `.autocomplete.typeahead` (`search/widgets/typeahead_select.html`) | the three `search:*_autocomplete` filter endpoints |

Every panel is filled by htmx (`hx-target`), and every one of them sits inside
a `position: relative` owner — `.autocomplete` for four of them, `.nav-search`
for the fifth.

## Decisions

| Question | Decision |
|---|---|
| What closes it | **Outside `pointerdown`, `Escape`, and focus leaving the field group** |
| Hide or clear | **Hide** (`hidden` attribute), never clear — refocusing the input shows the last results again; typing replaces them |
| Where the code lives | **One shared `static/js/autocomplete.js`**, loaded from `base.html`, delegated at the document level — no per-template copy |
| Width | The panel **matches its field**, and may still grow for long titles |
| Info texts | **Stay inside the panel** (they answer the query) but get **shorter** |
| ARIA combobox | **Out of scope** — see below |

## 1. `static/js/autocomplete.js`

One file, `defer`, loaded from `base.html` next to htmx so every page gets it.
It never creates or fills a panel — htmx does that. It only toggles `hidden`.

**Resolving a panel's owner** is the module's single piece of knowledge about
the page:

```js
const OWNER = ".autocomplete, .nav-search";
const PANEL = ".results, .nav-suggest";
```

An owner has exactly one panel; a panel has exactly one owner. No template
change is needed for this — the two selectors already describe all five sites,
and `.autocomplete` is what `app.css` already positions against.

**The four events:**

- **`htmx:afterSwap`** — un-hide the panel that received the swap. A fresh
  result set must appear even if the panel was dismissed a moment earlier;
  without this, dismissing once would make the field look broken on the next
  keystroke.
- **`pointerdown` on the document** — hide every panel whose *owner* does not
  contain the event target. `pointerdown`, not `click`: `click` fires after
  focus has already moved, and a `click` handler that also dismisses would
  swallow the first press on whatever sits under the panel. With
  `pointerdown` the panel is gone before the press lands, so the press
  reaches the field underneath — which is the actual bug being fixed.
- **`keydown` `Escape`** — hide the panel of the focused input, and call
  `preventDefault()` **only if a panel was actually open**. Otherwise `Escape`
  must keep reaching the browser's own behaviour on a `type=search` input
  (clear the field). One `Escape` closes the list; a second clears the box.
- **`focusin`** — when focus enters an input inside an owner, un-hide that
  owner's panel if it has content, and hide all the others. This is what makes
  "hide, don't clear" work: coming back to a field you dismissed shows the
  same results rather than an empty box that only refills if you type.

**Why `hidden` and not emptying the panel:** emptying loses the result set, so
returning to the field means retyping. `hidden` is also cheap to reason
about — one attribute, no state object to keep in sync with the DOM htmx
rewrites underneath us.

**Why `hidden` actually hides:** the UA stylesheet's `[hidden] { display: none }`
is specificity (0,1,0) and `app.css` sets no `display` on `.results` /
`.nav-suggest` outside of `:empty`. Nothing in the project overrides it. This
is a real constraint on future edits to `app.css`, and gets a comment saying
so next to the positioning block.

**No behaviour is removed.** Picking an option still clears the panel through
the existing per-template handlers; this module is additive.

## 2. Width (`static/css/app.css`)

`min-width: 20rem` becomes `min-width: 100%`: at least as wide as the owner
(which is as wide as the field), free to grow to the existing `max-width: 90vw`
for a long game title. `max-height: 20rem` and `overflow-y: auto` are unchanged.

This is layout, so it stays in `app.css` under that file's existing rule.

## 3. Shorter info texts (`templates/search/_company_options.html`)

The two hints are the reason the trapped panel was 126px tall. They stay —
they answer the query, and a visitor who cannot find their studio needs them —
but they shorten, and keep their i18n:

| Today | Becomes |
|---|---|
| `Employer is optional — you can add it once you've created your account.` | `Optional — you can add it after signing up.` |
| `Employer is optional — you can add it later from your credit.` | `Optional — you can add it later.` |

The two branches and their conditions (anonymous vs. logged-in-without-
`offer_create`) are unchanged; only the strings shorten. The comments in that
template explaining *why* there are two stay as they are.

## Out of scope

- **A WAI-ARIA combobox.** The panel is a `<div>` of `<button>`s, which is
  keyboard-reachable by Tab today and stays so; `Escape` closing it is a real
  accessibility gain. Arrow-key navigation, `role="listbox"`,
  `aria-activedescendant` and `aria-expanded` are a larger, separate change —
  a natural follow-up, noted in ROADMAP, not folded in here.
- Debounce, minimum query length, result count: unchanged.
- The IGDB fallback rendered inside the game panel: separate spec,
  `2026-08-22-igdb-auto-fallback-design.md`.

## Docs & tests

`docs/01-DESIGN.md` §3.3 gains one line on dropdown dismissal; `docs/03-TECH-STACK.md`
records `static/js/autocomplete.js` as the site's only hand-written script
outside templates; ROADMAP gets an entry.

**Tests.** The dismissal itself is client behaviour and the suite has no
JavaScript runner — asserting it in pytest is not possible and should not be
faked. What pytest *does* cover:

- `base.html` loads `js/autocomplete.js` (a template-diff test, the same shape
  as the existing htmx/CSS asset assertions).
- The two shortened hint strings render in their respective branches — the
  existing `_company_options.html` tests change to the new copy rather than
  gaining new ones.

**Browser verification** (the acceptance checklist for the implementer, run on
each of the five panels):

1. Open a panel, click a field below it → the click lands on that field.
2. Open a panel, press `Escape` → it closes. Press `Escape` again on the nav
   search → the input clears.
3. Open a panel, Tab away → it closes. Shift-Tab back → the same results
   reappear without retyping.
4. Dismiss a panel, type one more character → results reappear.
5. Pick an option → the panel clears and the choice is filled, as today.
6. At 375px, no panel is wider than its field.
