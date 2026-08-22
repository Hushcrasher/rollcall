# Credit form v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `MM/YYYY` date inputs, an optional country on each credit, and an employer picker that preselects the game's developer — on `/credits/new/`, credit edit, and the declare funnel's details step (they share `ContributionForm` and `_employer_field.html`).

**Architecture:** One model field + migration (`Contribution.country`), form-level changes in `contributions/forms.py`, the `games:game_employers` endpoint now renders a `<select>`, and the two templates' inline JS shrinks (no more toggle button). Display touches the three credit-line templates and the JSON export.

**Tech Stack:** Django 6, django-countries (already used for `User.country`), htmx-free fetch (existing pattern).

**Spec:** `docs/superpowers/specs/2026-08-21-credit-form-v2-design.md` — binding.

## Global Constraints

- i18n for every string; typed Python (existing `ty` accommodations only); comments state constraints; TDD.
- The seed write-surface (docs/04 §13) is untouched — `country` is a user-owned column.
- Commits DCO (`git commit -s`) ending `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; gates before each: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check`.
- Existing tests post dates as `YYYY-MM` — they must keep passing (legacy format accepted).

---

### Task 1: `MM/YYYY` date inputs

**Files:** Modify `contributions/forms.py`; Test `contributions/tests/test_forms.py` (append).

- [ ] **Step 1: Failing tests** — append (reuse the file's `game`/`discipline` fixtures and its `_data(...)`-style helper if present; otherwise build the POST dict as the existing tests do):

```python
def test_mm_yyyy_is_accepted_and_stored_as_first_of_month(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(data={"game": game.pk, "discipline": discipline.pk, "job_title": "Dev", "start_date": "08/2024"})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["start_date"] == date(2024, 8, 1)


def test_legacy_yyyy_mm_is_still_accepted(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(data={"game": game.pk, "discipline": discipline.pk, "job_title": "Dev", "start_date": "2024-08"})
    assert form.is_valid(), form.errors


@pytest.mark.parametrize("raw", ["13/2024", "8/24", "2024/08", "août 2024"])
def test_malformed_months_are_rejected_with_the_format_hint(game: Game, discipline: Discipline, raw: str) -> None:
    form = ContributionForm(data={"game": game.pk, "discipline": discipline.pk, "job_title": "Dev", "start_date": raw})
    assert not form.is_valid()
    assert "MM/YYYY" in " ".join(form.errors["start_date"])


def test_edit_form_shows_the_saved_month_as_mm_yyyy(game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(email="e@example.com", password="x", display_name="E")
    credit = Contribution.objects.create(user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2024, 8, 1))
    bound = ContributionForm(instance=credit)["start_date"]
    assert bound.value() == "08/2024"
    assert 'inputmode="numeric"' in str(bound) and 'placeholder="MM/YYYY"' in str(bound)
```

- [ ] **Step 2: Run** `uv run pytest contributions/tests/test_forms.py -q` → the new tests FAIL.

- [ ] **Step 3: Replace the widget/field** in `contributions/forms.py`:

```python
class MonthInput(forms.DateInput):
    """A text box, not the native month picker: the picker renders in the
    browser's locale ("février 2026"), and the site's date format is MM/YYYY
    everywhere (spec 2026-08-21-credit-form-v2 §3)."""

    input_type = "text"

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        base = {
            "inputmode": "numeric",
            "placeholder": "MM/YYYY",
            "pattern": "[0-9]{2}/[0-9]{4}",
            "autocomplete": "off",
        }
        super().__init__(attrs={**base, **(attrs or {})}, format="%m/%Y")


class MonthYearField(forms.DateField):
    """Stores month/year precision as a DATE with day forced to 01 (native SQL
    range/overlap ops matter for the future vouching system). Accepts MM/YYYY
    and, for older clients and tests, the legacy YYYY-MM."""

    widget = MonthInput
    default_error_messages = {"invalid": _("Enter a month as MM/YYYY, e.g. 08/2024.")}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("input_formats", ["%m/%Y", "%Y-%m"])
        super().__init__(**kwargs)
```

Update the module docstring ("month/year dates" → "MM/YYYY dates"). Check `templates/contributions/contribution_form.html` / `declare_details.html` render the field with `{{ form.start_date }}` (they do) — no template change.

- [ ] **Step 4: Run** the form tests, then `uv run pytest contributions/ -q` (funnel tests post `YYYY-MM`), then full gates.
- [ ] **Step 5: Commit** `feat(contributions): MM/YYYY date inputs replace the locale-dependent month picker`.

---

### Task 2: `Contribution.country`

**Files:** Modify `contributions/models.py`, `contributions/forms.py` (field + Meta), `templates/contributions/contribution_form.html`, `templates/contributions/declare_details.html`, `templates/accounts/profile.html`, `templates/games/game_detail.html`, `accounts/export.py`; Create `contributions/migrations/0004_contribution_country.py` (makemigrations); Test `contributions/tests/test_country.py` (new).

- [ ] **Step 1: Failing tests**

```python
"""Where a credit happened (spec 2026-08-21-credit-form-v2 §2): optional,
asked in the form, shown after the dates, exported with the member's data."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from contributions.forms import ContributionForm
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hades", source=Game.Source.MANUAL)


@pytest.fixture
def discipline() -> Discipline:
    return Discipline.objects.get(name="Programming")


def test_form_saves_the_country(game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C")
    form = ContributionForm(data={"game": game.pk, "discipline": discipline.pk, "job_title": "Dev", "start_date": "08/2024", "country": "FR"})
    assert form.is_valid(), form.errors
    credit = form.save(commit=False)
    credit.user = user
    credit.save()
    assert Contribution.objects.get(pk=credit.pk).country.code == "FR"


def test_country_is_optional(game: Game, discipline: Discipline) -> None:
    form = ContributionForm(data={"game": game.pk, "discipline": discipline.pk, "job_title": "Dev", "start_date": "08/2024"})
    assert form.is_valid(), form.errors


def test_profile_and_game_lines_show_the_country(client: Client, game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="Country Person")
    Contribution.objects.create(user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2024, 8, 1), country="FR")
    assert "08/2024 – present · France" in client.get(reverse("accounts:profile", args=[user.slug])).content.decode()
    assert "· France" in client.get(reverse("games:game", args=[game.slug])).content.decode()


def test_export_includes_the_country(client: Client, game: Game, discipline: Discipline) -> None:
    user = User.objects.create_user(email="c@example.com", password="x", display_name="C", email_verified_at=timezone.now())
    Contribution.objects.create(user=user, game=game, discipline=discipline, job_title="Dev", start_date=date(2024, 8, 1), country="FR")
    client.force_login(user)
    data = client.get(reverse("accounts:export_data")).json()
    assert data["contributions"][0]["country"] == "FR"
```

- [ ] **Step 2: Run** → ImportError / field errors.

- [ ] **Step 3: Model + migration + form + templates + export**

`contributions/models.py` (import `from django_countries.fields import CountryField`), after `end_date`:

```python
    # Where the work happened — the person's country is on the profile; a
    # career can span several (spec 2026-08-21-credit-form-v2 §2). Optional.
    country = CountryField(_("country"), blank=True)
```

`uv run python manage.py makemigrations contributions -n contribution_country`.

`contributions/forms.py`: `Meta.fields` → `[..., "start_date", "end_date", "country"]`; add `help_texts = {"country": _("Where this work happened.")}` in `Meta` (label comes from the model's verbose name → "Country"). The form's `country` uses django-countries' default select widget (same as `ProfileForm`).

Templates — after the `end_date` paragraph in BOTH `contribution_form.html` and `declare_details.html`:

```html
    <p>
      <label for="{{ form.country.id_for_label }}">{{ form.country.label }}</label>
      {{ form.country }} {{ form.country.errors }}
      <small>{{ form.country.help_text }}</small>
    </p>
```

Credit lines — `templates/accounts/profile.html` and `templates/games/game_detail.html`, inside the `.dates` span after the end date / "present": `{% if c.country %} · {{ c.country.name }}{% endif %}`.

`accounts/export.py` contributions entry: `"country": c.country.code or None,`.

- [ ] **Step 4: Run** the new tests + `contributions/ accounts/ games/` suites; full gates. `docs/04-DATABASE-SCHEMA.md` §8 gets the column (Task 4 collects docs, but add the row now so the migration and the schema doc land together).
- [ ] **Step 5: Commit** `feat(contributions): optional country on each credit (migration 0004)`.

---

### Task 3: Employer picker

**Files:** Modify `games/views.py` (`game_employers`), `templates/games/_employer_options.html`, `templates/contributions/_employer_field.html`, `templates/contributions/contribution_form.html` (JS), `templates/contributions/declare_details.html` (JS); Test `games/tests/test_employer.py` (edit + append), `contributions/tests/test_views.py` (append).

- [ ] **Step 1: Failing tests** — in `games/tests/test_employer.py`, the three existing `game_employers` tests assert quick-pick buttons; rewrite their assertions for the select (keep their names/intent: lists the game's companies, dedupes, orders), and append:

```python
def test_employer_select_preselects_the_developer_and_offers_the_two_escapes(client: Client) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    dev = Company.objects.create(name="Dev Studio", source=Company.Source.MANUAL)
    pub = Company.objects.create(name="Pub Corp", source=Company.Source.MANUAL)
    GameCompany.objects.create(game=game, company=pub, role=GameCompany.Role.PUBLISHER)
    GameCompany.objects.create(game=game, company=dev, role=GameCompany.Role.DEVELOPER)
    body = client.get(reverse("games:game_employers", args=[game.pk])).content.decode()
    assert "<select" in body
    assert re.search(rf'<option value="{dev.pk}" selected>Dev Studio \(', body)
    assert body.index("Dev Studio") < body.index("Pub Corp")
    assert '<option value="">No employer / freelance</option>' in body
    assert '<option value="__other">Another company…</option>' in body


def test_employer_select_without_companies_defaults_to_no_employer(client: Client) -> None:
    game = Game.objects.create(title="Solo", source=Game.Source.MANUAL)
    body = client.get(reverse("games:game_employers", args=[game.pk])).content.decode()
    assert '<option value="" selected>No employer / freelance</option>' in body


def test_employer_select_keeps_a_saved_company_that_is_not_linked_to_the_game(client: Client) -> None:
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    other = Company.objects.create(name="Outsourcing Ltd", source=Company.Source.MANUAL)
    body = client.get(reverse("games:game_employers", args=[game.pk]), {"selected": other.pk}).content.decode()
    assert re.search(rf'<option value="{other.pk}" selected>Outsourcing Ltd', body)
```

In `contributions/tests/test_views.py` append a test that the edit page carries the saved company for the JS: `data-selected="<company pk>"` on `#employer-field` (create a credit with a company, GET its edit URL as the owner, assert the attribute).

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Endpoint + partials + JS**

`games/views.py::game_employers`: read `selected = request.GET.get("selected")`; after building `employers`, if `selected` is a digit string and not among the ids, look the company up (`Company.objects.filter(pk=selected).first()`) and append `{"id": …, "name": …, "role": _("current employer")}`; pass `selected_id` (int or None) to the template. Selection rule: `selected_id` if given and present, else the first employer, else `""`.

`templates/games/_employer_options.html`:

```html
{% load i18n %}
{# A select, developer first and preselected: the common case needs no click
   (spec 2026-08-21-credit-form-v2 §1). The two trailing options are the escapes. #}
<select id="employer-select" class="employer-select" aria-label="{% translate 'Employer' %}">
  {% for employer in employers %}
    <option value="{{ employer.id }}"{% if employer.id == selected_id %} selected{% endif %}>{{ employer.name }} ({{ employer.role }})</option>
  {% endfor %}
  <option value=""{% if selected_id is None %} selected{% endif %}>{% translate "No employer / freelance" %}</option>
  <option value="__other">{% translate "Another company…" %}</option>
</select>
```

(`selected_id` is `None` when nothing should be preselected — i.e. no employers and no saved company.)

`templates/contributions/_employer_field.html`: label `{% translate "Employer" %}`; hint `{% translate "Pick a game first." %}`; add `data-selected="{{ form.instance.company_id|default_if_none:'' }}"` on `#employer-field`; keep `#employer-quickpicks` (it now receives the select), `.employer-search` (hidden), `.chosen`, errors. Drop the `(optional)` wording.

JS, `contribution_form.html`: `loadEmployers(gameId, reset)` fetches `url + (selected ? "?selected=" + selected : "")` where `selected` = `field.dataset.selected` only on the initial load (not after a game change); after injecting the HTML, call `applyEmployerSelect(field)` which: reads `#employer-select`, writes its value into the hidden `COMPANY_FIELD` (empty for `""`), sets `.chosen` to the option text, hides `.employer-search`; and wires `change` → same, except `__other` → clear hidden, reveal search + focus. Remove the `.employer-other-toggle` handler. On page load: if `document.getElementById(GAME_FIELD).value` → `loadEmployers(value, false)` (edit form). The existing autocomplete-pick handler keeps `if (wrapper.dataset.hidden === GAME_FIELD) loadEmployers(id, true)`; a company picked from the search still fills hidden + `.chosen` (unchanged).
`declare_details.html`: same `applyEmployerSelect` (copy the function — the two templates already duplicate their JS on purpose, see their comments) and `loadEmployers()` calling the endpoint once; remove the toggle handler.

- [ ] **Step 4: Run** `games/tests/test_employer.py contributions/ -q`, then full gates. Manually sanity-check (controller) that picking a game preselects the developer, `Another company…` reveals the search, and the declare funnel step 2 shows the select.
- [ ] **Step 5: Commit** `feat(contributions): employer picker — the game's companies in a select, developer preselected`.

---

### Task 4: Docs, gates, browser check

- [ ] `docs/01-DESIGN.md` §3.3: MM/YYYY entry, country on a credit (shown after the dates, not yet a filter), employer picker (developer preselected, "No employer / freelance", "Another company…"). `docs/04` §8: `country` column (if not done in Task 2). `ROADMAP.md`: Phase 12 block — "Credit form v2 ✅ (spec 2026-08-21)" with the three items and a `- [ ]` follow-up "country as a recruiter filter".
- [ ] Gates incl. `docker build -q .`; `uv run python manage.py migrate` on the dev DB (controller).
- [ ] Controller browser check: `/credits/new/` (logged-in verified user): pick a game → select shows the developer preselected; `Another company…` reveals the search; dates accept `08/2024` and reject `août 2024`; country select present; profile line shows `· France`; declare funnel step 2 shows the select.
- [ ] Commit `docs: record credit form v2 (MM/YYYY, credit country, employer picker)`.
