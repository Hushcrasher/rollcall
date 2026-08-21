# Search chrome: stacked wordmark, two-row filters, Message button — design

> Status: proposed 2026-08-21, decisions validated with the product owner the
> same day. Presentation only — no model, no migration. Touches `base.html`,
> `search/people_search.html`, `accounts/profile.html`, `static/css/app.css`,
> and the OG card renderer's wordmark.

## Decisions

| Question | Decision |
|---|---|
| Wordmark | **ROLL over CALL**, stacked, **monospace** so both lines are the same width — in the nav (system monospace stack) **and** on the OG cards (a vendored mono font) |
| Filter layout | **Two rows**: the game row and the person row; every filter visible without scrolling on a laptop screen |
| Banner | `Worked on a game? Add your credit` — the trailing "— no account needed to start." goes |
| Contact | The `Contact` link becomes a **`Message` button** (profile + search cards) |

## 1. Wordmark

- Nav (`base.html`): `<a href="{% url 'home' %}"><strong class="wordmark">ROLL<br>CALL</strong></a>`.
  `app.css`: `.wordmark { font-family: ui-monospace, SFMono-Regular, Menlo,
  Consolas, "Liberation Mono", monospace; display: inline-block; line-height: .95;
  letter-spacing: .04em; }` — a font-family rule is an aesthetic choice; it is
  here because the owner asked for exactly this on 2026-08-21 (comment says so).
  The two words have four glyphs each, so a monospace face makes them the same
  width by construction; no sizing trick needed. Colour stays Pico's link
  colour (unchanged).
- OG cards (`cards/render.py`): the top-left wordmark becomes two lines
  `ROLL` / `CALL` at 36 px in **JetBrains Mono Bold** (SIL OFL 1.1), vendored
  as `cards/fonts/JetBrainsMono-Bold.ttf` with its licence text. Everything else
  in the card keeps Inter. The text block still centres vertically; the
  spec's §2 table of 2026-08-21-open-graph-cards gets a one-line amendment.
- The existing nav tests assert `ROLLCALL` in the header — they change to
  assert the two lines (`ROLL` and `CALL` inside `.wordmark`).

## 2. Filters in two rows (`people_search.html`)

Two `<fieldset>`s with `<legend>`s, laid out by one functional grid rule:

| Row (legend) | Fields, left → right |
|---|---|
| **Games they worked on** | Engines · Genres · Min. rating (%) |
| **About the person** | Discipline · Countries · Worked on a game since (year) · Open to work only |

- `app.css`: `.filter-row { display: grid; grid-template-columns:
  repeat(auto-fit, minmax(13rem, 1fr)); gap: 0 1rem; align-items: start; }` —
  four columns on a laptop, two on a tablet, one on a phone (the mobile
  "filters first" posture is unchanged; the no-scroll goal is for desktop).
- Vertical space: the two data caveats (genre and rating data cover
  Steam-linked games only) leave the field help texts and become **one
  footnote line** under the rows (`<small>`); the two "Matches … any of the
  selected" help texts go — the chips make it obvious. Labels stay above
  their inputs; the Search button sits under the second row, left-aligned.
- Nothing changes in `search/forms.py` except the removed help texts; the
  `>= 1 filter` rule, typeahead widgets and chips are untouched.

## 3. Banner copy

`Worked on a game? Add your credit` (link unchanged). The `games/tests/test_home.py`
pitch assertion (`PITCH = b"Worked on a game?"`) keeps passing.

## 4. `Message` button

- `accounts/profile.html` (visitor, `contactable`): `<a role="button" href="{% url 'contact:contact' … %}">{% translate "Message" %}</a>`.
  In preview mode the muted placeholder says `Message` too.
- `search/people_search.html` result cards: the `— Contact` link becomes a
  `Message` button (`role="button"`), rendered solid — it is the card's one
  action, so it may carry the weight the nav CTA carries on the bar.
- `contact/contact_form.html` title stays "Contact {name}" (it is the form).
- Tests asserting `Contact` links switch to `Message`.

## Out of scope

Mobile filter collapsing; any colour/typography change beyond the wordmark
family; renaming the relay.

## Docs & tests

`docs/01-DESIGN.md` §3.6 (filter rows, button label), `docs/03` (JetBrains Mono
vendored), ROADMAP entry. Tests: wordmark lines in header; both legends
present and every filter field inside the right fieldset; banner text; `Message`
on profile and cards; card render still 1200×630 and centred.
