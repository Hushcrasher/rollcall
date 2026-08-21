# Mobile-first surface: Pico CSS, home reorder, latest-credits feed — design

> Status: validated 2026-08-20. Behavior source of truth stays
> [docs/01-DESIGN.md](../../01-DESIGN.md); this spec adds a style layer, reorders
> the home page, adds a read-only feed and an About page, and fixes date
> display. One route added (`/about/`), no model change, no migration.
>
> It **supersedes one decision** of
> [2026-08-11-home-is-people-search-design.md](2026-08-11-home-is-people-search-design.md):
> anonymous visitors no longer see the declare funnel *above* the search. The
> funnel itself is untouched; only its home-page entry point changes (a one-line
> banner plus the new nav CTA).

## Problem

The site ships zero CSS. That was a deliberate POC posture, and the HTML held
up: a 375px mobile audit (2026-08-20, dev fixtures) found no horizontal
overflow and every form usable. But four real defects:

1. **Dark mode is broken.** No `color-scheme` is declared, so browsers in dark
   mode paint near-black default text on a near-black `Canvas` — headings are
   unreadable.
2. **Everything renders in the browser's serif default.**
3. The nav bar wraps badly on small screens (the search box hardcodes
   `size=35`) and nothing on it pushes the product's #1 metric, declaring
   credits.
4. After a search, results render **below the whole filter stack** — on mobile
   the user must scroll past every filter to see them.

Separately, credit dates display as `Aug 2024` (`date:"M Y"`), and entry uses
the native month picker, which renders in the *visitor's* browser locale — a
French tester reads "août 2026" and thinks the site leaks French. It doesn't;
English browsers see English.

## Decisions (validated with the product owner, 2026-08-20)

| Question | Decision |
|---|---|
| CSS layer | **Pico CSS v2, classless variant**, vendored — no build step, no CDN |
| Home order | **Filters first for everyone**; worker pitch becomes a one-liner + nav CTA |
| Dates | **Native month input kept** for entry; every displayed credit date becomes **`MM/YYYY`** |
| Wordmark | No logo. The nav brand is the text **ROLLCALL** in bold |
| About page | Yes — static, footer link |

## 1. Style layer

- Vendor `pico.classless.min.css` (Pico CSS v2, latest 2.x at implementation
  time; record the version in a comment at the top of the vendored file) into
  `static/vendor/`, loaded from
  `base.html` before `{% block extra_head %}`.
- Pico's classless mode styles `body > header/main/footer` as centered
  containers and themes `nav`, forms, buttons and `article` from bare
  semantics. It declares `color-scheme: light dark` — that alone fixes defect
  1 — and uses a system sans-serif stack (defect 2).
- Move the inline `<style>` blocks of `base.html` and `people_search.html`
  into one new `static/css/app.css`. **Rule, and the review bar for every
  future edit to that file: `app.css` carries functional layout only**
  (autocomplete dropdown positioning, chip flex layout, the thumbnail grid of
  the gallery spec). No colors, no font choices, no radii/shadows/decoration —
  where a color is unavoidable (dropdown background) use Pico's CSS variables
  (`var(--pico-background-color)` etc.), never literals. Aesthetics come from
  Pico or don't happen.
- Delete rules Pico makes redundant instead of porting them. `.muted`
  (opacity) stays; the system-color hacks (`Canvas`, `GrayText`…) go.
- Django messages (`ul.messages`) currently render unstyled; keep them as a
  plain list styled by Pico defaults, no custom treatment.

### Nav bar (`base.html`)

Pico styles a `<nav>` with `<ul>` groups; restructure to its idiom (this is
semantics, not decoration):

- Left: `<a href="{% url 'home' %}"><strong>ROLLCALL</strong></a>` — text
  wordmark, no image.
- Middle: the existing global search form; drop `size=35`, let CSS size it
  (`app.css`: flexible width, `min-width: 0` so it shrinks on mobile). Sweep
  the remaining hardcoded `size` attributes (the `/declare/` game form) the
  same way while at it.
- Right: **`Add your credit`** as the nav's only `role="button"` element —
  Pico renders it as the single solid primary button on the bar, making it the
  most visible control (product decision: the worker CTA outranks login).
  - Authenticated → `contributions:create` (`/credits/new/` keeps its
    verified-email gate; unverified users get the existing bounce).
  - Anonymous → `contributions:declare` (`/declare/` already serves GET and is
    the funnel's natural entry).
- Then `Log in` / `My profile`, `Account`, `Log out` as plain links. `Sign
  up` drops off the nav for anonymous visitors: the declare funnel *is* the
  signup path (docs/01 §3.3), and login page links keep the direct route
  reachable.
- On mobile the nav wraps to a second row, with the search group on its own
  line. This is **not** a Pico default — Pico v2 lays `nav`/`nav ul` out with
  `display:flex` and ships no `flex-wrap` and no nav media query at all, so
  the bar would overflow into itself at 375px; `static/css/app.css` supplies
  the wrapping (functional layout, within that file's rule). No hamburger
  menu — four items don't need one.

## 2. Home page order (`people_search.html`)

Top to bottom, all viewports, anonymous and authenticated alike:

1. `<h1>Find people by what they've worked on</h1>`
2. Anonymous only, one line: `Worked on a game? Add your credit — no account
   needed to start.` where "Add your credit" links to `contributions:declare`.
   The `Which game did you work on?` H1 + inline game form and the `Looking
   for someone?` H2 leave this page; `/declare/` already carries that H1 and
   the same form, so nothing moves — the home block is simply removed.
3. The filter form, full width (it is the page's only column; Pico's
   container provides the margins).
4. `#results` anchor, then: search results when `searched`, otherwise the
   **Latest credits** feed (§3).

The form gains `action="{% url 'home' %}#results"` so a submit lands the
viewport on the results, which fixes defect 4 without JavaScript.

SEO note: the home page now indexes under the recruiter-facing question. The
2026-08-11 spec accepted indexing under the worker question; this reverses
that, knowingly — the worker funnel keeps its own indexable page at
`/declare/`.

## 3. Latest-credits feed

Social proof and freshness on an otherwise empty first visit.

- Query: `Contribution.objects.filter(status="active",
  user__profile_public=True, game__isnull=False).select_related("user",
  "game", "discipline").order_by("-created_at")[:10]`, computed in
  `PeopleSearchView.get_context_data` only when no search ran.
  `game__isnull=False` is a correctness clause, not an optimisation:
  `Contribution.game` is nullable (its check constraint accepts a company
  instead) and the feed line links the game, so a gameless row raises
  `NoReverseMatch` on the home page.
- Render (one `<li>`/entry, i18n via `blocktranslate`):
  `{display_name} added a credit on {game}: {job_title} (MM/YYYY – MM/YYYY)`
  — name links to the profile, game to the game page, `present` for open
  ends. Heading: `Latest credits`.
- **Privacy guards are the point**: only `status="active"` rows (the sole
  publishable status, docs/00 #7) and only `profile_public=True` users. No
  timestamps beyond the credit's own dates (a "2 hours ago" would advertise
  activity patterns). Nothing else about the user renders.
- No caching in the POC (one indexed query); revisit if the home ever needs it.

## 4. Date display

Every rendered credit date range becomes `m/Y` (`08/2024 – 03/2025`;
`present` unchanged): `accounts/profile.html`, `games/game_detail.html`, the
per-credit lines in `search/people_search.html` result cards (currently year
only), the feed, and any declare-funnel recap that shows the pending credit's
dates. Career summary ranges on result cards (`2021–present`) and game release
years stay years — they are years.

Entry keeps the native `<input type="month">`: it localizes to each visitor's
browser and is the best mobile widget. No code change.

## 5. About page

`/about/` (`TemplateView`, name `about`), linked from the footer next to
Terms/Privacy. English copy, four short sections, final wording at
implementation:

- **What this is** — a public credits register for the game industry: workers
  declare what they shipped; anyone can find people by what they actually
  worked on. Explicitly note the layoff waves since 2024 as the reason the
  worker side exists.
- **Where the data comes from** — the games catalog seeds from IGDB and
  Steam-derived data; credits are declared by the people themselves, never
  scraped.
- **Open source** — AGPL v3, link to the GitHub repo, invitation to
  contribute; user data stays private and is not part of the code.
- **Contact & safety** — the relay principle (personal emails never exposed),
  link to the report form.

## 6. English copy pass

The existing strings are close to native already; this is a light touch, not
a rewrite. At implementation, sweep every user-facing string (templates,
forms, `messages`, emails) against two rules — natural US English, and
consistency of the few product nouns (**credit**, **profile**, **discipline**,
"Open to work"). Known items:

- New strings above (banner, feed heading, About copy) land in English from
  the start, through i18n like everything else.
- `Worked since (year)` (search filter) reads as if the *person* must have
  been employed since then; it filters credits overlapping-or-after that year.
  Reword to `Worked on a game since (year)`.
- Keep `Add your credit` as the canonical CTA everywhere (nav, banner,
  profile empty state) rather than the current mix with `Add a credit`.

## Out of scope

- The search query, filters, funnel steps, contact relay: untouched.
- The profile gallery and upload hardening:
  [2026-08-20-profile-gallery-design.md](2026-08-20-profile-gallery-design.md).
- Any custom visual design (fonts, brand colors, illustrations): explicitly
  rejected — Pico's defaults are the design.
- Collapsible mobile filters, saved searches, OG social cards: candidates for
  later specs.

## Docs & tests

- `docs/01-DESIGN.md`: home order, feed, About page, `MM/YYYY` display.
  `docs/03-TECH-STACK.md`: record Pico CSS v2 classless as the implementer's
  CSS choice. `ROADMAP.md`: new entries under the current phase.
- Tests (house TDD): feed shows an active/public credit and **must not** show
  a `pending` credit nor one of a `profile_public=False` user; feed absent
  when a search ran; `/about/` 200 + footer link present; nav CTA target per
  auth state; date rendering `08/2024` on profile and game pages; the
  anonymous banner present, gone when authenticated. Template-diff tests
  (chips, typeahead payload) must keep passing untouched.
