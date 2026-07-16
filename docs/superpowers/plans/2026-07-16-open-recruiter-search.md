# Open Recruiter Search ("Find people") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open the recruiter search to everyone (with an anti-scraping ≥1-filter rule), add multi-select engine/genre filters and a person-level country filter (structured `User.country` field), and render rich result cards (matching credits, career stats, engine repartition %).

**Architecture:** Django monolith, server-rendered + htmx (no JS needed here). The search logic stays exclusively in `search/services.py`; `recruiter_search()` is reworked to take multi-value filters and return a typed, paginated `ResultsPage` of assembled `PersonResult` dataclasses (annotations are opaque to `ty`, and engine repartition needs grouped side-queries anyway — assembly is bounded by page size). Worker-side, `User.country` uses django-countries (ISO 3166-1); the free-text `location` stays as "City / region".

**Tech Stack:** Django ≥5.0, django-countries (new dep), django-ratelimit, PostgreSQL 16, pytest-django, uv/ruff/ty.

**Spec:** `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md` — read it first.

**House rules that apply to every task:**
- Fully typed Python (ruff `ANN` enforced). If django-countries descriptors are opaque to `ty`, use the codebase's established accommodations: a local `obj: Any = ...` bridge or a targeted `# ty: ignore[...]` comment (see `accounts/models.py` for examples).
- Quality gate before every commit: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q`. (If `ruff format --check` fails, run `uv run ruff format .` and re-stage.)
- Postgres must be running for tests: `docker compose up -d db`.

---

## File map (who owns what)

| File | Change |
|---|---|
| `pyproject.toml` / `uv.lock` | + django-countries (Task 1) |
| `config/settings/base.py` | + `django_countries` in INSTALLED_APPS (Task 1) |
| `accounts/models.py` + new migration `accounts/0005_*` | `User.country`, relabel `location` (Task 1) |
| `accounts/forms.py` | `country` on `SettingsForm` (Task 2) |
| `accounts/admin.py` | `country` in the explicit Profile fieldset (Task 2) |
| `accounts/export.py` | `country` in identity block (Task 2) |
| `accounts/models.py` | `User.location_display` property (Task 3) |
| `templates/accounts/profile.html` | renders `location_display` (Task 3) |
| `games/management/commands/load_dev_fixtures.py` | deterministic countries (Task 4) |
| `search/forms.py` | multi engines/genres, countries, ≥1-filter `clean()` (Task 5) |
| `search/tests/test_recruiter_form.py` | NEW — form rules (Task 5) |
| `search/services.py` | `PersonResult`, `ResultsPage`, reworked `recruiter_search` (Task 6) |
| `search/tests/test_recruiter_search.py` | rewritten for the new API (Task 6) |
| `search/views.py` | drop + delete `RecruiterRequiredMixin`, rate limit, pagination (Task 7) |
| `templates/search/recruiter_search.html` | checkbox fieldsets, result cards, pagination (Task 7) |
| `search/tests/test_recruiter_search_view.py` | rewritten — open access (Task 7) |
| `templates/search/recruiters_landing.html` | CTA → search, apply de-emphasized (Task 8) |
| `search/tests/test_recruiters_landing.py` | + link-to-search test (Task 8) |
| `docs/01-DESIGN.md`, `docs/04-DATABASE-SCHEMA.md`, `ROADMAP.md` | record the behavior change (Task 9) |

---

### Task 1: django-countries dependency + `User.country` field

**Files:**
- Modify: `pyproject.toml` (via `uv add`)
- Modify: `config/settings/base.py:37-38`
- Modify: `accounts/models.py:104-105`
- Create: `accounts/migrations/0005_user_country_alter_user_location.py` (generated)
- Test: `accounts/tests/test_user_model.py`

- [ ] **Step 1: Add the dependency**

```bash
uv add django-countries
```

Expected: `pyproject.toml` gains `"django-countries>=7.6"` (or newer) under `dependencies`, `uv.lock` updated.

- [ ] **Step 2: Register the app**

In `config/settings/base.py`, the third-party block becomes:

```python
    # Third-party
    "django_htmx",
    "django_countries",
```

- [ ] **Step 3: Write the failing test**

Append to `accounts/tests/test_user_model.py` (match the file's existing imports/style; add `from django_countries.fields import Country` to imports):

```python
def test_country_is_optional_and_stores_iso_code() -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    assert not user.country  # blank by default

    user.country = Country("FR")
    user.save(update_fields=["country"])
    user.refresh_from_db()
    assert user.country.code == "FR"
    assert user.country.name == "France"
```

- [ ] **Step 4: Run it — must fail**

```bash
uv run pytest accounts/tests/test_user_model.py -v -k country
```

Expected: ERROR/FAIL (`AttributeError: 'User' object has no attribute 'country'` or import error).

- [ ] **Step 5: Add the field**

In `accounts/models.py`, add the import at the top (with the other third-party imports):

```python
from django_countries.fields import CountryField
```

Then replace the `location` field definition (line ~105) with:

```python
    location = models.CharField(_("city / region"), max_length=150, blank=True, default="")
    country = CountryField(
        _("country"),
        blank=True,
        default="",
        help_text=_("Predefined list — powers the people-search country filter."),
    )
```

- [ ] **Step 6: Generate the migration**

```bash
uv run python manage.py makemigrations accounts
```

Expected: one new migration in `accounts/migrations/` adding `country` and altering `location` (verbose name). Any auto-generated name is fine; do not hand-edit it.

```bash
uv run python manage.py migrate
```

- [ ] **Step 7: Run the test — must pass**

```bash
uv run pytest accounts/tests/test_user_model.py -v
```

Expected: PASS. If `ty check` (next step) flags the `CountryField` assignment in `test`, bridge with the codebase's existing pattern (e.g. type the test variable as `Any`) — prefer no ignore if it passes clean.

- [ ] **Step 8: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add pyproject.toml uv.lock config/settings/base.py accounts/models.py accounts/migrations/ accounts/tests/test_user_model.py
git commit -m "feat(accounts): User.country (django-countries) + location relabelled city/region"
```

---

### Task 2: Country in settings form, admin, and GDPR export

**Files:**
- Modify: `accounts/forms.py:51-61` (`SettingsForm.Meta.fields`)
- Modify: `accounts/admin.py:18-37` (`UserAdmin.fieldsets`, Profile block)
- Modify: `accounts/export.py:29-39` (identity block)
- Test: `accounts/tests/test_settings.py`, `accounts/tests/test_account_management.py`

> **Added after Task 1's code review:** `UserAdmin.fieldsets` lists Profile fields
> explicitly, so a field absent from that tuple is invisible and uneditable in
> admin — `country` would otherwise ship as the only profile field staff can't
> see. No system check catches this (the field is `blank=True`).

- [ ] **Step 1: Write the failing tests**

Append to `accounts/tests/test_settings.py`:

```python
def test_update_country_from_settings(client: Client, user: User) -> None:
    client.force_login(user)
    client.post(
        reverse("accounts:settings"),
        {"display_name": "Me", "country": "FR", "location": "Lyon"},
    )
    user.refresh_from_db()
    assert user.country.code == "FR"
    assert user.location == "Lyon"
```

Append to `accounts/tests/test_account_management.py` (reuse the file's existing fixtures/helpers for a logged-in user — mirror `test_export_returns_json_attachment_with_identity_and_credits`'s setup):

```python
def test_export_includes_country(client: Client) -> None:
    user = User.objects.create_user(
        email="me@example.com", password="x", display_name="Me", country="SE"
    )
    client.force_login(user)
    data = client.get(reverse("accounts:export_data")).json()
    assert data["identity"]["country"] == "SE"
```

Append to `accounts/tests/test_user_model.py` — the admin fieldset guard (no
system check catches an omitted field, so assert it):

```python
def test_country_is_editable_in_admin() -> None:
    from accounts.admin import UserAdmin

    profile_fields = UserAdmin.fieldsets[1][1]["fields"]  # ty: ignore[non-subscriptable]
    assert "country" in profile_fields
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest accounts/tests/test_settings.py::test_update_country_from_settings accounts/tests/test_account_management.py::test_export_includes_country accounts/tests/test_user_model.py::test_country_is_editable_in_admin -v
```

Expected: FAIL (country not saved / KeyError `'country'` / not in fieldset).

- [ ] **Step 3: Implement**

`accounts/forms.py` — `SettingsForm.Meta.fields` becomes:

```python
        fields = [
            "display_name",
            "bio",
            "location",
            "country",
            "avatar",
            "profile_public",
            "contactable",
            "open_to_work",
        ]
```

`accounts/admin.py` — in `UserAdmin.fieldsets`, the Profile block's `"fields"`
tuple gains `"country"` immediately after `"location"`:

```python
                    "bio",
                    "location",
                    "country",
                    "github_login",
```

`accounts/export.py` — in the `"identity"` dict, after the `"location"` line, add:

```python
            "country": str(user.country),
```

(`str(Country)` is the ISO code, `""` when unset — JSON-safe. A raw `Country`
object is NOT JSON-serializable, so the `str()` is load-bearing, not cosmetic.)

- [ ] **Step 4: Run — must pass**

```bash
uv run pytest accounts -q
```

Expected: all PASS.

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add accounts/forms.py accounts/admin.py accounts/export.py accounts/tests/test_settings.py accounts/tests/test_account_management.py accounts/tests/test_user_model.py
git commit -m "feat(accounts): country in settings form, admin and GDPR export"
```

---

### Task 3: Profile displays "City · Country"

**Files:**
- Modify: `accounts/models.py` (add `User.location_display` property)
- Modify: `templates/accounts/profile.html:17`
- Test: `accounts/tests/test_user_model.py` (property), `accounts/tests/test_profile.py` (rendering)

> **Amended after Task 3's first code review.** The original plan inlined the
> join in the template — and prescribed the *same* markup again in Task 7's
> result cards, so the duplication was scheduled, not hypothetical. One property
> fixes four defects at once:
> 1. the copy-paste Task 7 would have inherited;
> 2. an untranslated `·` sitting inside translatable content (a locale may want
>    a comma — the separator belongs in `pgettext`);
> 3. a **real latent bug**: `bool(Country("ZZ"))` is `True` while `.name` is
>    `""`, so guarding on `country` rather than `country.name` renders a
>    dangling "Lyon · " for any invalid stored code (verified empirically —
>    reachable only by a raw `.update()`/bulk write that skips validation, which
>    is exactly what a seed or fixture does);
> 4. a 181-char template line with three nested inline `{% if %}` — the only
>    such line in all 31 templates.

- [ ] **Step 1: Write the failing tests**

The four branches are a pure string-join concern — test them on the property
(fast, no DB roundtrip, no HTML parsing), and leave ONE template test proving
the line reaches the page. Append to `accounts/tests/test_user_model.py`:

```python
@pytest.mark.parametrize(
    ("location", "country", "expected"),
    [
        ("Lyon", "FR", "Lyon · France"),
        ("Lyon", "", "Lyon"),
        ("", "FR", "France"),
        ("", "", ""),
        ("Lyon", "ZZ", "Lyon"),  # invalid code: truthy, but renders nothing
    ],
)
def test_location_display(location: str, country: str, expected: str) -> None:
    user = User(display_name="X", location=location, country=country)
    assert user.location_display == expected
```

Append to `accounts/tests/test_profile.py`:

```python
def test_profile_shows_city_and_country(client: Client) -> None:
    user = User.objects.create_user(
        email="loc@example.com",
        password="x",
        display_name="Located",
        location="Lyon",
        country="FR",
    )
    response = client.get(reverse("accounts:profile", kwargs={"slug": user.slug}))
    assert "Lyon · France" in response.content.decode()
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest accounts/tests/test_user_model.py accounts/tests/test_profile.py -v -k "location_display or city_and_country"
```

Expected: FAIL (`AttributeError: 'User' object has no attribute 'location_display'`).

- [ ] **Step 3: Implement**

In `accounts/models.py`, import `pgettext` alongside the existing
`gettext_lazy as _`, and add the property next to the existing
`is_email_verified` / `is_recruiter` properties:

```python
    @property
    def location_display(self) -> str:
        """"City · Country" for the profile and the search cards — omitting
        either part when unset. Guards on `country.name`, not `country`: an
        invalid stored code is truthy but renders empty."""
        separator = pgettext("between city and country", " · ")
        return separator.join(part for part in (self.location, self.country.name) if part)
```

Then in `templates/accounts/profile.html`, replace line 17:

```html
    {% if profile_user.location %}<p>{{ profile_user.location }}</p>{% endif %}
```

with:

```html
    {% if profile_user.location_display %}<p>{{ profile_user.location_display }}</p>{% endif %}
```

- [ ] **Step 4: Run — must pass**

```bash
uv run pytest accounts/tests/test_profile.py -v
```

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add accounts/models.py templates/accounts/profile.html accounts/tests/test_user_model.py accounts/tests/test_profile.py
git commit -m "feat(accounts): profile shows city and country via location_display"
```

---

### Task 4: Dev fixtures assign countries

**Files:**
- Modify: `games/management/commands/load_dev_fixtures.py:51-61` (constants) and `:184-203` (`_create_users`)
- Test: `games/tests/test_dev_fixtures.py`

- [ ] **Step 1: Write the failing tests**

> **Amended after Task 4's first code review.** The original plan's single test
> (`assert with_country.exists()`) is a change-detector that cannot fail when
> the thing this file actually guarantees — *draw ordering* — breaks. Aim the
> tests at the hard invariant instead. Three tests, each hitting a distinct
> target:

```python
def test_create_users_rng_consumption_is_independent_of_existing_rows() -> None:
    """THE invariant of this file: a draw must not depend on DB state. If one
    moves inside `if created:`, a re-run consumes a different number of values
    and every later draw shifts — silently changing "deterministic" data.
    Asserted directly on the rng state, not inferred from downstream row
    counts (which catch it only incidentally, via drift)."""
    command = Command()
    first = random.Random(42)
    command._create_users(first, 10)  # rows created
    expected_state = first.getstate()

    second = random.Random(42)
    command._create_users(second, 10)  # rows already exist
    assert second.getstate() == expected_state


@pytest.mark.parametrize("code", COUNTRY_CODES)
def test_country_codes_constant_is_valid_iso(code: str) -> None:
    """CountryField validation only runs via full_clean()/forms — get_or_create
    persists a bogus code silently, and an invalid code is truthy with an empty
    .name. Catches the plausible mistake: "UK" instead of the ISO "GB"."""
    assert Country(code).name


def test_fixture_country_proportion_is_roughly_intended() -> None:
    """~80% of devusers get a country. A range, not a literal, so the test
    isn't glued to one seed's exact roll count."""
    call_command("load_dev_fixtures", games=5, users=40, contributions=5)
    devusers = User.objects.filter(email__startswith="devuser")
    fraction = devusers.exclude(country="").count() / devusers.count()
    assert 0.65 <= fraction <= 0.95
```

Imports needed: `random`, `pytest`, `Country` from `django_countries.fields`,
`User`, `call_command`, and `COUNTRY_CODES` + `Command` from the fixtures module.

**Do NOT add** a pinned-seed-sequence test (hardcoding the exact `(country,
location)` pairs seed 42 produces). It reads like a determinism guard but is a
golden snapshot: it passes under the `if created:` mutation (verified twice,
independently), and its only real failure mode is "someone added an rng draw
earlier" — whose only remedy is re-pasting new literals. A test whose fix is
always a rubber stamp trains maintainers to rubber-stamp it.

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest games/tests/test_dev_fixtures.py -v
```

Expected: FAIL — `COUNTRY_CODES` doesn't exist yet (ImportError).

- [ ] **Step 3: Implement**

In `load_dev_fixtures.py`, add two constants after `LAST_NAMES` — every other
vocabulary in this file is a module constant with `# fmt: skip`, and the test
imports them rather than duplicating the literals:

```python
COUNTRY_CODES: list[str] = [
    "US", "FR", "GB", "CA", "DE", "SE", "JP", "PL", "ES", "BR", "AU", "NL",
]  # fmt: skip

CITIES: list[str] = ["Lyon", "Montreal", "Berlin", "Tokyo", ""]  # "" = city not given
```

In `_create_users`, inside the `defaults` dict (draws must stay unconditional for rng determinism — the dict literal guarantees that), add after `"profile_public"`:

```python
                    # Drawn independently of each other: mismatched pairs like
                    # "Tokyo · Brazil" are intentional — they exercise all four
                    # location_display branches (both/city/country/neither).
                    "country": rng.choice(COUNTRY_CODES) if rng.random() < 0.8 else "",
                    "location": rng.choice(CITIES),
```

- [ ] **Step 4: Run — must pass (including the existing idempotency test)**

```bash
uv run pytest games/tests/test_dev_fixtures.py -v
```

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add games/management/commands/load_dev_fixtures.py games/tests/test_dev_fixtures.py
git commit -m "feat(fixtures): deterministic countries and cities on dev users"
```

---

### Task 5: Search form — multi-select + countries + ≥1-filter rule

**Files:**
- Rewrite: `search/forms.py`
- Create: `search/tests/test_recruiter_form.py`

- [ ] **Step 1: Write the failing tests**

Create `search/tests/test_recruiter_form.py`:

```python
"""Recruiter search form — every field optional, but at least ONE filter is
required (anti-scraping: no filterless "all people" listing,
docs/02-ARCHITECTURE.md §5)."""

import pytest

from games.models import Engine, Genre
from search.forms import RecruiterSearchForm

pytestmark = pytest.mark.django_db


def test_zero_filters_is_invalid() -> None:
    form = RecruiterSearchForm({})
    assert not form.is_valid()
    assert "Pick at least one filter." in form.non_field_errors()


def test_page_param_alone_is_still_zero_filters() -> None:
    assert not RecruiterSearchForm({"page": "2"}).is_valid()


def test_open_to_work_alone_is_enough() -> None:
    assert RecruiterSearchForm({"open_to_work": "on"}).is_valid()


def test_min_rating_zero_counts_as_a_filter() -> None:
    assert RecruiterSearchForm({"min_rating": "0"}).is_valid()


def test_engines_and_genres_are_multi_select() -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    rpg = Genre.objects.create(name="RPG")

    form = RecruiterSearchForm(
        {"engines": [str(unreal.pk), str(unity.pk)], "genres": [str(rpg.pk)]}
    )

    assert form.is_valid()
    assert set(form.cleaned_data["engines"]) == {unreal, unity}
    assert list(form.cleaned_data["genres"]) == [rpg]


def test_countries_accepts_iso_codes_and_rejects_junk() -> None:
    assert RecruiterSearchForm({"countries": ["FR", "SE"]}).is_valid()
    assert not RecruiterSearchForm({"countries": ["ZZ"]}).is_valid()
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest search/tests/test_recruiter_form.py -v
```

Expected: FAIL (`engines` unknown field / zero-filter form currently valid).

- [ ] **Step 3: Rewrite the form**

Replace the whole `search/forms.py` with:

```python
"""Recruiter search filters (docs/01-DESIGN.md §3.6). Every field optional,
but at least one filter is required — the search is open to everyone, and a
filterless submit would be an exhaustive people listing (anti-scraping,
docs/02-ARCHITECTURE.md §5)."""

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _
from django_countries import countries

from contributions.models import Discipline
from games.models import Engine, Genre


class RecruiterSearchForm(forms.Form):
    discipline = forms.ModelChoiceField(
        queryset=Discipline.objects.all(), required=False, label=_("Discipline")
    )
    engines = forms.ModelMultipleChoiceField(
        queryset=Engine.objects.all(),
        required=False,
        label=_("Engines"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Matches games using any of the selected."),
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all(),
        required=False,
        label=_("Genres"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Matches games in any of the selected."),
    )
    countries = forms.MultipleChoiceField(
        choices=countries,
        required=False,
        label=_("Countries"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Where the person is — any of the selected."),
    )
    min_rating = forms.IntegerField(
        required=False, min_value=0, max_value=100, label=_("Min. rating (%)")
    )
    year_from = forms.IntegerField(
        required=False, min_value=1970, max_value=2100, label=_("Worked since (year)")
    )
    open_to_work = forms.BooleanField(required=False, label=_("Open to work only"))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        has_filter = any(
            [
                cleaned.get("discipline"),
                cleaned.get("engines"),
                cleaned.get("genres"),
                cleaned.get("countries"),
                cleaned.get("min_rating") is not None,
                cleaned.get("year_from") is not None,
                cleaned.get("open_to_work"),
            ]
        )
        if not has_filter:
            raise forms.ValidationError(_("Pick at least one filter."))
        return cleaned
```

Note: `choices=countries` — django-countries' `countries` object is a valid lazy choices iterable. If `ty` complains, wrap: `choices=list(countries)`.

- [ ] **Step 4: Run — must pass**

```bash
uv run pytest search/tests/test_recruiter_form.py -v
```

Expected: PASS. (`search/tests/test_recruiter_search_view.py` may now fail because the view still passes `cleaned["engine"]` — that's Task 7's territory; if it fails, temporarily accept it ONLY if you are doing Tasks 5–7 in one sitting. Otherwise, keep the view working by mapping old names now — see Step 5.)

- [ ] **Step 5: Keep the view compiling until Task 7 (minimal bridge)**

In `search/views.py` `RecruiterSearchView.get_context_data`, the old view reads `cleaned["engine"]`/`cleaned["genre"]` which no longer exist. Bridge minimally (full rework comes in Task 7) — replace the `context["results"] = recruiter_search(...)` call with:

```python
            engines = list(cleaned.get("engines") or [])
            genres = list(cleaned.get("genres") or [])
            context["results"] = recruiter_search(
                discipline_id=cleaned["discipline"].pk if cleaned.get("discipline") else None,
                engine_id=engines[0].pk if engines else None,
                genre_id=genres[0].pk if genres else None,
                min_rating=cleaned.get("min_rating"),
                year_from=cleaned.get("year_from"),
                open_to_work=cleaned.get("open_to_work") or None,
            )
```

- [ ] **Step 6: Full suite, gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add search/forms.py search/views.py search/tests/test_recruiter_form.py
git commit -m "feat(search): multi-select engines/genres, country filter, >=1-filter rule"
```

---

### Task 6: Service rework — multi filters, country, assembled `ResultsPage`

**Files:**
- Modify: `search/services.py` (keep `search_games` / `search_companies` / `search_people` and the module docstring untouched)
- Rewrite: `search/tests/test_recruiter_search.py`
- Modify: `search/views.py` (adapt the Task-5 bridge to the new signature)
- Modify: `templates/search/recruiter_search.html` (minimal — results loop reads `.user`)

- [ ] **Step 1: Rewrite the query + card tests**

Replace `search/tests/test_recruiter_search.py` entirely with:

```python
"""Recruiter search — the product promise, non-negotiable test zone #2.

Finds public people by *properties of the games they worked on* crossed with
their discipline (docs/01-DESIGN.md §3.6). Multi-value facets are OR within,
AND across; every credit-level filter applies to the SAME contribution.
Results are assembled PersonResult cards, paginated, ordered by display_name
(rating is a filter, never a sort)."""

from datetime import date
from typing import Any

import pytest

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Engine, Game, GameEngine, GameGenre, Genre
from search.services import (
    MATCHING_CREDITS_SHOWN,
    RESULTS_PER_PAGE,
    PersonResult,
    _percentage_shares,
    recruiter_search,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def disciplines() -> dict[str, Discipline]:
    return {d.name: d for d in Discipline.objects.all()}


def _make_person(email: str, name: str, **kwargs: object) -> User:
    return User.objects.create_user(email=email, password="x", display_name=name, **kwargs)


def _credit(user: User, game: Game, discipline: Discipline, **kwargs: object) -> Contribution:
    kwargs.setdefault("job_title", "Dev")
    kwargs.setdefault("start_date", date(2020, 1, 1))
    return Contribution.objects.create(user=user, game=game, discipline=discipline, **kwargs)


def _engine_game(title: str, *engines: Engine) -> Game:
    game = Game.objects.create(title=title, source=Game.Source.MANUAL)
    for engine in engines:
        GameEngine.objects.create(game=game, engine=engine)
    return game


def _users(**kwargs: Any) -> list[User]:
    return [r.user for r in recruiter_search(**kwargs).results]


# ---------------------------------------------------------------- filters


def test_filters_by_discipline_and_engine(disciplines: dict[str, Discipline]) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = _engine_game("UE Game", unreal)
    unity_game = Game.objects.create(title="Unity Game", source=Game.Source.MANUAL)

    programmer = _make_person("p@example.com", "Unreal Programmer")
    _credit(programmer, unreal_game, disciplines["Programming"])
    artist = _make_person("a@example.com", "Unity Artist")
    _credit(artist, unity_game, disciplines["Art"])

    results = _users(discipline_id=disciplines["Programming"].pk, engine_ids=[unreal.pk])

    assert results == [programmer]


def test_the_cross_is_within_a_single_contribution(disciplines: dict[str, Discipline]) -> None:
    """'Unreal' + 'Programming' means ONE credit is both — not two separate ones."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unreal_game = _engine_game("UE Game", unreal)
    other_game = Game.objects.create(title="Other", source=Game.Source.MANUAL)

    person = _make_person("x@example.com", "Split Person")
    _credit(person, unreal_game, disciplines["Art"])  # Unreal, but as Art
    _credit(person, other_game, disciplines["Programming"])  # Programming, but not Unreal

    assert _users(discipline_id=disciplines["Programming"].pk, engine_ids=[unreal.pk]) == []


def test_or_within_engines(disciplines: dict[str, Discipline]) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    godot = Engine.objects.create(name="Godot")

    ue_person = _make_person("ue@example.com", "A UE Person")
    _credit(ue_person, _engine_game("UE Game", unreal), disciplines["Design"])
    unity_person = _make_person("un@example.com", "B Unity Person")
    _credit(unity_person, _engine_game("Unity Game", unity), disciplines["Design"])
    godot_person = _make_person("go@example.com", "C Godot Person")
    _credit(godot_person, _engine_game("Godot Game", godot), disciplines["Design"])

    results = _users(engine_ids=[unreal.pk, unity.pk])

    assert results == [ue_person, unity_person]  # OR within the facet; godot excluded


def test_or_within_genres(disciplines: dict[str, Discipline]) -> None:
    rpg = Genre.objects.create(name="RPG")
    racing = Genre.objects.create(name="Racing")
    puzzle = Genre.objects.create(name="Puzzle")

    def genre_game(title: str, genre: Genre) -> Game:
        game = Game.objects.create(title=title, source=Game.Source.MANUAL)
        GameGenre.objects.create(game=game, genre=genre)
        return game

    rpg_person = _make_person("r@example.com", "A RPG Person")
    _credit(rpg_person, genre_game("RPG Game", rpg), disciplines["Design"])
    racing_person = _make_person("c@example.com", "B Racing Person")
    _credit(racing_person, genre_game("Racing Game", racing), disciplines["Design"])
    puzzle_person = _make_person("z@example.com", "C Puzzle Person")
    _credit(puzzle_person, genre_game("Puzzle Game", puzzle), disciplines["Design"])

    assert _users(genre_ids=[rpg.pk, racing.pk]) == [rpg_person, racing_person]


def test_multi_engine_game_matches_once(disciplines: dict[str, Discipline]) -> None:
    """A game tagged with BOTH selected engines must not duplicate the person."""
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    person = _make_person("m@example.com", "Multi Engine")
    _credit(person, _engine_game("Hybrid", unreal, unity), disciplines["Design"])

    page = recruiter_search(engine_ids=[unreal.pk, unity.pk])

    assert [r.user for r in page.results] == [person]
    assert page.results[0].matching_credits_total == 1  # one credit, not two


def test_filters_by_country(disciplines: dict[str, Discipline]) -> None:
    """Country is a PERSON-level filter, not a credit-level one."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    french = _make_person("fr@example.com", "French Person", country="FR")
    _credit(french, game, disciplines["Design"])
    swedish = _make_person("se@example.com", "Swedish Person", country="SE")
    _credit(swedish, game, disciplines["Design"])
    nowhere = _make_person("nw@example.com", "No Country")
    _credit(nowhere, game, disciplines["Design"])

    assert _users(countries=["FR"]) == [french]
    assert _users(countries=["FR", "SE"]) == [french, swedish]


def test_filters_by_minimum_rating(disciplines: dict[str, Discipline]) -> None:
    hit = Game.objects.create(title="Hit", steam_positive_pct=95, source=Game.Source.MANUAL)
    flop = Game.objects.create(title="Flop", steam_positive_pct=40, source=Game.Source.MANUAL)
    star = _make_person("s@example.com", "On A Hit")
    _credit(star, hit, disciplines["Design"])
    talented = _make_person("t@example.com", "On A Flop")
    _credit(talented, flop, disciplines["Design"])

    results = _users(min_rating=70)

    assert star in results
    assert talented not in results


def test_open_to_work_filter(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    seeker = _make_person("s@example.com", "Seeker", open_to_work=True)
    employed = _make_person("e@example.com", "Employed", open_to_work=False)
    _credit(seeker, game, disciplines["Design"])
    _credit(employed, game, disciplines["Design"])

    assert _users(open_to_work=True) == [seeker]


def test_never_returns_private_or_inactive(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    private = _make_person("pr@example.com", "Private", profile_public=False)
    _credit(private, game, disciplines["Design"])
    inactive = _make_person("in@example.com", "Inactive")
    _credit(inactive, game, disciplines["Design"], status=Contribution.Status.REMOVED)

    results = _users(discipline_id=disciplines["Design"].pk)

    assert private not in results
    assert inactive not in results


def test_a_person_appears_once_despite_multiple_matching_credits(
    disciplines: dict[str, Discipline],
) -> None:
    game1 = Game.objects.create(title="G1", source=Game.Source.MANUAL)
    game2 = Game.objects.create(title="G2", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Prolific")
    _credit(person, game1, disciplines["Design"])
    _credit(person, game2, disciplines["Design"])

    assert _users(discipline_id=disciplines["Design"].pk) == [person]


def test_no_filters_returns_all_matching_public_people(
    disciplines: dict[str, Discipline],
) -> None:
    """Service-level: the >=1-filter rule is enforced by the FORM, not here."""
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    a = _make_person("a@example.com", "Aaron")
    b = _make_person("b@example.com", "Bea")
    _credit(a, game, disciplines["Design"])
    _credit(b, game, disciplines["Art"])

    assert set(_users()) == {a, b}


# ---------------------------------------------------------------- cards


def _single_result(**kwargs: Any) -> PersonResult:
    page = recruiter_search(**kwargs)
    assert len(page.results) == 1
    return page.results[0]


def test_matching_credits_are_the_filter_satisfying_ones(
    disciplines: dict[str, Discipline],
) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    ue_game = _engine_game("UE Game", unreal)
    other = Game.objects.create(title="Other Game", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Person")
    matching = _credit(person, ue_game, disciplines["Programming"], job_title="UE Dev")
    _credit(person, other, disciplines["Programming"], job_title="Other Dev")

    result = _single_result(engine_ids=[unreal.pk])

    assert result.matching_credits == [matching]
    assert result.matching_credits_total == 1
    assert result.credits_count == 2  # career stats stay career-wide
    assert result.games_count == 2


def test_matching_credits_are_capped_with_total(disciplines: dict[str, Discipline]) -> None:
    person = _make_person("p@example.com", "Busy")
    for i in range(MATCHING_CREDITS_SHOWN + 2):
        game = Game.objects.create(title=f"Game {i}", source=Game.Source.MANUAL)
        _credit(person, game, disciplines["Design"], start_date=date(2010 + i, 1, 1))

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert len(result.matching_credits) == MATCHING_CREDITS_SHOWN
    assert result.matching_credits_total == MATCHING_CREDITS_SHOWN + 2
    assert result.more_credits_count == 2
    # Most recent first.
    starts = [c.start_date for c in result.matching_credits]
    assert starts == sorted(starts, reverse=True)


def test_years_active_with_open_end_is_present(disciplines: dict[str, Discipline]) -> None:
    game1 = Game.objects.create(title="G1", source=Game.Source.MANUAL)
    game2 = Game.objects.create(title="G2", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Veteran")
    _credit(person, game1, disciplines["Design"], start_date=date(2015, 3, 1),
            end_date=date(2018, 1, 1))
    _credit(person, game2, disciplines["Design"], start_date=date(2019, 1, 1))  # open end

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.first_year == 2015
    assert result.last_year is None  # open end = present


def test_years_active_all_ended(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Past")
    _credit(person, game, disciplines["Design"], start_date=date(2012, 1, 1),
            end_date=date(2014, 6, 1))

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.first_year == 2012
    assert result.last_year == 2014


def test_engine_shares_sum_to_100_top3_plus_other(disciplines: dict[str, Discipline]) -> None:
    person = _make_person("p@example.com", "Poly")
    engines = [Engine.objects.create(name=f"Engine {i}") for i in range(5)]
    # 4 games on Engine 0, then 1 game each on Engines 1-4 → 8 pairs total.
    for i in range(4):
        _credit(person, _engine_game(f"E0 Game {i}", engines[0]), disciplines["Design"])
    for i, engine in enumerate(engines[1:], start=1):
        _credit(person, _engine_game(f"Game {i}", engine), disciplines["Design"])

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert sum(pct for _, pct in result.engine_shares) == 100
    assert result.engine_shares[0][0] == "Engine 0"
    assert result.engine_shares[0][1] == 50  # 4 of 8 pairs
    assert result.engine_shares[-1][0] == "other"  # 5 engines → top 3 + other


def test_engine_shares_absent_without_engine_data(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="No Engine", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Person")
    _credit(person, game, disciplines["Design"])

    result = _single_result(discipline_id=disciplines["Design"].pk)

    assert result.engine_shares == []


def test_percentage_shares_largest_remainder() -> None:
    # 3 equal thirds cannot all be 33 — largest remainder pushes one to 34.
    shares = _percentage_shares({"a": 1, "b": 1, "c": 1})
    assert sorted(shares, key=lambda s: s[0]) == [("a", 34), ("b", 33), ("c", 33)]
    assert sum(pct for _, pct in shares) == 100


# ---------------------------------------------------------------- pagination


def test_results_are_paginated_and_ordered_by_display_name(
    disciplines: dict[str, Discipline],
) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(RESULTS_PER_PAGE + 5):
        person = _make_person(f"u{i}@example.com", f"Person {i:02d}")
        _credit(person, game, disciplines["Design"])

    first = recruiter_search(discipline_id=disciplines["Design"].pk, page=1)
    second = recruiter_search(discipline_id=disciplines["Design"].pk, page=2)

    assert first.total == RESULTS_PER_PAGE + 5
    assert first.num_pages == 2
    assert len(first.results) == RESULTS_PER_PAGE
    assert len(second.results) == 5
    names = [r.user.display_name for r in first.results]
    assert names == sorted(names)
    assert first.has_next and not first.has_previous
    assert second.has_previous and not second.has_next


def test_out_of_range_page_clamps(disciplines: dict[str, Discipline]) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    person = _make_person("p@example.com", "Only One")
    _credit(person, game, disciplines["Design"])

    page = recruiter_search(discipline_id=disciplines["Design"].pk, page=99)

    assert page.page_number == 1
    assert [r.user for r in page.results] == [person]
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest search/tests/test_recruiter_search.py -v 2>&1 | tail -20
```

Expected: collection error (`ImportError: cannot import name 'PersonResult'`).

- [ ] **Step 3: Rework the service**

In `search/services.py`, keep the module docstring and `search_games` / `search_companies` / `search_people` exactly as they are. Replace the imports block and everything from `def recruiter_search(` down with:

```python
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from django.contrib.postgres.search import TrigramSimilarity
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q, QuerySet

from accounts.models import User
from contributions.models import Contribution
from games.models import Company, Game

_SIMILARITY_THRESHOLD = 0.15

RESULTS_PER_PAGE = 20
MATCHING_CREDITS_SHOWN = 3
ENGINE_SHARES_SHOWN = 3
```

(imports/constants at the top — `_SIMILARITY_THRESHOLD` already exists, don't duplicate it), then after `search_people`:

```python
@dataclass(frozen=True)
class PersonResult:
    """One fully-assembled recruiter-search result card (spec
    docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md §4).
    Career stats are career-wide (all active credits), deliberately not
    filter-scoped; matching_credits are the filter-satisfying ones."""

    user: User
    matching_credits: list[Contribution]  # capped at MATCHING_CREDITS_SHOWN, recent first
    matching_credits_total: int
    credits_count: int
    games_count: int
    first_year: int | None
    last_year: int | None  # None with credits present = an open end ("present")
    engine_shares: list[tuple[str, int]]  # [("Unreal Engine", 67), ..., ("other", 5)]

    @property
    def more_credits_count(self) -> int:
        return self.matching_credits_total - len(self.matching_credits)


@dataclass(frozen=True)
class ResultsPage:
    results: list[PersonResult]
    total: int
    page_number: int
    num_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page_number > 1

    @property
    def has_next(self) -> bool:
        return self.page_number < self.num_pages

    @property
    def previous_page_number(self) -> int:
        return self.page_number - 1

    @property
    def next_page_number(self) -> int:
        return self.page_number + 1


def recruiter_search(
    *,
    discipline_id: int | None = None,
    engine_ids: Sequence[int] = (),
    genre_ids: Sequence[int] = (),
    countries: Sequence[str] = (),
    min_rating: float | None = None,
    open_to_work: bool | None = None,
    year_from: int | None = None,
    page: int = 1,
) -> ResultsPage:
    """The product promise (docs/01-DESIGN.md §3.6, docs/04 §8): public people
    filtered by properties of the games they worked on, crossed with their
    discipline. Credit-level filters apply to the SAME active contribution
    ("Unreal × Programming" means one credit is both); multi-value facets are
    OR within the facet, AND across facets; `countries` filters the person.
    Rating is a filter, never a sort — results order by display_name."""
    credits = _matching_credits(
        discipline_id=discipline_id,
        engine_ids=engine_ids,
        genre_ids=genre_ids,
        countries=countries,
        min_rating=min_rating,
        open_to_work=open_to_work,
        year_from=year_from,
    )
    users = User.objects.filter(id__in=credits.values("user_id")).order_by("display_name")
    paginator = Paginator(users, RESULTS_PER_PAGE)
    page_obj = paginator.get_page(page)
    return ResultsPage(
        results=_assemble_results(list(page_obj.object_list), credits),
        total=paginator.count,
        page_number=page_obj.number,
        num_pages=paginator.num_pages,
    )


def _matching_credits(
    *,
    discipline_id: int | None,
    engine_ids: Sequence[int],
    genre_ids: Sequence[int],
    countries: Sequence[str],
    min_rating: float | None,
    open_to_work: bool | None,
    year_from: int | None,
) -> QuerySet[Contribution]:
    # profile_public filter FIRST: private profiles are invisible to search,
    # everywhere, unconditionally (docs/01-DESIGN.md §3.4).
    credits = Contribution.objects.filter(
        status=Contribution.Status.ACTIVE,
        game__isnull=False,
        user__profile_public=True,
    )
    if discipline_id is not None:
        credits = credits.filter(discipline_id=discipline_id)
    if engine_ids:
        credits = credits.filter(game__engines__in=list(engine_ids))
    if genre_ids:
        credits = credits.filter(game__genres__in=list(genre_ids))
    if countries:
        credits = credits.filter(user__country__in=list(countries))
    if min_rating is not None:
        credits = credits.filter(
            Q(game__steam_positive_pct__gte=min_rating) | Q(game__igdb_rating__gte=min_rating)
        )
    if year_from is not None:
        credits = credits.filter(start_date__year__gte=year_from)
    if open_to_work:
        credits = credits.filter(user__open_to_work=True)
    return credits


def _assemble_results(
    users: list[User], credits: QuerySet[Contribution]
) -> list[PersonResult]:
    if not users:
        return []
    user_ids = [user.pk for user in users]

    # The credits that satisfied the filters, for the page's users only.
    # M2M `__in` joins can duplicate a credit row → distinct.
    by_user: dict[int, list[Contribution]] = defaultdict(list)
    page_credits = (
        credits.filter(user_id__in=user_ids)
        .select_related("game", "discipline")
        .order_by("-start_date")
        .distinct()
    )
    for credit in page_credits:
        by_user[credit.user_id].append(credit)  # ty: ignore[unresolved-attribute]

    # Career-wide aggregates (ALL active credits, not just matching ones).
    # Row values are Any: .values().annotate() rows are opaque to ty.
    stats: dict[int, dict[str, Any]] = {
        row["user_id"]: row
        for row in Contribution.objects.filter(
            status=Contribution.Status.ACTIVE, user_id__in=user_ids
        )
        .values("user_id")
        .annotate(
            credits_count=Count("id"),
            games_count=Count("game", distinct=True),
            first_start=Min("start_date"),
            last_end=Max("end_date"),
            open_count=Count("id", filter=Q(end_date__isnull=True)),
        )
    }

    # Engine repartition over distinct (game, engine) pairs, career-wide.
    engine_counts: dict[int, dict[str, int]] = defaultdict(dict)
    pairs = (
        Contribution.objects.filter(
            status=Contribution.Status.ACTIVE,
            user_id__in=user_ids,
            game__engines__isnull=False,
        )
        .values_list("user_id", "game_id", "game__engines__name")
        .distinct()
    )
    for user_id, _game_id, engine_name in pairs:
        counts = engine_counts[user_id]
        counts[engine_name] = counts.get(engine_name, 0) + 1

    results: list[PersonResult] = []
    for user in users:
        matching = by_user.get(user.pk, [])
        row = stats.get(user.pk, {})
        first_start = row.get("first_start")
        last_end = row.get("last_end")
        still_active = bool(row.get("open_count"))
        results.append(
            PersonResult(
                user=user,
                matching_credits=matching[:MATCHING_CREDITS_SHOWN],
                matching_credits_total=len(matching),
                credits_count=int(row.get("credits_count") or 0),
                games_count=int(row.get("games_count") or 0),
                first_year=first_start.year if first_start else None,
                last_year=None if still_active or last_end is None else last_end.year,
                engine_shares=_percentage_shares(engine_counts.get(user.pk, {})),
            )
        )
    return results


def _percentage_shares(
    counts: dict[str, int], top: int = ENGINE_SHARES_SHOWN
) -> list[tuple[str, int]]:
    """Integer percentages via largest-remainder rounding (they sum to exactly
    100), ranked descending, capped at `top` entries + an "other" bucket."""
    total = sum(counts.values())
    if not total:
        return []
    exact = {name: count * 100 / total for name, count in counts.items()}
    floors = {name: int(value) for name, value in exact.items()}
    remainder = 100 - sum(floors.values())
    by_fraction = sorted(exact, key=lambda name: (floors[name] - exact[name], name))
    for name in by_fraction[:remainder]:
        floors[name] += 1
    ranked = sorted(floors.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) <= top:
        return [(name, pct) for name, pct in ranked if pct > 0]
    head = [(name, pct) for name, pct in ranked[:top] if pct > 0]
    other = sum(pct for _, pct in ranked[top:])
    if other > 0:
        head.append(("other", other))
    return head
```

Only add `# ty: ignore[...]` comments where `uv run ty check` actually reports; remove any listed above that turn out unnecessary.

- [ ] **Step 4: Adapt the view bridge and template to the new return type**

`search/views.py` — in `RecruiterSearchView.get_context_data`, replace the Task-5 bridge with:

```python
            context["results_page"] = recruiter_search(
                discipline_id=cleaned["discipline"].pk if cleaned.get("discipline") else None,
                engine_ids=[engine.pk for engine in cleaned.get("engines") or []],
                genre_ids=[genre.pk for genre in cleaned.get("genres") or []],
                countries=list(cleaned.get("countries") or []),
                min_rating=cleaned.get("min_rating"),
                year_from=cleaned.get("year_from"),
                open_to_work=cleaned.get("open_to_work") or None,
            )
```

`templates/search/recruiter_search.html` — minimal keep-alive (the full card layout is Task 7): replace the results loop `{% for person in results %}` block with:

```html
      {% for r in results_page.results %}
        <p>
          <a href="{% url 'accounts:profile' r.user.slug %}">{{ r.user.display_name }}</a>
          {% if r.user.open_to_work %}<span class="badge">{% translate "Open to work" %}</span>{% endif %}
          {% if r.user.contactable %}
            — <a href="{% url 'contact:contact' r.user.slug %}">{% translate "Contact" %}</a>
          {% endif %}
        </p>
      {% empty %}
        <p>{% translate "No people match these filters." %}</p>
      {% endfor %}
```

- [ ] **Step 5: Run — must pass**

```bash
uv run pytest search -q
```

Expected: all search tests PASS (including the view tests, still recruiter-gated at this point).

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add search/services.py search/views.py search/tests/test_recruiter_search.py templates/search/recruiter_search.html
git commit -m "feat(search): assembled PersonResult cards, multi-value + country filters, pagination"
```

---

### Task 7: Open the view + result-card template

**Files:**
- Modify: `search/views.py` (delete `RecruiterRequiredMixin`, open + rate-limit the view, page param, `base_qs`)
- Rewrite: `templates/search/recruiter_search.html`
- Rewrite: `search/tests/test_recruiter_search_view.py`

- [ ] **Step 1: Rewrite the view tests**

Replace `search/tests/test_recruiter_search_view.py` entirely with:

```python
"""Recruiter search view — open to everyone (platform is free; findability IS
the service). Anti-scraping: >=1 filter required, IP rate limit."""

from datetime import date
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


def _candidate(name: str = "Great Candidate", **user_kwargs: object) -> User:
    design = Discipline.objects.get(name="Design")
    game = Game.objects.create(title="Card Game", source=Game.Source.MANUAL)
    user = User.objects.create_user(
        email="candidate@example.com", password="x", display_name=name, **user_kwargs
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=design,
        job_title="Level Designer",
        start_date=date(2020, 1, 1),
    )
    return user


def test_search_page_is_public(client: Client) -> None:
    response = client.get(reverse("search:recruiter_search"))
    assert response.status_code == 200
    assert b"discipline" in response.content.lower()


def test_member_is_not_redirected_to_apply(client: Client) -> None:
    member = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(member)
    assert client.get(reverse("search:recruiter_search")).status_code == 200


def test_zero_filters_shows_error_and_no_people(client: Client) -> None:
    """Anti-scraping: a filterless submit must never enumerate people."""
    _candidate()
    response = client.get(reverse("search:recruiter_search"), {"discipline": ""})
    assert b"Pick at least one filter." in response.content
    assert b"Great Candidate" not in response.content


def test_anonymous_search_returns_matches_without_leaking_email(client: Client) -> None:
    _candidate()
    design = Discipline.objects.get(name="Design")

    response = client.get(reverse("search:recruiter_search"), {"discipline": design.pk})

    assert b"Great Candidate" in response.content
    assert b"candidate@example.com" not in response.content


def test_result_card_shows_credit_location_and_stats(client: Client) -> None:
    _candidate(location="Lyon", country="FR")
    design = Discipline.objects.get(name="Design")

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert "Card Game" in content  # the matching credit
    assert "Level Designer" in content
    assert "Lyon" in content and "France" in content
    assert "1 credit" in content and "1 game" in content


def test_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("search:recruiter_search")
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 403


def test_pagination_preserves_filters(client: Client) -> None:
    design = Discipline.objects.get(name="Design")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(21):  # RESULTS_PER_PAGE + 1
        user = User.objects.create_user(
            email=f"u{i}@example.com", password="x", display_name=f"Person {i:02d}"
        )
        Contribution.objects.create(
            user=user, game=game, discipline=design,
            job_title="Dev", start_date=date(2020, 1, 1),
        )

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert f"discipline={design.pk}" in content  # filter kept in the page link
    assert "page=2" in content
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest search/tests/test_recruiter_search_view.py -v 2>&1 | tail -15
```

Expected: FAIL — anonymous gets 302 (still gated), no pagination links, etc.

- [ ] **Step 3: Rework the view**

In `search/views.py`:

1. **Delete** the whole `RecruiterRequiredMixin` class.
2. Remove now-unused imports: `messages`, `LoginRequiredMixin`, `redirect` (keep `render`), and `gettext as _` if nothing else uses it.
3. Replace `RecruiterSearchView` with:

```python
@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET", block=True), name="get")
class RecruiterSearchView(TemplateView):
    """Open to everyone — the platform is free, and showing workers that the
    recruiter-side tool exists is part of the promise (spec 2026-07-16).
    Anti-scraping: the form requires >=1 filter; IP rate limit above."""

    template_name = "search/recruiter_search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        form = RecruiterSearchForm(self.request.GET or None)
        context["form"] = form
        params = self.request.GET.copy()
        params.pop("page", None)
        context["base_qs"] = params.urlencode()
        if self.request.GET and form.is_valid():
            cleaned = form.cleaned_data
            try:
                page = int(self.request.GET.get("page", "1"))
            except ValueError:
                page = 1
            context["results_page"] = recruiter_search(
                discipline_id=cleaned["discipline"].pk if cleaned.get("discipline") else None,
                engine_ids=[engine.pk for engine in cleaned.get("engines") or []],
                genre_ids=[genre.pk for genre in cleaned.get("genres") or []],
                countries=list(cleaned.get("countries") or []),
                min_rating=cleaned.get("min_rating"),
                year_from=cleaned.get("year_from"),
                open_to_work=cleaned.get("open_to_work") or None,
                page=page,
            )
            context["searched"] = True
        return context
```

- [ ] **Step 4: Rewrite the template**

Replace `templates/search/recruiter_search.html` entirely with:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Find people" %} · Rollcall{% endblock %}

{% block extra_head %}
<style>
  .checkbox-scroll { max-height: 11rem; overflow-y: auto; border: 1px solid GrayText; padding: .35rem .6rem; }
  .checkbox-scroll ul { list-style: none; margin: 0; padding: 0; }
  .checkbox-scroll legend { font-weight: bold; }
  .person-card { border: 1px solid GrayText; padding: .6rem .8rem; margin: .6rem 0; }
  .person-card h3 { margin: 0 0 .2rem; }
  .person-card ul { margin: .3rem 0; }
  .muted { opacity: .7; }
  .pagination { margin: 1rem 0; }
</style>
{% endblock %}

{% block content %}
  <h1>{% translate "Find people by what they've worked on" %}</h1>

  <form method="get">
    {{ form.non_field_errors }}
    <p>{{ form.discipline.label_tag }} {{ form.discipline }}</p>
    <fieldset class="checkbox-scroll">
      <legend>{{ form.engines.label }} <span class="muted">— {{ form.engines.help_text }}</span></legend>
      {{ form.engines }}
    </fieldset>
    <fieldset class="checkbox-scroll">
      <legend>{{ form.genres.label }} <span class="muted">— {{ form.genres.help_text }}</span></legend>
      {{ form.genres }}
    </fieldset>
    <fieldset class="checkbox-scroll">
      <legend>{{ form.countries.label }} <span class="muted">— {{ form.countries.help_text }}</span></legend>
      {{ form.countries }}
    </fieldset>
    <p>{{ form.min_rating.label_tag }} {{ form.min_rating }}</p>
    <p>{{ form.year_from.label_tag }} {{ form.year_from }}</p>
    <p><label>{{ form.open_to_work }} {{ form.open_to_work.label }}</label></p>
    <button type="submit">{% translate "Search" %}</button>
  </form>

  {% if searched %}
    <section>
      <h2>{% blocktranslate count counter=results_page.total %}{{ counter }} result{% plural %}{{ counter }} results{% endblocktranslate %}</h2>

      {% for r in results_page.results %}
        <article class="person-card">
          <h3>
            <a href="{% url 'accounts:profile' r.user.slug %}">{{ r.user.display_name }}</a>
            {% if r.user.open_to_work %}<span class="badge">{% translate "Open to work" %}</span>{% endif %}
            {% if r.user.contactable %}
              — <a href="{% url 'contact:contact' r.user.slug %}">{% translate "Contact" %}</a>
            {% endif %}
          </h3>

          {% if r.user.location_display %}
            <p class="muted">{{ r.user.location_display }}</p>
          {% endif %}

          <ul>
            {% for c in r.matching_credits %}
              <li>
                <a href="{% url 'games:game' c.game.slug %}">{{ c.game.title }}</a>
                — {{ c.job_title }} <em>({{ c.discipline.name }})</em>
                <span class="dates">{{ c.start_date|date:"Y" }}–{% if c.end_date %}{{ c.end_date|date:"Y" }}{% else %}{% translate "present" %}{% endif %}</span>
              </li>
            {% endfor %}
          </ul>
          {% if r.more_credits_count %}
            <p class="muted">{% blocktranslate count counter=r.more_credits_count %}+{{ counter }} more matching credit{% plural %}+{{ counter }} more matching credits{% endblocktranslate %}</p>
          {% endif %}

          <p class="muted">
            {% blocktranslate count counter=r.credits_count %}{{ counter }} credit{% plural %}{{ counter }} credits{% endblocktranslate %}
            · {% blocktranslate count counter=r.games_count %}{{ counter }} game{% plural %}{{ counter }} games{% endblocktranslate %}
            · {{ r.first_year }}–{% if r.last_year %}{{ r.last_year }}{% else %}{% translate "present" %}{% endif %}
          </p>

          {% if r.engine_shares %}
            <p class="muted">{% for name, pct in r.engine_shares %}{{ name }} {{ pct }}%{% if not forloop.last %} · {% endif %}{% endfor %}</p>
          {% endif %}
        </article>
      {% empty %}
        <p>{% translate "No people match these filters." %}</p>
      {% endfor %}

      {% if results_page.num_pages > 1 %}
        <nav class="pagination">
          {% if results_page.has_previous %}
            <a href="?{{ base_qs }}&amp;page={{ results_page.previous_page_number }}">{% translate "Previous" %}</a>
          {% endif %}
          <span>{% blocktranslate with page=results_page.page_number pages=results_page.num_pages %}Page {{ page }} of {{ pages }}{% endblocktranslate %}</span>
          {% if results_page.has_next %}
            <a href="?{{ base_qs }}&amp;page={{ results_page.next_page_number }}">{% translate "Next" %}</a>
          {% endif %}
        </nav>
      {% endif %}
    </section>
  {% endif %}
{% endblock %}
```

- [ ] **Step 5: Run — must pass**

```bash
uv run pytest search -q
```

Expected: all PASS.

- [ ] **Step 6: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add search/views.py templates/search/recruiter_search.html search/tests/test_recruiter_search_view.py
git commit -m "feat(search): recruiter search open to all — rate limit, result cards, pagination"
```

---

### Task 8: Landing page points to the open search

**Files:**
- Modify: `templates/search/recruiters_landing.html:20-21`
- Modify: `search/tests/test_recruiters_landing.py`

- [ ] **Step 1: Write the failing test**

Append to `search/tests/test_recruiters_landing.py`:

```python
def test_landing_links_to_the_open_search(client: Client) -> None:
    response = client.get(reverse("search:recruiters_landing"))
    assert reverse("search:recruiter_search").encode() in response.content
```

- [ ] **Step 2: Run — must fail**

```bash
uv run pytest search/tests/test_recruiters_landing.py -v
```

Expected: the new test FAILS (no link to the search yet); the apply-link test still passes.

- [ ] **Step 3: Implement**

In `templates/search/recruiters_landing.html`, replace the last two paragraphs (lines 20–21):

```html
  <p>{% blocktranslate %}Recruiter accounts are reviewed manually.{% endblocktranslate %}</p>
  <p><a href="{% url 'accounts:recruiter_apply' %}">{% translate "Apply for a recruiter account" %}</a></p>
```

with:

```html
  <p><a href="{% url 'search:recruiter_search' %}">{% translate "Search people now" %}</a>
  — {% translate "free and open to everyone while the platform grows." %}</p>

  <p class="muted">{% blocktranslate %}Recruiter? You can also introduce yourself with a
  manually-reviewed recruiter account.{% endblocktranslate %}
  <a href="{% url 'accounts:recruiter_apply' %}">{% translate "Apply" %}</a></p>
```

- [ ] **Step 4: Run — must pass**

```bash
uv run pytest search/tests/test_recruiters_landing.py -v
```

Expected: all PASS (including `test_landing_links_to_apply` — the apply link is still there, just de-emphasized).

- [ ] **Step 5: Gate + commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
git add templates/search/recruiters_landing.html search/tests/test_recruiters_landing.py
git commit -m "feat(search): landing page CTA points to the open people search"
```

---

### Task 9: Documentation + final verification

**Files:**
- Modify: `docs/01-DESIGN.md` §3.6
- Modify: `docs/04-DATABASE-SCHEMA.md` §1
- Modify: `ROADMAP.md` (Post-roadmap additions)

- [ ] **Step 1: Update docs/01-DESIGN.md §3.6**

In the §3.6 bullet list, replace this bullet:

```markdown
- **Recruiter account with manual validation** ("do things that don't scale"): mini application form (name, company, work email, LinkedIn link) → admin approves one by one. Each validation doubles as a user interview. `role` field on user: `member`/`recruiter`/`admin`; application has `pending`/`approved`/`rejected` status.
```

with:

```markdown
- **Search open to everyone** (changed 2026-07-16, spec `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md`): the platform is 100% free for now, so the search is not gated — showing workers that the recruiter-side tool exists is part of the promise. Anti-scraping survives as a form rule (≥1 filter required — no filterless "all people" listing) plus the standard search IP rate limit.
- **Recruiter account (dormant)**: the manual-validation application flow (mini form → admin approves one by one; `role` `member`/`recruiter`/`admin`; application `pending`/`approved`/`rejected`) stays in place but no longer gates anything. Re-arm it if paid recruiter accounts return.
```

And replace this bullet:

```markdown
- **Recruiter search filters:** discipline × game engine × game genre × game rating (Steam positive % — available natively from the Hushcrasher data — and IGDB ratings for non-Steam games) × dates/years of experience × `open_to_work`. Results sorted by criteria relevance only (no trust score yet). Rating is a filter among others, **never a default sort** (penalizes talented people on failed games).
```

with:

```markdown
- **Recruiter search filters:** discipline × game engines (multi, OR within) × game genres (multi, OR within) × person's country (multi) × game rating (Steam positive % — available natively from the Hushcrasher data — and IGDB ratings for non-Steam games) × dates/years of experience × `open_to_work`. Credit-level facets cross within a SINGLE contribution. Results ordered by display name; rating is a filter among others, **never a default sort** (penalizes talented people on failed games). Result cards show matching credits, city/country, career stats (credits, distinct games, years active) and engine repartition % — all factual, no person-level score.
```

- [ ] **Step 2: Update docs/04-DATABASE-SCHEMA.md §1**

Replace the row:

```markdown
| bio, location, links… | | nullable | Optional profile fields, implementer's discretion. |
```

with:

```markdown
| country | varchar(2) | not null, default `''` | ISO 3166-1 alpha-2 (django-countries). Person-level recruiter-search filter. |
| bio, location, links… | | nullable | Optional profile fields, implementer's discretion. `location` is the free-text "city / region" display line. |
```

- [ ] **Step 3: Update ROADMAP.md**

Append to the "Post-roadmap additions" list:

```markdown
- [x] **Open recruiter search** (2026-07-16): search open to all (apply flow dormant, gate removed), multi-select engines/genres, person-level country filter (`User.country`, django-countries), rich result cards (matching credits, career stats, engine repartition %), pagination, ≥1-filter anti-scraping rule + IP rate limit. Spec: `docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md`.
```

- [ ] **Step 4: Full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
```

Expected: everything green.

- [ ] **Step 5: Browser verification (use the project's preview/dev-server tooling, never a raw Bash server)**

With `docker compose up -d db`, migrations applied and `load_dev_fixtures` loaded, start the dev server and verify:
1. Logged **out**, open `/search/recruiters/` → the form renders (no redirect).
2. Submit with no filters → "Pick at least one filter.", no people listed.
3. Pick two engines + a country → result cards show matching credits, city/country line, "N credits · M games · YYYY–present", engine percentages.
4. More than 20 matches → pagination links keep the filters.
5. `/search/for-recruiters/` → "Search people now" links to the search; apply link still present but secondary.
6. A profile page shows "City · Country"; settings shows the country dropdown and saves it.
7. View page source of a results page → no email address anywhere.

- [ ] **Step 6: Commit docs**

```bash
git add docs/01-DESIGN.md docs/04-DATABASE-SCHEMA.md ROADMAP.md
git commit -m "docs: record open recruiter search — gate removed, filters, country field"
```

---

## Self-review notes (already applied)

- **Spec coverage:** open access + guard (T7/T5), dormant recruiter flow (T7 deletes only the mixin; models/forms untouched), landing CTA (T8), multi-select OR/AND/same-credit (T5/T6), country field + settings + export + profile + fixtures (T1–T4), person-level country filter (T6), cards with matching credits/stats/engine % + largest-remainder rounding (T6/T7), pagination + param preservation (T6/T7), rate limit (T7), docs (T9). Out-of-scope items from the spec are not implemented anywhere.
- **Type consistency:** `recruiter_search(..., engine_ids, genre_ids, countries, page) -> ResultsPage`; `ResultsPage.results: list[PersonResult]`; `PersonResult.more_credits_count` property — names match across service (T6), view (T7), templates (T6/T7) and tests.
- **Known judgment calls:** `"other"` engine-shares label is an untranslated sentinel (LANGUAGES=[en] in POC); `ty: ignore` comments in T6 are indicative — add only what `ty check` actually reports.
