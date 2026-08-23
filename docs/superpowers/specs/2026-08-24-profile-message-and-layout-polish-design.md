# Profile-only Message button, filter-row alignment, sticky footer — design

Date: 2026-08-24. Approved by the owner in session.

## 1. Context

Three visual/behavioral defects reported on the 2026-08-23 build:

- The `Message` button renders on every search result card, next to the
  person's name — the owner wants contact to start from the profile page only.
  Meanwhile the profile's own `Message` button is invisible to logged-out
  visitors, so the surface a recruiter lands on first shows no contact action.
- The filter rows on home are not vertically aligned: the typeahead inputs
  (Engines, Genres, Countries) sit 5px lower than the plain fields, and the
  `Open to work only` checkbox floats at label height instead of input height.
  In the header, the search field, the `Add your credit` button and `Log in`
  have different heights and top edges.
- On short pages (e.g. a profile), the footer sits directly under the content
  instead of at the bottom of the viewport.

## 2. Message button: the profile is the single entry point

Amends `docs/superpowers/specs/2026-08-21-search-chrome-design.md` §4, which
put the button on profile **and** search cards. Decision (owner, 2026-08-24):
cards lose the button; the profile shows it to everyone except the owner.

### Behavior

- `templates/search/people_search.html`: the result card renders **no**
  contact link/button. The display name (→ profile) stays the card's only
  person link. The relay URL must not appear anywhere in the card.
- `templates/accounts/profile.html`: when `profile_user.contactable`, the
  existing `<a role="button">` to `contact:contact` renders for **any viewer
  who is not the owner** — anonymous included. The owner's `?preview=member`
  keeps the muted `Message` placeholder; the owner's normal view keeps
  showing nothing.
- No view or URL changes. An anonymous click follows the existing gates:
  `ContactView` is `EmailVerifiedRequiredMixin(LoginRequiredMixin)`, so the
  visitor is bounced to login with `?next=` back to the form, and the
  email-verified rule (docs/00 #6) still guards the relay itself.
- No new user-facing strings; `Message` is already translated.

### Visibility matrix (tests, `accounts/tests/test_message_button.py`)

| Viewer                      | contactable target | Profile page       | Search card |
| --------------------------- | ------------------ | ------------------ | ----------- |
| Anonymous                   | yes                | button             | nothing     |
| Authenticated visitor       | yes                | button (unchanged) | nothing     |
| Owner (normal view)         | yes                | nothing            | nothing     |
| Owner (`?preview=member`)   | yes                | muted placeholder  | nothing     |
| Anyone                      | no                 | nothing            | nothing     |

### Docs amended in the same change

- `docs/01-DESIGN.md` §"Contact via relay form": "on the profile and on
  search result cards" becomes profile-only, with a pointer to this record.
- `docs/superpowers/specs/2026-08-21-search-chrome-design.md`: its two
  now-false statements (§4 card button, the test note) get an amendment note
  pointing here — the record itself stays as history.
- `ROADMAP.md`: one line under the current milestone.

## 3. Alignment fixes

### 3.1 Typeahead chips (root cause, measured)

`search/templates/search/widgets/typeahead_select.html` renders
`<ul class="chips" data-chips>` with template whitespace inside, so with no
chips selected the element still contains a text node — `.chips:empty
{ display: none }` never matches, and the empty list's 4.5px margin pushes
the three typeahead inputs 5px below their row neighbours.

Fix: make the empty rendering truly empty (tighten the template so the
`<ul>…</ul>` contains no text nodes when `widget.chips` is empty). Keep the
`:empty` mechanism — app.css already documents why no author `display` may
be added outside `:empty`.

### 3.2 `Open to work only` checkbox

Decision (owner, 2026-08-24): keep the inline `checkbox + label` form —
no column label added. CSS-only: the checkbox line moves down so it aligns
vertically with the adjacent inputs' row (Countries / year fields), not with
their labels. Scoped to the filter row; the no-JS layout must stay sane.

### 3.3 Header controls

At desktop width the three nav controls measure: search input 35px tall
(top 26), `Add your credit` 34px (top 30), `Log in` 37px (top 31). CSS-only
normalization in `static/css/app.css`: the search field, the nav CTA and the
nav links share the same visual height and top edge (±1px) at ≥768px. The
narrow-viewport wrapping rules (search on its own row) are untouched.

## 4. Sticky footer (min-height, not fixed)

`body` becomes a flex column at least the viewport height (`min-height:
100dvh` with a `100vh` fallback); `main` grows to fill the remaining space.
The footer keeps its place in normal flow: on long pages nothing moves; on
short pages its bottom edge lands on the viewport's bottom edge. Must not
break Pico's classless centering of `body > header/main/footer` (check
horizontal padding/max-width after the change).

## 5. Non-goals

- No change to the contact relay, rate limiting, or report flows.
- No change to search ranking, filters' semantics, or the typeahead JS.
- No visual redesign beyond the alignments listed — colors, fonts, spacing
  rhythm stay Pico's.

## 6. Verification

- pytest: the visibility matrix above; existing profile-preview and search
  tests keep passing; a card assertion proves the relay URL is absent.
- Browser (dev server, 1280×800 and mobile width): filter inputs of one row
  share the same top edge; checkbox aligned with the input line; header
  control top edges within 1px; profile page footer bottom == viewport
  bottom; a long page (home with results) scrolls normally.
- CSS-only items are browser-verified — no pytest asserts computed styles
  (house rule already stated in app.css).
