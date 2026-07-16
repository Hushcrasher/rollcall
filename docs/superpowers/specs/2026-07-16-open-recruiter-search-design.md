# Open Recruiter Search ("Find people") — Design

**Status:** approved, ready for implementation plan
**Date:** 2026-07-16

## Goal

Turn the gated recruiter search into an **open discovery tool**: anyone —
anonymous visitors included — can filter people by properties of the games
they worked on. Four changes, in one coherent feature:

1. **Open access.** The platform is 100% free for now; gating buys nothing and
   hides the tool from the very workers whose motivation depends on believing
   the recruiter side exists (docs/01-DESIGN.md §3.6 rationale). Opening the
   page makes the promise visible to both sides.
2. **Multi-select engines and genres** in the filters.
3. **Country filter**, backed by a structured worker-side country field
   (predefined ISO list, no more free-text-only location).
4. **Richer result cards**: why the person matched + factual career summary.

This supersedes the "gated to recruiters" behavior in docs/01-DESIGN.md §3.6;
that doc (source of truth) is updated as part of this work.

## Non-negotiables that shape this design

- **Anti-scraping mitigations** (docs/02-ARCHITECTURE.md §5: no exhaustive
  "all people" listing — and note §5 already concedes *"public pages can't be
  fully protected — accept and mitigate"*). Two distinct things, deliberately
  not conflated:
  - The **IP rate limit** (`SEARCH_RATELIMIT`, same as the public search page)
    plus pagination and `profile_public` are the **actual** mitigation.
  - The **≥1-filter form rule** is a **UX guard**, not a security boundary: it
    stops the accidental/lazy filterless submit. It **cannot** stop a
    determined enumerator, and we do not claim it does. Verified during Task
    5's review: `?min_rating=0` and `?year_from=1970` both pass the rule and
    return the *full* listing. That is not a bug to patch — any range filter
    at its extreme is a no-op, `?min_rating=1` is equally wide, and there is
    no principled line between "no-op" and "merely broad". Chasing one would
    be whack-a-mole against an undefinable boundary.

  Do not write a docstring, comment, or doc claiming the filter rule prevents
  enumeration. It doesn't. The rate limit is the answer to that question.
- **Emails never rendered** — unchanged; contact stays relay-only.
- **No numeric public score of the person.** Career stats and engine
  repartition are factual descriptions of credited games, not a rating of the
  person. Game ratings remain a *filter*, never a sort or a displayed score on
  people; ordering stays `display_name`.
- **Private profiles invisible everywhere** — `profile_public=True` filter
  stays first in the query.
- **Same-credit rule preserved**: all credit-level filters must hold on one
  single active contribution.

## 1. Open access

- `RecruiterSearchView` loses `RecruiterRequiredMixin`; the mixin is deleted
  (dead code once unused). Route stays `/search/recruiters/`.
- Add `@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET",
  block=True), name="get")` — same shape as `SearchView`.
- **Recruiter application flow goes dormant, not deleted:**
  `RecruiterApplication`, the apply form/view/admin approval all stay working
  (cheap to re-arm if paid recruiter accounts return). The
  `User.Role.RECRUITER` role keeps existing; nothing reads it for access
  anymore.
- **"For recruiters" landing page** (`recruiters_landing.html`): primary CTA
  becomes "Search people now" → the search page. The apply link stays as a
  low-key secondary mention ("Want to introduce yourself as a recruiter?
  Apply for a recruiter account."). Honest-counts section unchanged.
- Footer "For recruiters" link stays — that is how workers discover the tool.

## 2. Filters

`RecruiterSearchForm` (all fields optional, but **at least one required** via
`clean()`):

| Field | Type | Applies to | Semantics |
|---|---|---|---|
| `discipline` | ModelChoiceField (single) | credit | unchanged |
| `engines` | ModelMultipleChoiceField, checkbox list | credit's game | game has **any** of the selected |
| `genres` | ModelMultipleChoiceField, checkbox list | credit's game | game has **any** of the selected |
| `countries` | MultipleChoiceField over django-countries, checkbox list | **person** | person's country is any of the selected |
| `min_rating` | IntegerField **1**–100 | credit's game | Steam positive % OR IGDB rating. **1, not 0**: `0` reads as "I don't care about rating" but behaves as "must *have* rating data" — silently dropping people whose games carry neither score. Leaving the field blank is how you say "I don't care". Side effect: every valid value is truthy. |
| `year_from` | IntegerField | credit | unchanged (`start_date__year__gte`) |
| `open_to_work` | BooleanField | person | unchanged |

- **OR within a facet, AND across facets, same single credit** for the
  credit-level facets: "(Unreal OR Unity) × (RPG OR Roguelike) ×
  Programming" must all hold on one active contribution. Field help text
  states "any of the selected".
- **Engines, genres and countries use an htmx typeahead** — type a few letters,
  pick from a dropdown, chosen values show as removable chips; the form posts
  the same repeated `?engines=3&engines=7` params either way, so the service
  and tests are unaffected.

  > **Amended after Task 7's review (product owner decision).** The original
  > spec said "checkbox lists render inside a scrollable `<fieldset>`". That was
  > wrong, and not merely at scale: countries are **249 today, in dev, forever**
  > — measured at **34,908 bytes and 249 `<input>`s on every anonymous hit** of
  > the empty form, with no type-ahead, no filter, and no keyboard jump. A
  > `<legend>` is also the accessible name for every control in its fieldset, so
  > a screen reader re-announces the help text 249 times. The codebase already
  > has the right pattern — `search:game_autocomplete`, `search:company_autocomplete`,
  > `_suggest.html` — htmx, no build step, established.
- Form submits as GET → shareable URLs (`?engines=3&engines=7&countries=FR`).
- Rename note: `engine`/`genre` request params become `engines`/`genres`.
  No deployed users, no URL back-compat needed.
- `clean()` rule: if every field is empty/False, raise a form-level
  ValidationError ("Pick at least one filter."). `open_to_work=True` alone
  counts as a filter. This is the UX guard described in the non-negotiables —
  **not** a security boundary; don't document it as one.
  - The check enumerates every field **explicitly**. Keep it that way: a
    generic loop over `self.fields` fails **open** the moment a non-filter
    field is added (a `sort` field would make `?sort=name` alone "a filter"),
    whereas a forgotten field in the explicit list fails **closed** — merely
    annoying. For a security-adjacent rule, prefer the failure that locks over
    the one that leaks. A parametrized test pins every field individually.
- The country choice list must be passed as a **callable**, not the
  `django_countries.countries` iterable directly. Django's `normalize_choices`
  matches `Iterable` before `callable`, and `Countries` is both — so passing
  it directly materialises the *translated* names once, at import, freezing
  every country in `LANGUAGE_CODE` forever (verified: with `fr` active, the
  field still renders "Germany", not "Allemagne"). A non-iterable callable
  yields a `CallableChoiceIterator` that re-evaluates per access.

## 3. Country on the worker side

- New dependency: **django-countries** (added via uv). If its typing is
  opaque to `ty`, use the same small Any-bridge accommodations the codebase
  already uses for Django descriptors.
- `User.country = CountryField(_("country"), blank=True, default="")` —
  ISO 3166-1 codes, translated names for free.
- Existing `location` CharField is **kept**, relabelled **"City / region"**
  (verbose name + settings-form label). No parsing of existing free text into
  countries: nothing is deployed, and dev fixtures are regenerated.
- Profile page displays "City · Country" (either part optional). The join lives
  in ONE place — a `User.location_display` property — because the search result
  cards (§4) render the same line; the separator is translatable (`pgettext`),
  since a locale may prefer a comma.
- `SettingsForm` gains `country`; `load_dev_fixtures` assigns deterministic
  countries to fake profiles; GDPR export (`accounts/export.py`) gains
  `country` in the identity block.
- docs/04-DATABASE-SCHEMA.md §1 updated with the field.

## 4. Results

### Card content

Per person:

- Display name (profile link) · open-to-work badge · relay contact link
  (existing behavior).
- **Location**: `user.location_display` — "City · Country" (whichever parts
  exist), the same property the profile page uses.
- **Matching credits — the "why"** (up to 3, then "+N more"): game title
  (linked) — job title (discipline), start–end dates. These are exactly the
  active credits that satisfied the credit-level filters.
- **Career stats** over *all* the person's active credits (career summary,
  deliberately not filter-scoped): total credits · distinct games · years
  active ("2015 – present" using min start / max end, open end = present).
- **Engine repartition %** across the person's distinct credited games that
  carry engine data: computed over distinct (game, engine) pairs; integer
  percentages with largest-remainder rounding so displayed shares sum to
  exactly 100; display top 3 + "other N%". Omitted entirely when no credited
  game has engine data. **Must be rendered with a label** — "Engines on
  credited games: Unreal 67% · Unity 33%". Unlabelled, sitting directly under
  a career-stats line, "Unreal Engine 100%" reads as a proficiency score —
  exactly the inference the "no numeric public score of a person"
  non-negotiable exists to prevent. The label is what keeps it factual, and
  it costs one string. The "other" bucket must be translatable.

Never shown: email, any person-level score.

### Service shape

`recruiter_search()` in `search/services.py` stays the only place search
logic lives, and now returns **assembled, typed results** instead of a bare
`QuerySet[User]`:

```python
@dataclass(frozen=True)
class PersonResult:
    user: User
    matching_credits: list[Contribution]   # capped at 3
    matching_credits_total: int
    credits_count: int                     # all active credits
    games_count: int                       # distinct games
    first_year: int                        # never None: a result has >=1 active
                                           # credit and start_date is NOT NULL
    last_year: int | None                  # None = present (an open end exists)
    engine_shares: list[tuple[str, int]]   # [("Unreal Engine", 67), ...] top 3 + ("other", n)
```

Chosen over annotated querysets because *queryset* annotations are invisible
to `ty` (the codebase already fights that), and engine repartition needs a
grouped side-query anyway.

`ResultsPage` is hand-rolled rather than exposing Django's `Page` because
`Page.object_list` is `list[User]` while the service returns
`list[PersonResult]` — `Page` cannot carry that without lying, and a frozen
dataclass keeps Django types out of the service's public signature. Note this
is **not** a `ty` limitation: `Paginator`/`Page` are plain classes and `ty`
resolves their methods fine. (An earlier draft claimed otherwise; corrected
after Task 6's review, since a wrong rationale gets cited for things it
doesn't cover.)

`previous_page_number`/`next_page_number` return `int | None`, not a bare
`page_number ± 1`: `get_page(0)` clamps to the **last** page, so an unguarded
"Previous" link on page 1 would jump the user to the end. `page` is typed
`int | str | None` and passed the raw GET value — `get_page()` coerces junk to
page 1, whereas an `int()` in the view would 500 on `?page=abc`.

Query plan (bounded by page size):

1. Build the filtered credits queryset exactly as today (multi-value filters
   use `__in`), get distinct matching `user_id`s, order users by
   `display_name`, **paginate the user ids** (20/page, Django `Paginator`).
2. For the page's users only: fetch matching credits
   (`select_related("game", "discipline")`), all-active-credit aggregates
   (one grouped query), and engine pairs (one `values_list(user_id,
   game_id, engine name).distinct()` query). Assemble `PersonResult`s in
   Python.

The view passes the paginator page + results to the template; pagination
links preserve all GET params except `page`.

### Files touched

| File | Change |
|---|---|
| `search/forms.py` | multi fields, countries, `clean()` ≥1-filter rule |
| `search/services.py` | `PersonResult`, multi-value + country params, assembly |
| `search/views.py` | drop mixin (delete it), rate limit, pagination wiring |
| `templates/search/recruiter_search.html` | scrollable checkbox fieldsets, result cards, pagination |
| `templates/search/recruiters_landing.html` | CTA to search, apply de-emphasized |
| `accounts/models.py` | `country` field, `location` relabel (+ migration) |
| `accounts/forms.py` | `country` on `SettingsForm` |
| `accounts/export.py` | `country` in identity |
| `templates/accounts/profile.html` | renders `user.location_display` |
| `games/management/commands/load_dev_fixtures.py` | deterministic countries |
| `pyproject.toml` | django-countries |
| `docs/01-DESIGN.md` §3.6, `docs/04-DATABASE-SCHEMA.md` §1, `ROADMAP.md` | record the behavior change |

## Testing (TDD)

- **Access**: anonymous GET → 200 with form; member GET → 200 (no redirect to
  apply); zero-filter submit → form error, no results, no user enumeration;
  rate limit returns 403 when exceeded (same focused-test pattern as search).
- **Query**: OR within engines (Unreal-only person + Unity-only person both
  match `engines=[unreal, unity]`); same for genres; AND across facets still
  requires a single credit satisfying all (the existing cross-credit
  regression test extended to multi values); country filter matches
  person-level; private profiles never surface; only `status='active'`
  credits count; `open_to_work` unchanged.
- **Cards / service**: matching credits are exactly the filter-satisfying
  ones, capped at 3 with correct total; career stats math (counts, distinct
  games, min/max years, open end → present); engine shares sum to 100, top-3
  + other, absent when no engine data; ordering by display_name; pagination
  page size + param preservation.
- **Accounts**: settings form saves country; profile renders "City · Country"
  via `location_display` (all four combinations, incl. an invalid stored code);
  export contains country; fixtures stay deterministic/idempotent.

## Out of scope

Multi-select discipline (trivial to add later, same pattern) · city-level
filtering · parsing legacy free-text locations · removing the recruiter
role/application models · ranking/relevance ordering · avatar/bio on cards
(deliberately left out per product owner's card-content selection).
