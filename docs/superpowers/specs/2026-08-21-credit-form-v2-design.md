# Credit form v2: employer picker, credit country, MM/YYYY dates — design

> Status: proposed 2026-08-21, decisions validated with the product owner the
> same day. One model change (`Contribution.country`, one migration), one form
> rewrite, shared by `/credits/new/`, credit edit, and the declare funnel's
> details step (they already share `_employer_field.html`).

## Problems

1. After picking a game, the employer block reads "Employer company (optional)"
   with a "Worked for another company?" button: the member has to understand
   two controls to do the common thing (I worked at the studio that made it).
2. A credit has no location: recruiters filter people by country, but a
   career spent in three countries is invisible.
3. The month picker is native: it renders in the *browser's* locale
   ("février 2026"), not the site's `MM/YYYY`.

## Decisions

| Question | Decision |
|---|---|
| Employer | A **select** of the game's companies, **developer preselected**, last option **"Another company…"** revealing the existing search |
| Credit country | New optional `country` on `Contribution`, asked in the form, shown on the credit line |
| Dates | **`MM/YYYY` text inputs** (numeric keypad on mobile), server-validated; both `MM/YYYY` and the legacy `YYYY-MM` accepted on input |

## 1. Employer picker (`_employer_field.html`, `games:game_employers`)

- The htmx endpoint keeps returning the game's companies in role order
  (developer → publisher → porting → support, deduplicated) and now renders a
  `<select id="employer-select">`: one `<option value="<pk>">` per company with
  its role in parentheses — `Supergiant Games (developer)` — the **first
  option selected**, then `<option value="">No employer / freelance</option>`,
  then `<option value="__other">Another company…</option>`.
- On load and on change, three lines of inline JS copy the selected pk into
  the hidden `form.company` input; `__other` reveals the existing company
  search (autocomplete + "create" offer where `offer_company_create`), whose
  pick fills the hidden input as today. Picking a quick option hides the
  search again.
- Label: `Employer`. Before a game is picked: the select is absent and the hint
  reads `Pick a game first.` A game with **no** linked company renders only
  the last two options, with `No employer / freelance` selected.
- Editing a credit: the select preselects the saved company if it is one of
  the options, otherwise shows the saved company's name as a selected extra
  option (so the edit form never silently changes an employer).
- No change to the model; `company` stays optional (`SET NULL`).

## 2. Credit country (`contributions/models.py`, migration)

- `country = CountryField(_("country"), blank=True)` (django-countries, same
  as `User.country`), nullable-by-blank, no default. Migration adds the column.
- Form: `Country` select under the dates, optional; label `Country`, help
  `Where this work happened.` The declare funnel's details step asks it too.
- Display: on the profile credit line and the game page, after the dates:
  `08/2024 – 03/2025 · France` when set. Not in the OG card (the card stays
  the owner's location), not yet a search filter (a natural follow-up —
  "worked in country X" — noted in ROADMAP, out of scope here).
- Export: included in the JSON export's credits; seed write-surface untouched
  (it is a user-owned column, docs/04 §13).

## 3. `MM/YYYY` dates (`contributions/forms.py`)

- `MonthYearField` switches to a `TextInput` with `inputmode="numeric"`,
  `placeholder="MM/YYYY"`, `pattern="[0-9]{2}/[0-9]{4}"`, `autocomplete="off"`;
  `input_formats = ["%m/%Y", "%Y-%m"]`, display format `%m/%Y`.
- Validation messages: `Enter a month as MM/YYYY, e.g. 08/2024.`; the existing
  "end before start" rule stays.
- Both `/credits/new/` and the declare funnel's details step use the field, so
  both change at once; existing tests that post `YYYY-MM` keep passing
  (legacy format accepted); new tests post `08/2024`.

## Out of scope

Country as a recruiter filter; multi-country credits; employer creation flow
changes (the existing "create company" offer stays where it is).

## Docs & tests

`docs/01-DESIGN.md` §3.3 (employer picker, country, date entry), `docs/04`
§8 (new column), ROADMAP. Tests: employer endpoint renders the select with the
developer selected and the two trailing options; a game without companies
defaults to "No employer"; edit form preselects the saved company; country
saved and displayed; `08/2024` accepted, `2024-08` accepted, `13/2024` and
`8/24` rejected with the message; funnel step posts the same fields.
