# Filter bento, type hierarchy and a "specific games" facet — design

Date: 2026-08-24 · Surface: the home page (`/`, `search/people_search.html`)
· Supersedes the layout half of `2026-08-21-search-chrome-design.md` §2 (the
two flat filter rows) and the field labels it fixed.

## 1. Why

The filter block is the product's whole recruiter-facing promise, and it reads
today as eight controls of equal weight strung across 72rem. Three problems,
all reported by the owner on 2026-08-24:

1. **No hierarchy.** `theme.css` sets `label`, `legend` and `th` to the same
   `.8rem` monospace bold, so "Games they worked on" is typographically
   indistinguishable from "Engines" — the group names do not group anything.
2. **No boundary.** The form floats on the page with nothing drawn around it,
   and its Search button sits flush against the "Latest credits" feed below.
3. **A missing facet.** A recruiter who already knows the games — "who worked
   on Hades *or* Celeste?" — has no way to ask. The three criteria
   (genre/rating/engine) are an *indirect* way of naming games, and the two
   ways of asking do not compose: adding a genre to a list of named games can
   only ever narrow it into nonsense.

## 2. Layout — the bento

The whole `<form class="filters">` becomes one drawn card. Inside it, two
`<fieldset class="filter-section">` blocks, each with a legend that now
outranks the field labels (§4). The first section splits into two sub-cards
separated by a vertical rule carrying the word `OR`:

```
┌─ The games they've worked on ─────────────────────────────────────┐
│ ┌─────────────────────────────────────┐  │  ┌──────────────────┐  │
│ │ Games matching all of:              │  │  │ Credited on any  │  │
│ │ Game genre  Min. player rating  …   │ OR │ │ of:              │  │
│ └─────────────────────────────────────┘  │  │ Specific games   │  │
│                                          │  └──────────────────┘  │
├─ The person ──────────────────────────────────────────────────────┤
│ Their role   Based in   Credited since (year)   ☐ Open to work    │
└───────────────────────────────────────────────────────────────────┘
```

Decisions taken with the owner against a rendered mockup:

- **The relationship is stated once, as a group heading** — `Games matching
  all of:` and `Credited on any of:` — not as an `and` repeated between every
  pair of fields. An "and" between columns was the first proposal and was
  rejected: it says the same thing three times and collapses badly the moment
  the columns stack.
- **The right sub-card takes its natural height**, not the left one's. Stretched
  to match, a card holding a single field is mostly empty space.
- **Chips stay above their input.** Selecting a genre therefore pushes that
  input below its two row-neighbours. Raised as a defect, examined, and
  deliberately kept: moving chips under the input to keep the input line
  straight would put the selection below the box that produced it.
- **Fields pack left at a readable width** — `repeat(auto-fit, minmax(9rem,
  13.5rem))` with `justify-content: start`, replacing `minmax(13rem, 1fr)`.
  The `1fr` was what stretched four controls across the full column and left
  the ragged gaps the owner flagged.
- **`.filters` carries the bottom margin** that separates Search from "Latest
  credits" (`2.75rem`, was the `<form>`'s default).

## 3. Field order

Row 1 becomes **Genres · Min. rating · Engines** (was Engines · Genres · Min.
rating): genre is the coarsest, most-reached-for facet and belongs first;
engine is the specialist's filter and moves last.

## 4. Type hierarchy

`theme.css` gains one rule: `.filter-section > legend` at `1.05rem` with a
`-.01em` tracking, against the `.8rem` that `label`/`legend`/`th` share. It
must be written at `:root[data-theme=light] .filter-section > legend`
specificity — the existing `:root[data-theme=light] legend` block is (0,2,1)
and outranks any bare class selector regardless of source order.

The group headings (`Games matching all of:`) are `<small class="muted">`.
That is `.85rem` — nominally a hair *larger* than the `.8rem` labels — but
regular weight and dimmed against their bold, so it reads as a note about the
group rather than as another label. It is a note, not the group's name: the
section legend above is the name.

## 5. Copy

The owner picked the descriptive register over an interrogative one.

| Current | New |
|---|---|
| *Games they worked on* (legend) | **The games they've worked on** |
| *About the person* (legend) | **The person** |
| Genres | **Game genre** |
| Min. rating (%) | **Minimum player rating (%)** |
| Engines | **Game engine** |
| — | **Specific games** *(new)* |
| Discipline | **Their role** |
| Countries | **Based in** |
| Worked on a game since (year) | **Credited since (year)** |
| Open to work only | *unchanged* |

New strings: `Games matching all of:`, `Credited on any of:`, `OR`, `Search
games…`, and the exclusion error in §7. All through `gettext` (non-negotiable
#10); the existing `locale/` catalogues gain the new msgids and lose the
renamed ones.

## 6. The `games` facet

A new optional `games` field: a `ModelMultipleChoiceField` over `Game`,
rendered by the same chip typeahead as engines/genres/countries, so it posts
the same repeated `?games=12&games=88` params.

Two traps, both load-bearing:

- **`TypeaheadSelectMultiple._chips()` must not be reused as-is.** It builds
  its label map by iterating `self.choices` — correct for Engine, Genre and
  the 249 countries, fatal for Game: the catalogue is ~391k rows and would be
  materialised on **every render of the home page**. A
  `GameTypeaheadSelectMultiple` subclass overrides `_chips()` to look up only
  the selected ids (`Game.objects.filter(pk__in=ids).values_list("pk",
  "title")`). This keeps the property the base class exists for — a label is
  never derived from the raw value, so an unknown id renders no chip — at a
  cost bounded by the selection.
- **Non-numeric ids must be filtered before the query.** `?games=abc` would
  reach `pk__in=["abc"]` and raise `ValueError` — a 500 on a public page from
  a hand-typed URL. The override drops anything failing `str.isdigit()`
  before it queries.

`recruiter_search()` gains `game_ids: Sequence[int] = ()`, applied in
`_matching_credits()` as `credits.filter(game_id__in=list(game_ids))` — OR
within the facet, AND across facets, exactly like `engine_ids` and
`genre_ids`. Unlike those two it needs no `.distinct()` guard of its own:
`Contribution.game` is a ForeignKey, so an `__in` over it cannot fan a credit
into several joined rows the way the `game__engines` M2M does.

### Autocomplete endpoint

New `search:game_filter_autocomplete` at `filters/games/`, `key="ip"` like the
other three filter endpoints, rendering the shared `_filter_options.html`.

It is deliberately **not** the existing `search:game_autocomplete`: that one
offers the IGDB "deeper search" import, and importing a game nobody is
credited on cannot make this filter match a single person. It would spend an
IGDB call, and the owner's per-IP quota, to add an option guaranteed to return
zero results.

It searches the whole catalogue rather than only games carrying an active
credit. Restricting it would be more flattering but costs a join and a
`DISTINCT` on every keystroke, and it is not what the sibling facets do —
picking an engine nobody used already returns zero results.

## 7. The OR: mutual exclusion

**The rule.** `{genres, min_rating, engines}` and `{games}` are alternatives.
`{discipline, countries, year_from, open_to_work}` — the whole "person"
section — stays available in both modes and is unaffected.

**Server side is the boundary.** `clean()` raises
`Filter either by game criteria or by specific games, not both.` when both
sides are populated. It runs before the existing "Pick at least one filter."
check; the two can never fire together. `games` joins that check's explicit
`any([...])` list — the list is deliberately enumerated, not looped over
`self.fields`, because a loop fails **open** the day a non-filter field is
added.

**Client side is the affordance.** A script on the page keeps exactly one
side live: filling either one disables the other's controls and marks its card
`data-off` (an opacity, no colour). "Filled" means at least one chip, or a
non-empty `min_rating`. When neither or *both* sides are filled — the second
only reachable from a crafted querystring — both stay live and the server's
error is what the visitor sees.

Disabled inputs are not submitted, so this doubles as the mechanism, not just
a hint. It listens on `input`/`change` at the form and runs after every chip
add/remove; the typeahead's own `q` box is a DOM descendant of the form even
though `form="typeahead-scratch"` owns it for submission, so events from it
bubble here as normal.

Switching modes needs no reset control: the *filled* side is always the live
one, so its chips can be removed and its rating cleared. Emptying it returns
both sides to live. The disabled side is only ever the empty one, which is
why nothing is ever locked away behind the state it caused.

No-JS keeps its documented posture (`people_search.html`'s `<noscript>` note):
the typeahead is htmx, so all four chip facets are hidden without JavaScript.
Without the script neither side is ever disabled, and a visitor who somehow
posts both gets the server's error — correct, if blunt.

## 8. Template shape

The per-field markup is currently written twice, and this change would make it
four times. It moves to one `search/_filter_field.html` partial carrying the
`open_to_work` checkbox special case, included from all three places.

`RecruiterSearchForm` exposes `criteria_fields()` → `[genres, min_rating,
engines]` and keeps `person_fields()`. The lone `games` field is rendered
directly through the partial rather than behind a one-element accessor.

## 9. Tests

TDD, failing test first. New or changed:

- `test_recruiter_form.py` — `games` alone satisfies the one-filter rule
  (added to the existing all-fields parametrization, which exists precisely so
  that dropping an entry from `clean()` fails here); multi-select accepts
  several ids; each of genres/min_rating/engines conflicts with `games`;
  person-section fields do **not** conflict with it.
- `test_recruiter_search.py` — `game_ids` ORs across games; composes with a
  person filter; a credit on an unlisted game is excluded.
- `test_filter_autocomplete.py` — the new endpoint returns options and,
  explicitly, **no** IGDB trigger; junk `?q=` returns the empty state.
- `test_filter_rows.py` — renamed legends and labels; row-1 order is genres,
  min_rating, engines; the two sub-cards exist; `.chips:empty` count rises
  from 3 to 4.
- New `test_game_facet_widget.py` — the chip lookup is bounded
  (`assertNumQueries`-style: rendering with two selected games must not scale
  with the catalogue), an unknown id renders no chip, and `?games=abc`
  renders the page instead of raising.

## 10. Out of scope

**The mobile pass**, explicitly deferred by the owner to a follow-up. This
change ships the minimum that keeps small screens working — the split
collapses to one column and the `OR` rule turns horizontal — and nothing more.
The full narrow-viewport review of the new bento is its own task.

Also unchanged: results cards, the feed, the rate limit, and the `.filters`
form's action/method.

## 11. Docs

`docs/01-DESIGN.md` §3.6 (the filter paragraph, which currently describes the
two flat rows and the old labels) and `ROADMAP.md` in the same PR.
