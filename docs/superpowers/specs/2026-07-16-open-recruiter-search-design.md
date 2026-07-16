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

- **Anti-scraping posture survives** (docs/02-ARCHITECTURE.md §5: no
  exhaustive "all people" listing). A submit with zero filters returns no
  results and shows a "pick at least one filter" form error. The view gets the
  same IP rate limit as the public search page (`SEARCH_RATELIMIT`).
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
| `min_rating` | IntegerField 0–100 | credit's game | unchanged (Steam positive % OR IGDB rating) |
| `year_from` | IntegerField | credit | unchanged (`start_date__year__gte`) |
| `open_to_work` | BooleanField | person | unchanged |

- **OR within a facet, AND across facets, same single credit** for the
  credit-level facets: "(Unreal OR Unity) × (RPG OR Roguelike) ×
  Programming" must all hold on one active contribution. Field help text
  states "any of the selected".
- Checkbox lists render inside a scrollable `<fieldset>` (engines can be a
  long list on the real seed) — plain CSS in the page template, no JS.
- Form submits as GET → shareable URLs (`?engines=3&engines=7&countries=FR`).
- Rename note: `engine`/`genre` request params become `engines`/`genres`.
  No deployed users, no URL back-compat needed.
- `clean()` rule: if every field is empty/False, raise a form-level
  ValidationError ("Pick at least one filter."). `open_to_work=True` alone
  counts as a filter.

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
  exactly 100; display top 3 + "other N%". Example: "Unreal 67% · Unity 33%".
  Omitted entirely when no credited game has engine data.

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
    first_year: int | None
    last_year: int | None                  # None = present (an open end exists)
    engine_shares: list[tuple[str, int]]   # [("Unreal Engine", 67), ...] top 3 + ("other", n)
```

Chosen over annotated querysets because annotations are invisible to `ty`
(the codebase already fights that) and engine repartition needs a grouped
side-query anyway.

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
