# Filter Bento and Specific-Games Facet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the home page's flat filter row into a drawn bento with a real type hierarchy, and add a "specific games" facet that is the mutually-exclusive alternative to the genre/rating/engine criteria.

**Architecture:** Backend first (service facet → autocomplete endpoint → form field → exclusion rule), then presentation (template restructure → copy → CSS → JS), then docs and a browser pass against the real 391k-game catalogue. Every backend task leaves the app working and tested; the new field is added to the form before it is rendered, so no task ships a half-drawn page.

**Tech Stack:** Django 6.0, Postgres 16 (pg_trgm), htmx, Pico CSS v2 classless, pytest, uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-24-filter-bento-and-game-facet-design.md`
**Branch:** `feat/filter-bento` (already created; the spec is already committed on it)

## Global Constraints

- **Never commit to `main`.** All work stays on `feat/filter-bento`; commits are DCO-signed (`git commit -s`). CI rejects unsigned PR commits.
- **Every user-facing string goes through i18n** — `gettext_lazy as _` in Python, `{% translate %}` in templates, including any inline-JS text. `locale/` holds no `.po` catalogue yet, so nothing needs re-extracting; the requirement is that the strings are wrapped.
- **Search logic lives ONLY in `search/services.py`.** No querysets that filter people or credits anywhere else.
- **`app.css` is layout-only** — positioning, flex/grid, widths, spacing. No colours, fonts, radii or shadows of its own; a border may use a Pico variable (`var(--pico-muted-border-color)`), which is the existing precedent set by `.chip` and `.notice`. Font sizes go in `theme.css`.
- **`theme.css` is the one aesthetic stylesheet.** Its `:root[data-theme=light] legend` block is specificity (0,2,1) — any new rule targeting a legend must match or beat it.
- **TDD**: write the failing test, run it, watch it fail for the right reason, then implement. `search/tests/test_recruiter_search.py` is a non-negotiable test zone (docs/02 §7).
- **Comment style**: comments state constraints and reasons ("why"), never narrate the next line.
- **Full toolchain must pass** before each commit:
  ```bash
  uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
  ```
  Postgres must be up first: `docker compose up -d db`.
- **`ty` has no Django plugin.** Reuse the existing accommodations (`# ty: ignore[...]`, `Any` bridges) rather than inventing new patterns.
- **Copy is fixed by the spec §5** — do not improvise labels.

---

### Task 1: The `game_ids` facet in `recruiter_search`

**Files:**
- Modify: `search/services.py:172-242` (`recruiter_search`, `_matching_credits`)
- Test: `search/tests/test_recruiter_search.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `recruiter_search(*, ..., game_ids: Sequence[int] = (), ...) -> ResultsPage` and the matching keyword on the private `_matching_credits`. Task 3's view wiring calls it as `game_ids=[game.pk for game in cleaned.get("games") or []]`.

- [ ] **Step 1: Write the failing tests**

Append to `search/tests/test_recruiter_search.py`, in the `# ---- filters` section (the file already defines `_make_person`, `_credit`, `_users` and the `disciplines` fixture — reuse them, do not redefine):

```python
def test_filters_by_specific_games(disciplines: dict[str, Discipline]) -> None:
    """OR within the facet, like engines and genres: credited on EITHER named
    game is a match. Names are chosen so display_name order is deterministic —
    results are ordered by display_name, never by rating."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    celeste = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    unlisted = Game.objects.create(title="Unlisted", source=Game.Source.MANUAL)

    on_hades = _make_person("h@example.com", "A Hades Dev")
    _credit(on_hades, hades, disciplines["Programming"])
    on_celeste = _make_person("c@example.com", "B Celeste Dev")
    _credit(on_celeste, celeste, disciplines["Art"])
    elsewhere = _make_person("u@example.com", "C Unlisted Dev")
    _credit(elsewhere, unlisted, disciplines["Art"])

    assert _users(game_ids=[hades.pk, celeste.pk]) == [on_hades, on_celeste]


def test_specific_games_cross_with_person_filters(disciplines: dict[str, Discipline]) -> None:
    """AND across facets: the person section stays available alongside the
    games facet (spec 2026-08-24 §7)."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    in_france = _make_person("f@example.com", "A In France", country="FR")
    _credit(in_france, hades, disciplines["Art"])
    in_sweden = _make_person("s@example.com", "B In Sweden", country="SE")
    _credit(in_sweden, hades, disciplines["Art"])

    assert _users(game_ids=[hades.pk], countries=["FR"]) == [in_france]


def test_two_credits_on_one_listed_game_yield_one_result(
    disciplines: dict[str, Discipline],
) -> None:
    """Contribution.game is a ForeignKey, so an __in over it cannot fan a credit
    into several joined rows the way the game__engines M2M does — this pins that
    no distinct() guard is needed here."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "One Person")
    _credit(person, hades, disciplines["Art"])
    _credit(person, hades, disciplines["Programming"])

    page = recruiter_search(game_ids=[hades.pk])

    assert page.total == 1
    assert len(page.results[0].matching_credits) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose up -d db && uv run pytest search/tests/test_recruiter_search.py -k specific_games -v
```

Expected: FAIL — `TypeError: recruiter_search() got an unexpected keyword argument 'game_ids'`.

- [ ] **Step 3: Add the parameter to `recruiter_search`**

In `search/services.py`, add `game_ids` to the signature immediately after `genre_ids` (keeping the facets grouped) and pass it through:

```python
def recruiter_search(
    *,
    discipline_id: int | None = None,
    engine_ids: Sequence[int] = (),
    genre_ids: Sequence[int] = (),
    game_ids: Sequence[int] = (),
    countries: Sequence[str] = (),
    min_rating: float | None = None,
    open_to_work: bool | None = None,
    year_from: int | None = None,
    page: int | str | None = 1,  # raw GET value: get_page() coerces junk to 1
) -> ResultsPage:
```

and in the `_matching_credits(...)` call inside it:

```python
    credits = _matching_credits(
        discipline_id=discipline_id,
        engine_ids=engine_ids,
        genre_ids=genre_ids,
        game_ids=game_ids,
        countries=countries,
        min_rating=min_rating,
        open_to_work=open_to_work,
        year_from=year_from,
    )
```

Extend the docstring's facet sentence — replace:

```
    ("Unreal × Programming" means one credit is both); multi-value facets are
    OR within the facet, AND across facets; `countries` filters the person.
```

with:

```
    ("Unreal × Programming" means one credit is both); multi-value facets are
    OR within the facet, AND across facets; `countries` filters the person.
    `game_ids` names games outright and is the recruiter-facing alternative to
    engine/genre/rating rather than a companion to them — the form refuses both
    at once (search/forms.py), but nothing here depends on that.
```

- [ ] **Step 4: Apply the filter in `_matching_credits`**

Add `game_ids: Sequence[int],` to the signature after `genre_ids`, and the filter after the `genre_ids` block:

```python
    if game_ids:
        # A ForeignKey, unlike game__engines / game__genres above: an __in over
        # it matches at most one row per credit, so this needs no distinct()
        # guard of its own.
        credits = credits.filter(game_id__in=list(game_ids))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest search/tests/test_recruiter_search.py -v
```

Expected: PASS, whole file green (the existing tests call `recruiter_search` by keyword and are unaffected by a new defaulted parameter).

- [ ] **Step 6: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add search/services.py search/tests/test_recruiter_search.py
git commit -s -m "feat(search): filter people by specific games

A recruiter who already knows the games has no way to ask "who worked on Hades
or Celeste?" — the genre/rating/engine criteria are only an indirect way of
naming games. recruiter_search gains game_ids: OR within the facet, AND across
facets, exactly like engine_ids and genre_ids.

Unlike those two it needs no distinct() guard: Contribution.game is a
ForeignKey, so an __in over it cannot fan one credit into several joined rows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The `filters/games/` autocomplete endpoint

**Files:**
- Modify: `search/views.py` (add view at the end of the `--- Recruiter-filter typeahead ---` section), `search/urls.py`
- Test: `search/tests/test_filter_autocomplete.py`

**Interfaces:**
- Consumes: `search.services.search_games` (already imported in `search/views.py`), `_FILTER_OPTIONS_SHOWN` (already defined at `search/views.py:211`).
- Produces: URL name `search:game_filter_autocomplete` at path `filters/games/`, rendering `search/_filter_options.html` with `options: list[tuple[int, str]]`. Task 3's widget passes this name to `GameTypeaheadSelectMultiple(url_name=...)`.

- [ ] **Step 1: Write the failing tests**

Append to the `# --- The endpoints ---` section of `search/tests/test_filter_autocomplete.py`. Add `Game` to the existing `from games.models import Engine, Genre` import:

```python
def test_game_filter_autocomplete_returns_matching_options(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "hade"})

    assert response.status_code == 200
    assert b"Hades" in response.content
    assert b"Celeste" not in response.content


def test_game_filter_option_carries_the_pk(client: Client) -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "hades"})
    assert f'data-id="{hades.pk}"'.encode() in response.content


def test_game_filter_autocomplete_offers_no_deeper_search(client: Client) -> None:
    """Deliberately NOT search:game_autocomplete, which offers the IGDB import:
    importing a game nobody is credited on cannot make this filter match a
    single person, and it would spend an IGDB call and the owner's per-IP quota
    to add an option guaranteed to return zero results (spec 2026-08-24 §6)."""
    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "nothing here"})

    assert response.status_code == 200
    assert b"igdb-trigger" not in response.content
    assert b"deeper search" not in response.content


def test_game_filter_autocomplete_blank_query_is_empty(client: Client) -> None:
    Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    response = client.get(reverse("search:game_filter_autocomplete"), {"q": "   "})

    assert response.status_code == 200
    assert b"autocomplete-option" not in response.content
```

Then add `"search:game_filter_autocomplete"` to the `url_name` list of the existing `test_filter_autocomplete_is_rate_limited` parametrize block, so it reads:

```python
@pytest.mark.parametrize(
    "url_name",
    [
        "search:engine_autocomplete",
        "search:genre_autocomplete",
        "search:country_autocomplete",
        "search:game_filter_autocomplete",
    ],
)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest search/tests/test_filter_autocomplete.py -k game_filter -v
```

Expected: FAIL — `NoReverseMatch: Reverse for 'game_filter_autocomplete' not found`.

- [ ] **Step 3: Add the view**

At the end of `search/views.py`, after `country_autocomplete`:

```python
@ratelimit(key="ip", rate=_search_rate, method="GET", block=True)
def game_filter_autocomplete(request: HttpRequest) -> HttpResponse:
    """The recruiter filter's game picker.

    Deliberately not `game_autocomplete` above: that one offers the IGDB
    "deeper search" import, and importing a game nobody is credited on cannot
    make this filter match a single person — it would spend an IGDB call, and
    the operator's per-IP quota, on an option guaranteed to return nothing.

    It searches the whole catalogue rather than only games carrying an active
    credit: restricting it would cost a join and a DISTINCT on every keystroke,
    and it is not what the sibling facets do — picking an engine nobody used
    already returns zero results.
    """
    games = search_games(request.GET.get("q", ""), limit=_FILTER_OPTIONS_SHOWN)
    options: list[tuple[Any, str]] = [(game.pk, game.title) for game in games]
    return render(request, "search/_filter_options.html", {"options": options})
```

- [ ] **Step 4: Add the URL**

In `search/urls.py`, after the countries line:

```python
    path("filters/games/", views.game_filter_autocomplete, name="game_filter_autocomplete"),
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest search/tests/test_filter_autocomplete.py -v
```

Expected: PASS.

- [ ] **Step 6: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 7: Commit**

```bash
git add search/views.py search/urls.py search/tests/test_filter_autocomplete.py
git commit -s -m "feat(search): a game typeahead endpoint for the recruiter filter

filters/games/ mirrors the engine/genre/country filter endpoints — same per-IP
limit, same shared _filter_options.html — rather than reusing the credit form's
game_autocomplete, which offers the IGDB deeper search. Importing a game nobody
is credited on cannot make a filter match anyone; it would spend an IGDB call
and the operator's per-IP quota on an option guaranteed to return zero results.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The `games` form field, its widget, and the view wiring

**Files:**
- Modify: `search/forms.py` (add `GameTypeaheadSelectMultiple` after `TypeaheadSelectMultiple`, the `games` field, and the `clean()` filter list), `search/views.py:103-114` (`recruiter_search` call)
- Create: `search/tests/test_game_facet_widget.py`
- Test: `search/tests/test_recruiter_form.py`, `search/tests/test_people_search_view.py`

**Interfaces:**
- Consumes: `search:game_filter_autocomplete` (Task 2), `recruiter_search(game_ids=...)` (Task 1).
- Produces: `RecruiterSearchForm.games` (a `ModelMultipleChoiceField` over `Game`, `required=False`) and `GameTypeaheadSelectMultiple`. Task 5 renders `form.games` through the field partial.

- [ ] **Step 1: Write the failing widget tests**

Create `search/tests/test_game_facet_widget.py`:

```python
"""The `games` facet's chip widget.

The base TypeaheadSelectMultiple builds its label map by iterating
`self.choices` — correct for Engine, Genre and the 249 countries, ruinous for
Game: the catalogue is ~391k rows and would be materialised on every render of
the home page. These tests pin the targeted lookup that replaces it, and the
querystring shapes that must not reach the database as-is.
"""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from games.models import Game
from search.forms import RecruiterSearchForm

pytestmark = pytest.mark.django_db


def _home(client: Client, query: str) -> str:
    return client.get(reverse("home") + query).content.decode()


def test_selected_games_render_as_chips(client: Client) -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    rendered = str(RecruiterSearchForm({"games": [str(hades.pk)]})["games"])

    assert f'<input type="hidden" name="games" value="{hades.pk}">' in rendered
    assert "Hades" in rendered


def test_game_chips_are_ordered_as_given() -> None:
    """Querystring order, not the queryset's: the recruiter's own order is the
    only order the page can honestly claim."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    celeste = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    rendered = str(RecruiterSearchForm({"games": [str(celeste.pk), str(hades.pk)]})["games"])

    assert rendered.index("Celeste") < rendered.index("Hades")


def test_unknown_game_id_renders_no_chip() -> None:
    """Same property the base class exists for: a label is never derived from
    the raw value, so a stale or invented id renders nothing at all."""
    rendered = str(RecruiterSearchForm({"games": ["424242"]})["games"])

    assert 'value="424242"' not in rendered


@pytest.mark.parametrize("junk", ["abc", "1;DROP", "-1", "²", "99999999999999999999"])
def test_junk_game_id_does_not_break_the_public_page(client: Client, junk: str) -> None:
    """`?games=abc` reaching pk__in as a string raises ValueError — a 500 on a
    public page from a hand-typed URL.

    The out-of-range value is here to pin the surprise rather than a fix:
    Postgres promotes the literal instead of overflowing, so `id IN (10^20)`
    simply matches nothing. Measured against the existing `engines` facet
    before this branch — all five shapes already returned 200 there."""
    response = client.get(reverse("home"), {"games": junk})

    assert response.status_code == 200


def test_chip_lookup_does_not_scale_with_the_catalogue(
    client: Client, django_assert_num_queries: Any
) -> None:
    """The regression this widget exists for. Two selected games must cost the
    same number of queries whether the catalogue holds 3 games or 391k — pinned
    by query count, so any rewrite that re-iterates self.choices fails here
    however it spells it."""
    picked = [Game.objects.create(title=f"Picked {n}", source=Game.Source.MANUAL) for n in range(2)]
    for n in range(20):
        Game.objects.create(title=f"Noise {n}", source=Game.Source.MANUAL)

    query = f"?games={picked[0].pk}&games={picked[1].pk}"
    with django_assert_num_queries(1):
        RecruiterSearchForm({"games": [str(g.pk) for g in picked]})["games"].as_widget()

    content = _home(client, query)
    assert "Picked 0" in content and "Picked 1" in content
    assert "Noise 0" not in content
```

- [ ] **Step 2: Write the failing form tests**

In `search/tests/test_recruiter_form.py`, add `Game` to the `from games.models import Engine, Genre` import, then add `{"games": [str(game.pk)]}` to `test_each_filter_alone_satisfies_the_rule`. Replace that test's body so it creates the game and covers all eight fields:

```python
def test_each_filter_alone_satisfies_the_rule() -> None:
    """Every field must count as a filter on its own. Parametrized in spirit
    over all 8 — dropping any one from clean()'s any([...]) must fail HERE.
    (Task 5's review mutation-tested this: with only the plan's original
    tests, 4 of the 7 entries could be deleted with the suite still green.)"""
    engine = Engine.objects.create(name="Unreal Engine")
    genre = Genre.objects.create(name="RPG")
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")
    for data in (
        {"discipline": str(discipline.pk)},
        {"engines": [str(engine.pk)]},
        {"genres": [str(genre.pk)]},
        {"games": [str(game.pk)]},
        {"countries": ["FR"]},
        {"min_rating": "70"},
        {"year_from": "2015"},
        {"open_to_work": "on"},
    ):
        assert RecruiterSearchForm(data).is_valid(), f"{data} should be enough"
```

and add:

```python
def test_games_is_multi_select() -> None:
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    celeste = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)

    form = RecruiterSearchForm({"games": [str(hades.pk), str(celeste.pk)]})

    assert form.is_valid()
    assert set(form.cleaned_data["games"]) == {hades, celeste}
```

- [ ] **Step 3: Write the failing end-to-end view test**

Append to `search/tests/test_people_search_view.py`. Its `_candidate()` helper hardcodes `candidate@example.com`, so it cannot build the two people this test needs — construct them directly, as below. Every import used here (`date`, `User`, `Contribution`, `Discipline`, `Game`, `Client`, `reverse`) is already at the top of that file:

```python
def test_games_facet_filters_the_page(client: Client) -> None:
    """?games=<pk> is a real search: it binds the form, replaces the feed, and
    returns only people credited on that game."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    other = Game.objects.create(title="Other", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")
    on_hades = User.objects.create_user(
        email="h@example.com", password="x", display_name="Hades Dev"
    )
    Contribution.objects.create(
        user=on_hades, game=hades, discipline=discipline, job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    elsewhere = User.objects.create_user(
        email="o@example.com", password="x", display_name="Other Dev"
    )
    Contribution.objects.create(
        user=elsewhere, game=other, discipline=discipline, job_title="Dev",
        start_date=date(2020, 1, 1),
    )

    content = client.get(reverse("home"), {"games": str(hades.pk)}).content.decode()

    assert "Hades Dev" in content
    assert "Other Dev" not in content
    assert "Latest credits" not in content
```

- [ ] **Step 4: Run to verify they fail**

```bash
uv run pytest search/tests/test_game_facet_widget.py search/tests/test_recruiter_form.py -v
```

Expected: FAIL — `KeyError: 'games'` / `"games" is not one of the available choices`.

- [ ] **Step 5: Add the widget subclass**

In `search/forms.py`, change the games import to `from games.models import Engine, Game, Genre`, then add after `TypeaheadSelectMultiple`:

```python
class GameTypeaheadSelectMultiple(TypeaheadSelectMultiple):
    """Chip labels from a targeted query instead of from `self.choices`.

    `TypeaheadSelectMultiple._chips()` builds a {value: label} map by iterating
    every choice — fine for Engine, Genre and the 249 countries, ruinous for
    Game: the catalogue is ~391k rows and would be materialised on every render
    of the home page. Looking up only the selected ids keeps the property the
    base class exists for — a label is never derived from the raw value, so an
    unknown id renders no chip — at a cost bounded by the selection.
    """

    def _chips(self, value: Any) -> list[tuple[str, Any]]:
        # Filtered BEFORE the query, not after: `?games=abc` reaching `pk__in`
        # as a string raises ValueError — a 500 on a public page from a
        # hand-typed URL. isascii() is part of the guard, not decoration:
        # "²".isdigit() is True and int("²") raises.
        ids = [v for v in map(str, value or []) if v.isascii() and v.isdigit()]
        if not ids:
            return []
        labels = {
            str(pk): title
            for pk, title in Game.objects.filter(pk__in=ids).values_list("pk", "title")
        }
        # `ids` order, not the queryset's: chips render in querystring order.
        return [(v, labels[v]) for v in ids if v in labels]
```

- [ ] **Step 6: Add the field**

In `RecruiterSearchForm`, after `genres`:

```python
    games = forms.ModelMultipleChoiceField(
        queryset=Game.objects.all(),
        required=False,
        label=_("Specific games"),
        widget=GameTypeaheadSelectMultiple(
            url_name="search:game_filter_autocomplete", placeholder=_("Search games…")
        ),
        # The alternative to engines/genres/min_rating, not a companion to
        # them — clean() below refuses both at once (spec 2026-08-24 §7).
    )
```

and add `cleaned.get("games"),` to `clean()`'s `has_filter` list, immediately after `cleaned.get("genres"),`.

- [ ] **Step 7: Wire the view**

In `search/views.py`, inside the `recruiter_search(...)` call, after the `genre_ids` line:

```python
                game_ids=[game.pk for game in cleaned.get("games") or []],
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run pytest search/tests/ -v
```

Expected: PASS. If `test_junk_game_id_does_not_break_the_public_page` fails for one of the junk values, the failure is in Django's own field validation, not in `_chips` — read the traceback before touching the guard. Do not widen the guard beyond `isascii() and isdigit()`: the same five shapes were measured against the existing `engines` facet before this branch and all returned 200, so anything more is guarding against a failure mode that does not exist.

- [ ] **Step 9: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 10: Commit**

```bash
git add search/forms.py search/views.py search/tests/
git commit -s -m "feat(search): a specific-games filter field

ModelMultipleChoiceField over Game, rendered by the same chip typeahead as
engines/genres/countries, so it posts the same repeated ?games=12&games=88.

It cannot reuse TypeaheadSelectMultiple._chips() as-is: that builds its label
map by iterating self.choices, which for Game means materialising ~391k rows on
every render of the home page. The subclass looks up only the selected ids and
keeps the property the base class exists for — a label is never derived from
the raw value, so an unknown id renders no chip.

Junk ids are filtered before the query, not after: ?games=abc would reach
pk__in as a string and 500 a public page from a hand-typed URL.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The OR — mutual exclusion in `clean()`

**Files:**
- Modify: `search/forms.py` (`RecruiterSearchForm.clean`)
- Test: `search/tests/test_recruiter_form.py`

**Interfaces:**
- Consumes: the `games` field (Task 3).
- Produces: a non-field `ValidationError` with the exact message `Filter either by game criteria or by specific games, not both.` Task 8's script mirrors this rule client-side; Task 5's template already renders `{{ form.non_field_errors }}`.

- [ ] **Step 1: Write the failing tests**

Append to `search/tests/test_recruiter_form.py`:

```python
_CONFLICT = "Filter either by game criteria or by specific games, not both."


@pytest.mark.parametrize("criteria", ["genres", "min_rating", "engines"])
def test_each_game_criterion_conflicts_with_specific_games(criteria: str) -> None:
    """The two ways of naming games are alternatives, not filters that compose:
    adding a genre to a list of named games can only narrow it into nonsense.
    Parametrized so dropping any one of the three from clean() fails here."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    values = {
        "genres": [str(Genre.objects.create(name="RPG").pk)],
        "engines": [str(Engine.objects.create(name="Unreal Engine").pk)],
        "min_rating": "70",
    }

    form = RecruiterSearchForm({"games": [str(game.pk)], criteria: values[criteria]})

    assert not form.is_valid()
    assert _CONFLICT in form.non_field_errors()


@pytest.mark.parametrize(
    "person_filter",
    [
        {"countries": ["FR"]},
        {"year_from": "2015"},
        {"open_to_work": "on"},
    ],
)
def test_person_filters_do_not_conflict_with_specific_games(
    person_filter: dict[str, object],
) -> None:
    """The whole person section answers a different question and stays
    available in both modes (spec 2026-08-24 §7)."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    form = RecruiterSearchForm({"games": [str(game.pk)], **person_filter})

    assert form.is_valid(), form.errors


def test_discipline_does_not_conflict_with_specific_games() -> None:
    """Separate from the parametrized cases above: discipline needs a real row."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")

    form = RecruiterSearchForm({"games": [str(game.pk)], "discipline": str(discipline.pk)})

    assert form.is_valid(), form.errors


def test_a_field_error_does_not_also_report_the_conflict() -> None:
    """Same reasoning as the zero-filter rule: a field-level error already told
    the user what is wrong."""
    game = Game.objects.create(title="Hades", source=Game.Source.MANUAL)

    form = RecruiterSearchForm({"games": [str(game.pk)], "min_rating": "200"})

    assert not form.is_valid()
    assert _CONFLICT not in form.non_field_errors()
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest search/tests/test_recruiter_form.py -k conflict -v
```

Expected: FAIL — the forms are currently valid, so the `_CONFLICT` assertions fail.

- [ ] **Step 3: Implement the rule**

In `search/forms.py`, in `clean()`, insert between the `if self.errors: return cleaned` guard and the `has_filter` block:

```python
        # The two ways of naming games are alternatives, not filters that
        # compose: adding a genre to a list of named games can only narrow it
        # into nonsense. Enumerated, like has_filter below — a loop over the
        # criteria would fail OPEN the day a fourth one is added.
        criteria = any(
            [cleaned.get("genres"), cleaned.get("min_rating"), cleaned.get("engines")]
        )
        if criteria and cleaned.get("games"):
            raise forms.ValidationError(
                _("Filter either by game criteria or by specific games, not both.")
            )
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest search/tests/test_recruiter_form.py -v
```

Expected: PASS.

- [ ] **Step 5: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 6: Commit**

```bash
git add search/forms.py search/tests/test_recruiter_form.py
git commit -s -m "feat(search): game criteria and specific games are alternatives

Naming games outright and describing them by genre/rating/engine answer the
same question two ways; combining them can only narrow a list of named games
into nonsense. clean() refuses both at once.

The person section is untouched: country, year, discipline and open-to-work
answer a different question and stay available in both modes.

The criteria are enumerated rather than looped, for the same reason the
zero-filter rule enumerates its fields — a loop fails OPEN the day a fourth
criterion is added.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The bento template

**Files:**
- Create: `templates/search/_filter_field.html`
- Modify: `templates/search/people_search.html:53-89`, `search/forms.py` (`game_fields` → `criteria_fields`)
- Test: `search/tests/test_filter_rows.py`, `search/tests/test_filter_autocomplete.py`

**Interfaces:**
- Consumes: `form.games` (Task 3).
- Produces: `RecruiterSearchForm.criteria_fields() -> list[forms.BoundField]` returning `[genres, min_rating, engines]` in that order; the CSS hooks `.filter-section`, `.filter-split`, `.filter-group`, `.filter-group-head`, `.filter-or`, and the JS hook `data-filter-group` on each `.filter-group`. Tasks 7 and 8 depend on those exact names.

- [ ] **Step 1: Update the legend-reading helper and write the failing tests**

`{% translate %}` autoescapes, and Task 6 introduces an apostrophe into a legend — unescape before comparing, or renamed legends look absent. In `search/tests/test_filter_rows.py`, add `import html` at the top and replace `_fieldsets`:

```python
def _fieldsets(body: str) -> dict[str, str]:
    """Keyed on the legend text, unescaped: `{% translate %}` autoescapes, so
    "they've" reaches the HTML as "they&#x27;ve"."""
    return {
        html.unescape(re.search(r"<legend>([^<]+)</legend>", fs).group(1)).strip(): fs  # ty: ignore[unresolved-attribute]
        for fs in re.findall(r"<fieldset[^>]*>.*?</fieldset>", body, re.S)
    }
```

Then add these tests (keeping the current legend strings — Task 6 renames them):

```python
def test_game_criteria_are_ordered_genre_rating_engine(client: Client) -> None:
    """Genre is the coarsest facet a recruiter reaches for and comes first;
    engine is the specialist's and comes last (spec 2026-08-24 §3)."""
    body = client.get(reverse("home")).content.decode()
    row = _fieldsets(body)["Games they worked on"]

    assert (
        row.index('id="id_genres"')
        < row.index('id="id_min_rating"')
        < row.index('id="id_engines"')
    )


def test_the_two_game_cards_are_alternatives(client: Client) -> None:
    """The three criteria and the named games are drawn as two cards with OR
    between them — the layout IS the rule clean() enforces (spec §2, §7)."""
    body = client.get(reverse("home")).content.decode()
    row = _fieldsets(body)["Games they worked on"]

    assert row.count('class="filter-group"') == 2
    assert "Games matching all of:" in row
    assert "Credited on any of:" in row
    assert ">OR<" in row
    assert 'id="id_games"' in row


def test_the_games_facet_is_not_in_the_person_row(client: Client) -> None:
    person = _fieldsets(client.get(reverse("home")).content.decode())["About the person"]
    assert 'id="id_games"' not in person
```

- [ ] **Step 2: Update the counted assertions in `test_filter_autocomplete.py` and `test_filter_rows.py`**

A fourth typeahead now renders. Change these four assertions:

- `test_filter_rows.py::test_empty_chips_list_renders_truly_empty`: `== 3` → `== 4`
- `test_filter_autocomplete.py::test_typeahead_search_box_stays_out_of_the_querystring`: `== 3` → `== 4`
- `test_filter_autocomplete.py::test_no_js_hides_the_dead_controls_and_says_so`: `== 3` → `== 4`
- `test_filter_autocomplete.py::test_empty_form_does_not_ship_a_choice_per_country`: the `< 20` input cap and the `< 15_000` byte cap must be **re-measured, not guessed**. After Step 5, run:

  ```bash
  uv run python - <<'PY'
  import django, os
  os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
  django.setup()
  from django.test import Client
  c = Client().get("/").content.decode()
  print("inputs:", c.count("<input"), "bytes:", len(c))
  PY
  ```

  Raise each cap to the measured value plus roughly 10% headroom and say so in the test's docstring. The assertion's point is "no choice-per-country list ever comes back" — keep the caps tight enough that re-inlining 249 choices still fails.

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest search/tests/test_filter_rows.py -v
```

Expected: FAIL — `KeyError`/`ValueError` on `id="id_games"` and the ordering assertion, since the template renders neither the games field nor the cards.

- [ ] **Step 4: Create the field partial**

`templates/search/_filter_field.html`:

```html
{% comment %}
  One filter cell. Written once because it is now used in three places (the two
  game sub-cards and the person row), and because the open_to_work exception
  has to live in exactly one of them.

  A <label for> per field, not just the section's <legend>: the legend only
  names the group, and a group name is not an accessible name every control
  inside it can share (that was the old checkbox list's problem).
{% endcomment %}
<div class="filter{% if field.name == 'open_to_work' %} filter-checkbox{% endif %}">
  {% if field.name == "open_to_work" %}
    {# The box lives inside its label, so box and text are one hit target; the
       cell has no input row of its own, and app.css bottom-aligns it onto the
       row's input line (spec 2026-08-24 §3.2). #}
    <label>{{ field }} {{ field.label }}</label>{{ field.errors }}
  {% else %}
    <label for="{{ field.id_for_label }}">{{ field.label }}</label>
    {{ field.errors }}{{ field }}
  {% endif %}
</div>
```

- [ ] **Step 5: Rewrite the form block**

In `templates/search/people_search.html`, replace lines 53–89 (from `<form class="filters"` through its `</form>`) with:

```html
  <form class="filters" method="get" action="{% url 'home' %}#results">
    {{ form.non_field_errors }}
    {% comment %}
      Two sections, each a <fieldset> whose <legend> names the group; the field
      cells keep their own <label for> (see _filter_field.html). The first
      section splits into two cards that are ALTERNATIVES — the three criteria,
      or the games named outright — which is the rule the form's clean()
      enforces (spec 2026-08-24 §7). Drawing it is what makes the rule
      discoverable before the visitor trips it.
    {% endcomment %}
    <fieldset class="filter-section">
      <legend>{% translate "Games they worked on" %}</legend>
      <div class="filter-split">
        <div class="filter-group" data-filter-group>
          <p class="filter-group-head"><small class="muted">{% translate "Games matching all of:" %}</small></p>
          <div class="filter-row">
            {% for field in form.criteria_fields %}{% include "search/_filter_field.html" %}{% endfor %}
          </div>
        </div>
        {# Not decorative: OR states the relationship between the two cards, so
           it stays in the accessibility tree rather than being aria-hidden. #}
        <div class="filter-or"><span>{% translate "OR" %}</span></div>
        <div class="filter-group" data-filter-group>
          <p class="filter-group-head"><small class="muted">{% translate "Credited on any of:" %}</small></p>
          <div class="filter-row">
            {% include "search/_filter_field.html" with field=form.games %}
          </div>
        </div>
      </div>
    </fieldset>
    <fieldset class="filter-section">
      <legend>{% translate "About the person" %}</legend>
      <div class="filter-row">
        {% for field in form.person_fields %}{% include "search/_filter_field.html" %}{% endfor %}
      </div>
    </fieldset>
    {# The data caveat once, not per field: genre and rating data cover Steam-linked games only (ROADMAP "Non-Steam facet coverage"). #}
    <p class="filters-note"><small class="muted">{% translate "Genre and rating data currently cover Steam-linked games only." %}</small></p>
    <button type="submit">{% translate "Search" %}</button>
  </form>
```

- [ ] **Step 6: Rename the form accessor**

In `search/forms.py`, replace `game_fields()` with:

```python
    def criteria_fields(self) -> list[forms.BoundField]:
        """The three game criteria, in the order a recruiter reaches for them
        (spec 2026-08-24 §3): genre is the coarsest facet, engine the
        specialist's. `games` is deliberately absent — it is the alternative to
        this group, not a member of it, and the template renders it on its own
        so the two cards can never be looped into one row by accident."""
        return [self["genres"], self["min_rating"], self["engines"]]
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run pytest search/tests/ -v
```

Expected: PASS. The page is unstyled at this point — the CSS hooks land in Task 7. That is fine and expected; do not add styles here.

- [ ] **Step 8: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 9: Commit**

```bash
git add templates/search/ search/forms.py search/tests/
git commit -s -m "feat(search): draw the filter block as two alternative cards

The three game criteria and the named-games facet become two cards with OR
between them, inside the section that names them. Drawing the alternative is
what makes clean()'s rule discoverable before a visitor trips it.

Row 1 reorders to genre, rating, engine: genre is the coarsest facet a
recruiter reaches for, engine the specialist's.

The per-field markup moves to one _filter_field.html partial — it was written
twice and this change would have made it four times, with the open_to_work
exception duplicated across all of them.

The legend-reading test helper now unescapes: {% translate %} autoescapes, and
the renamed legends carry an apostrophe.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The copy

**Files:**
- Modify: `search/forms.py` (field labels), `templates/search/people_search.html` (two legends, the noscript note)
- Test: `search/tests/test_filter_rows.py`

**Interfaces:**
- Consumes: the template shape from Task 5.
- Produces: the final strings. Task 9's docs edit quotes them.

- [ ] **Step 1: Update the tests to the new copy**

In `search/tests/test_filter_rows.py`, replace every `"Games they worked on"` with `"The games they've worked on"` and every `"About the person"` with `"The person"` (they appear in `test_two_rows_hold_the_right_filters`, `test_game_criteria_are_ordered_genre_rating_engine`, `test_the_two_game_cards_are_alternatives`, `test_the_games_facet_is_not_in_the_person_row`). Then add:

```python
def test_fields_are_named_in_plain_words(client: Client) -> None:
    """The old labels named the database column ("Engines", "Discipline"), not
    the question a visitor is answering (spec 2026-08-24 §5)."""
    body = client.get(reverse("home")).content.decode()

    for label in (
        "Game genre",
        "Minimum player rating (%)",
        "Game engine",
        "Specific games",
        "Their role",
        "Based in",
        "Credited since (year)",
    ):
        assert f">{label}</label>" in body, label
    assert ">Engines</label>" not in body
    assert ">Discipline</label>" not in body
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest search/tests/test_filter_rows.py -v
```

Expected: FAIL — `KeyError: "The games they've worked on"`.

- [ ] **Step 3: Rename the field labels**

In `search/forms.py`, apply exactly these, changing nothing else about the fields:

| Field | New `label=` |
|---|---|
| `discipline` | `_("Their role")` |
| `engines` | `_("Game engine")` |
| `genres` | `_("Game genre")` |
| `games` | `_("Specific games")` *(already set in Task 3)* |
| `countries` | `_("Based in")` |
| `min_rating` | `_("Minimum player rating (%)")` |
| `year_from` | `_("Credited since (year)")` |
| `open_to_work` | `_("Open to work only")` *(unchanged)* |

- [ ] **Step 4: Rename the legends and the noscript note**

In `templates/search/people_search.html`:

- `{% translate "Games they worked on" %}` → `{% translate "The games they've worked on" %}`
- `{% translate "About the person" %}` → `{% translate "The person" %}`
- The noscript note, which now covers four typeaheads:

```html
  <p class="noscript-note">
    {% translate "The genre, game, engine and country filters need JavaScript. Without it you can still filter by role, rating, year and open-to-work." %}
  </p>
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest search/tests/ -v
```

Expected: PASS. If `test_no_js_hides_the_dead_controls_and_says_so` fails, check it is still asserting the substring `"need JavaScript"`, which the new sentence keeps.

- [ ] **Step 6: Full toolchain**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 7: Commit**

```bash
git add search/forms.py templates/search/people_search.html search/tests/test_filter_rows.py
git commit -s -m "feat(search): name the filters in plain words

The labels named the database column — Engines, Genres, Discipline, Countries —
rather than the question a visitor is answering. Every one is renamed to the
descriptive register the owner picked against a rendered mockup.

The noscript note now covers four typeaheads rather than three, and names the
person facet by its new label.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: The stylesheet

**Files:**
- Modify: `static/css/app.css:91-124` (the filter-row block), `static/css/theme.css` (one legend rule, after the existing `label, legend, th` block at :118-130)

**Interfaces:**
- Consumes: the class hooks from Task 5.
- Produces: `.filter-group[data-off] { opacity: .45 }`, which Task 8's script toggles.

**No test asserts computed styles** — this task's verification is the browser pass in Task 10. Do not invent a CSS test.

- [ ] **Step 1: Replace the filter block in `app.css`**

Replace the block currently spanning `/* Filter rows (spec 2026-08-21-search-chrome §2) ... */` through `.filters-note { ... }` with:

```css
/* The filter bento (spec 2026-08-24 §2). One drawn card around the form, and
   inside it two sub-cards that are alternatives rather than neighbours. The
   border colours are Pico variables, same as .chip and .notice above — this
   file still states no colour of its own. */
.filters {
  border: 1px solid var(--pico-muted-border-color);
  padding: 1rem 1.1rem .5rem;
  /* The air between Search and "Latest credits" (§2). */
  margin-bottom: 2.75rem;
}
.filter-section { border: 0; padding: 0; margin: 0 0 1.1rem; }
.filter-section:last-of-type { margin-bottom: .6rem; }
/* A <legend> is not a grid item (it's the fieldset's accessible name, rendered
   outside the box it labels), so grid-column on it is a no-op. Size and weight
   are theme.css's — this is spacing only. */
.filter-section > legend { padding: 0; margin-bottom: .55rem; }

/* The two cards and the rule between them. Left column wider: it holds three
   fields to the right column's one. */
.filter-split {
  display: grid; grid-template-columns: minmax(0, 1.9fr) auto minmax(0, 1fr);
  gap: .8rem;
}
/* start on the CARDS, not on the grid: a card holding one field would
   otherwise stretch to the tall one's height and be mostly empty space (§2).
   The grid itself must keep stretching, or .filter-or has no height to draw
   its rule down. */
.filter-group {
  align-self: start;
  border: 1px solid var(--pico-muted-border-color);
  padding: .55rem .75rem .35rem;
}
.filter-group > .filter-row { margin-bottom: 0; }
.filter-group-head { margin: 0 0 .1rem; }
/* A full-height line with the word sitting on it: ::before draws the rule,
   and the <span> punches through it with the page's own background. */
.filter-or { position: relative; display: flex; align-items: center; justify-content: center; }
.filter-or::before {
  content: ""; position: absolute; top: 0; bottom: 0; left: 50%;
  border-left: 1px solid var(--pico-muted-border-color);
}
.filter-or span { position: relative; background: var(--pico-background-color); padding: .35rem 0; }
/* The empty half of the OR, disabled by the page's script (§7). An opacity,
   never a colour — the controls inside are already inert. */
.filter-group[data-off] { opacity: .45; }

/* Field cells. Was minmax(13rem, 1fr): the 1fr stretched four controls across
   the whole 72rem column and left the ragged gaps between them (§2). A max
   track plus justify-content packs them left at a readable width instead. */
.filter-row { border: 0; padding: 0; margin: 0 0 .25rem; display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 13.5rem));
  justify-content: start; gap: 0 .8rem; align-items: start; }
/* The typeahead's text input and the plain <select>s otherwise size to
   content, leaving a ragged column; fill the grid cell like Pico's other
   full-width form controls do (excluding the open_to_work checkbox, which
   sits inline with its label). */
.filter-row input:not([type=checkbox]), .filter-row select { width: 100%; }
/* The shared data-caveat footnote under the two sections (§2). */
.filters-note { margin: 0 0 .5rem; }

/* Enough to keep the bento usable on a narrow screen — the cards stack and the
   OR rule turns horizontal. The real narrow-viewport pass is a follow-up
   (spec 2026-08-24 §10), deliberately not attempted here. */
@media (max-width: 767px) {
  .filter-split { grid-template-columns: 1fr; }
  .filter-or { padding: .2rem 0; }
  .filter-or::before {
    top: 50%; bottom: auto; left: 0; right: 0;
    border-left: 0; border-top: 1px solid var(--pico-muted-border-color);
  }
  .filter-or span { padding: 0 .6rem; }
}
```

**Leave `.filter { margin: .6rem 0; }` and `.filter-checkbox { align-self: end; padding-bottom: 1rem; }` exactly as they are.** That padding is a measured value (app.css says so): changing `.filter`'s margin would silently break the checkbox's alignment onto the row's input line, and no test can catch it.

- [ ] **Step 2: Add the legend size to `theme.css`**

After the `:root[data-theme=light] label, legend, th { font-size: .8rem; font-weight: 700; }` block:

```css
/* The filter section names outrank the field labels (spec 2026-08-24 §4):
   before this, `legend` and `label` shared one .8rem mono bold and the group
   names grouped nothing. Written at this specificity on purpose — the
   `:root[data-theme=light] legend` rule above is (0,2,1) and would beat a bare
   `.filter-section > legend` however late it appeared. */
:root[data-theme=light] .filter-section > legend {
  font-size: 1.05rem; letter-spacing: -.01em;
}
```

- [ ] **Step 3: Confirm nothing regressed in the suite**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

Expected: PASS. (No test reads CSS; this only confirms the edit broke nothing else.)

- [ ] **Step 4: Commit**

```bash
git add static/css/app.css static/css/theme.css
git commit -s -m "style(search): the filter bento and its type hierarchy

theme.css gave label, legend and th one .8rem mono bold, so the section names
grouped nothing; the legend now sits at 1.05rem. It has to be written at
:root[data-theme=light] specificity — the existing legend rule is (0,2,1) and
beats a bare class selector whatever the source order.

app.css draws the form as one card with two alternative sub-cards and a rule
between them, and packs the field cells left: the old minmax(13rem, 1fr)
stretched four controls across the full 72rem column. align-self:start sits on
the cards rather than the grid, so the single-field card takes its natural
height while the OR rule still has a full row to draw down.

.filter's margin and .filter-checkbox's padding are untouched on purpose: that
padding is a measured value and no test can catch it moving.

The media query is the minimum that keeps a narrow screen usable; the real
mobile pass is a follow-up.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The client-side OR

**Files:**
- Modify: `templates/search/people_search.html` (the existing inline `<script>` block)

**Interfaces:**
- Consumes: `data-filter-group` (Task 5), `.filter-group[data-off]` (Task 7), the existing `addChip`/chip-remove handlers.
- Produces: nothing later tasks consume.

**No pytest coverage** — the project has no JS runner, and `2026-08-22-autocomplete-dismiss-design.md` set the precedent of a browser checklist instead. Task 10 carries it.

- [ ] **Step 1: Add the exclusion functions**

Inside the existing IIFE in `templates/search/people_search.html`, after `addChip`:

```js
      // The OR between the two game cards (spec 2026-08-24 §7). The filled side
      // stays live and the empty one is disabled — disabled controls are not
      // submitted, so this IS the mechanism in the browser, not a hint on top
      // of one. The form's clean() is still the boundary: this only spares the
      // visitor from reaching it.
      function isFilled(group) {
        if (group.querySelector(".chips input")) return true;
        const numbers = group.querySelectorAll("input[type=number]");
        for (const number of numbers) {
          if (number.value.trim() !== "") return true;
        }
        return false;
      }

      function syncExclusion() {
        const groups = Array.from(document.querySelectorAll(".filters [data-filter-group]"));
        const filled = groups.filter(isFilled);
        // Exactly one filled is the only state that disables anything. Neither
        // filled is the empty form; BOTH filled is only reachable from a
        // crafted querystring, and there the server's error is what should
        // speak — disabling half of it would hide the value being complained
        // about.
        groups.forEach(function (group) {
          const off = filled.length === 1 && !filled.includes(group);
          group.toggleAttribute("data-off", off);
          group.querySelectorAll("input, select, button").forEach(function (control) {
            control.disabled = off;
          });
        });
      }
```

- [ ] **Step 2: Call it from the three places that change the state**

In the existing click handler, add `syncExclusion();` immediately before the `return;` in the option branch, and immediately after the chip-remove branch:

```js
      document.addEventListener("click", function (event) {
        const option = event.target.closest(".typeahead .autocomplete-option");
        if (option) {
          const widget = option.closest(".typeahead");
          addChip(widget, option.dataset.id, option.dataset.label);
          widget.querySelector(".results").innerHTML = "";
          const input = widget.querySelector(".autocomplete-input");
          input.value = "";
          input.focus();  // keep picking without reaching for the mouse
          syncExclusion();
          return;
        }
        const remove = event.target.closest(".typeahead .chip-remove");
        if (remove) {
          remove.closest(".chip").remove();
          syncExclusion();
        }
      });

      // Typing in the rating box is the other way a side becomes filled. The
      // typeahead's own `q` box is a DOM descendant of the form even though
      // <form id="typeahead-scratch"> owns it for submission, so its events
      // bubble here too — harmless, since only chips count as filled.
      document.addEventListener("input", function (event) {
        const target = event.target;
        if (target && target.closest && target.closest(".filters")) syncExclusion();
      });

      // Server-rendered chips are a filled state the page arrives in.
      syncExclusion();
```

- [ ] **Step 3: Confirm the suite still passes**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

Expected: PASS. No new user-facing string is introduced here, so nothing needs `{% translate %}`.

- [ ] **Step 4: Commit**

```bash
git add templates/search/people_search.html
git commit -s -m "feat(search): keep exactly one side of the filter OR live

Filling either game card disables the other's controls and dims it. Disabled
inputs are not submitted, so this is the mechanism in the browser rather than a
hint layered over one — though clean() stays the boundary, since a crafted
querystring reaches neither.

Only "exactly one side filled" disables anything. Both filled is reachable only
from a hand-typed URL, and there the server's error should speak: disabling
half the form would hide the very value being complained about. The filled side
is always the live one, so its chips can be removed to switch modes — nothing
is ever locked behind the state that caused it.

No pytest coverage: the project has no JS runner. The browser checklist in the
spec is the coverage, as with the autocomplete dismissal.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Docs

**Files:**
- Modify: `docs/01-DESIGN.md:100` (the §3.6 filter paragraph), `ROADMAP.md` (a new entry after the 2026-08-24 profile-message line)

**Interfaces:** none.

- [ ] **Step 1: Update `docs/01-DESIGN.md` §3.6**

In the long `**Recruiter search filters:**` bullet at line 100, make three edits:

1. In the opening facet list, after `× game genres (multi, OR within)`, insert `× specific games named outright (multi, OR within)`.
2. Replace the sentence `Engines/genres/countries are picked through an htmx typeahead (chips), not exhaustive checkbox lists.` with:

   ```
   Engines/genres/games/countries are picked through an htmx typeahead (chips), not exhaustive checkbox lists; the games typeahead has its own endpoint (`filters/games/`) and deliberately offers no deeper-search import, since a game nobody is credited on cannot match anyone.
   ```
3. Replace the whole `**The form lays out as two labelled rows** (changed 2026-08-21, ...)` sentence through the end of the bullet with:

   ```
   **The form lays out as one drawn card** (changed 2026-08-24, spec `docs/superpowers/specs/2026-08-24-filter-bento-and-game-facet-design.md`; supersedes the two flat rows of 2026-08-21): a **The games they've worked on** section holding two mutually exclusive sub-cards — *Games matching all of:* (game genre · minimum player rating · game engine) **OR** *Credited on any of:* (specific games) — and a **The person** section (their role · based in · credited since · open to work only). The two ways of naming games are alternatives, not filters that compose: the form refuses both at once with `Filter either by game criteria or by specific games, not both.`, and the page disables the empty side so a visitor meets the rule before tripping it. The person section is unaffected and stays available in both modes. The per-field "any of the selected" and Steam-only-data help texts are gone; the data caveat surfaces once, as a single footnote under the sections.
   ```

- [ ] **Step 2: Add the ROADMAP entry**

In `ROADMAP.md`, immediately after the `**Profile-only Message button + layout polish** (2026-08-24)` bullet, add:

```markdown
- [x] **Filter bento + a specific-games facet** (2026-08-24): the home page's filter block becomes one drawn card with a real type hierarchy (`theme.css` gave `label`, `legend` and `th` one `.8rem` mono bold, so the section names grouped nothing — legends now sit at `1.05rem`). Inside it, the three game criteria and a **new `games` facet** are drawn as two mutually exclusive cards with `OR` between them: naming games outright and describing them by genre/rating/engine answer the same question two ways, and combining them can only narrow a list of named games into nonsense. `clean()` refuses both at once; the page disables the empty side (disabled controls are not submitted, so that IS the browser-side mechanism), and the person section stays available in both modes. Row 1 reorders to genre · rating · engine, every label is renamed out of database vocabulary ("Engines" → "Game engine", "Discipline" → "Their role"), and the field cells pack left — the old `minmax(13rem, 1fr)` stretched four controls across the full 72rem column. Two traps carried the real work: `TypeaheadSelectMultiple._chips()` builds its label map by iterating `self.choices`, which for `Game` would materialise ~391k rows **on every render of the home page** (a subclass looks up only the selected ids), and `?games=abc` would reach `pk__in` as a string — a 500 on a public page from a hand-typed URL. The games typeahead gets its own `filters/games/` endpoint rather than reusing the credit form's, which offers an IGDB import that cannot produce a match. **The narrow-viewport pass is deliberately deferred** — this ships only the stacking that keeps a phone usable. Spec: `docs/superpowers/specs/2026-08-24-filter-bento-and-game-facet-design.md`.
```

- [ ] **Step 3: Confirm the suite still passes**

```bash
uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run ty check
```

- [ ] **Step 4: Commit**

```bash
git add docs/01-DESIGN.md ROADMAP.md
git commit -s -m "docs: the filter bento and the specific-games facet

docs/01-DESIGN.md §3.6 described two flat rows and the old labels; ROADMAP gains
the phase entry. A behaviour change updates both in the same PR.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Browser verification against the real catalogue

**Files:** none — this task produces evidence, and fixes only what it finds.

**Why this task exists:** two of the three defects that mattered most on this project were invisible to a green suite, because the test DB holds a handful of rows and the real one holds 391k. A `games` typeahead over the real catalogue is exactly that shape of risk. The CSS has no test at all.

- [ ] **Step 1: Bring the dev database up to date**

```bash
docker compose up -d db && uv run python manage.py migrate
```

Then confirm the catalogue is real, not fixtures:

```bash
uv run python manage.py shell -c "from games.models import Game; print(Game.objects.count())"
```

Expected: ~391,482. If it prints ~301, the box has only `load_dev_fixtures` data — load the real one first:

```bash
uv run python manage.py seed_games --source data/rollcall_games.parquet
```

- [ ] **Step 2: Start the dev server**

Use the `preview_start` tool with `{"name": "rollcall-dev"}` — the one configuration in `.claude/launch.json`, on port 8010. **Never** run the server through Bash.

- [ ] **Step 3: Walk the checklist**

Record a pass/fail for each. Any failure is diagnosed in source and fixed before the task is done.

1. **Hierarchy** — "The games they've worked on" and "The person" are visibly larger than "Game genre" etc.
2. **Bento** — one border around the whole form; two bordered cards inside section 1; the OR rule runs the full height between them.
3. **Right card height** — the "Credited on any of:" card is *not* stretched to the left card's height.
4. **Air** — a clear gap between the Search button and the "Latest credits" heading.
5. **Packing** — the person row's four cells sit close together on the left, not spread across the full width.
6. **Checkbox alignment** — "Open to work only" still sits on its row's input line (this is the measured value Task 7 was told not to disturb).
7. **Games typeahead** — type `hade`; real titles appear within a keystroke or two; **no "deeper search" option** is offered; picking one adds a chip.
8. **Exclusion, games → criteria** — with a game chip present, the left card is dimmed and its inputs refuse focus. Look at the dimming specifically: `.filter-group[data-off]`'s `opacity: .45` stacks on top of the browser's own dimming of `disabled` controls, so the card may read as far fainter than intended. Raised by the Task 8 review. If it is unreadable, raise the opacity rather than removing the disabled state — the disabling is the mechanism, the opacity is only its sign.
9. **Exclusion, criteria → games** — clear the chip, type `85` into the rating box: the right card dims instead.
10. **Switch back** — clear the rating box; both cards go live again.
11. **Submit in games mode** — pick a game a real member is credited on, Search: results render, and the URL carries `?games=<pk>` and *no* `engines=`/`genres=`/`min_rating=` (proving the disabled inputs did not submit).
12. **Both sides via a crafted URL** — load `/?games=<pk>&min_rating=85` by hand: the page renders 200 with `Filter either by game criteria or by specific games, not both.` and **both** cards live.
13. **Junk id** — load `/?games=abc`: 200, no chip, no 500.
14. **Narrow screen** — resize to 375px: the cards stack, the OR rule is horizontal, nothing overflows sideways. (Polish is out of scope; *broken* is not.)
15. **The 768–820px band** — raised by the Task 7 review, from the box model rather than from a render. At 768px the left card's content box works out to roughly 27.3rem, against the 28.6rem that three `minmax(9rem, 13.5rem)` tracks plus two `.8rem` gaps need: `auto-fit` would drop to two columns and wrap the third criterion onto its own line *inside* the card. This band sits **above** the `max-width: 767px` stacking rule, so the deferred mobile pass does not cover it. Check 768, 800 and 820px explicitly. If it wraps, the cheap fixes are narrowing the track minimum below `9rem` or widening the left column's `1.9fr` share — decide in the browser, with the measurement in hand.

- [ ] **Step 4: Capture the evidence**

Take a screenshot of the finished filter block at desktop width and one at 375px. Report both to the user with `SendUserFile`, alongside the checklist result.

- [ ] **Step 5: Commit any fixes**

If the walk produced fixes, commit them with a message naming what the browser showed that the suite could not. If it produced none, say so explicitly rather than committing an empty change.

---

## Self-Review

**Spec coverage.** §2 layout → Tasks 5, 7. §3 field order → Task 5. §4 type hierarchy → Task 7. §5 copy → Task 6. §6 the games facet, both traps and the endpoint → Tasks 1, 2, 3. §7 mutual exclusion, server and client → Tasks 4, 8. §8 template shape → Task 5. §9 tests → distributed across Tasks 1–6. §10 out-of-scope mobile → Task 7's media query and Task 10's item 14. §11 docs → Task 9. No section is unclaimed.

**Naming consistency, checked across tasks.** `game_ids` (service, Tasks 1 & 3) · `games` (form field, Tasks 3–6) · `criteria_fields()` (Tasks 5 & 6; replaces `game_fields()`, which is deleted in Task 5 and referenced nowhere after) · `GameTypeaheadSelectMultiple` (Task 3) · `search:game_filter_autocomplete` (Tasks 2 & 3) · `data-filter-group` (Tasks 5 & 8) · `.filter-group[data-off]` (Tasks 7 & 8) · `.filter-section`, `.filter-split`, `.filter-or`, `.filter-group-head` (Tasks 5 & 7).

**Ordering constraint.** Task 2 precedes Task 3 because `GameTypeaheadSelectMultiple` calls `reverse("search:game_filter_autocomplete")` at render time — added in the other order, every widget render raises `NoReverseMatch`.

**Known count changes**, all in Task 5, so a later task never trips over a stale number: three `== 3` → `== 4` assertions, plus the two re-measured caps in `test_empty_form_does_not_ship_a_choice_per_country`.
