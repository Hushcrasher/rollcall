# Deferred Registration Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An anonymous visitor answers "which game did you work on?", fills a complete credit, and only then creates an account — the credit is preserved and published when their email is verified.

**Architecture:** Three funnel steps in the `contributions` app hold their state in the session (`contributions/funnel.py`), because no account exists yet. At step 3 the account is created and auto-logged-in, so the credit becomes a real row immediately with a new `Contribution.Status.PENDING`; `verify_email` flips it to `ACTIVE`. The mail round trip therefore carries no state and works from any device. The root page leads with the question for anonymous visitors only.

**Tech Stack:** Django 6, Python 3.12, htmx, pytest, uv + ruff + ty.

Spec: [docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md](../specs/2026-08-11-deferred-registration-funnel-design.md)

## Global Constraints

- Fully typed Python. Full gate before each commit: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`.
- `ty` has no Django plugin — reuse the accommodations already in the codebase (`AuthedHttpRequest`, `ClassVar` managers, `str(field)` bridges, `Any` for FK/descriptor access, `# ty: ignore[...]` with the exact rule name).
- Postgres runs in Docker on port **5433** (`.env` sets `POSTGRES_PORT`). Start it with `docker compose up -d db` if a test run errors on the DB connection.
- Every user-facing string goes through `{% translate %}` / `{% blocktranslate %}` in templates and `gettext_lazy as _` in Python. **UI copy is English only.**
- Commit after every task. Work on a branch off `main`: `feat/deferred-registration-funnel`.
- **Exactly one migration in this plan**, created in Task 1 (`contributions`, an `AlterField` on `status`). If any later task provokes `makemigrations`, something was changed that shouldn't have been.
- **No new write endpoint may be opened to anonymous requests.** `games:igdb_search`, `games:igdb_import` and `games:company_create` keep their `@login_required`.
- Nothing outside `status='active'` may be rendered anywhere public.
- Session values must be **JSON-serialisable** — Django's default `SESSION_SERIALIZER` is `JSONSerializer`, so `date` objects cannot be stored. The funnel stores raw form strings and re-validates them.

---

## File structure

| File | New/Modified | Responsibility |
|---|---|---|
| `contributions/models.py` | Modify | `Status.PENDING` |
| `contributions/migrations/0002_*.py` | Create | the `AlterField` |
| `accounts/views.py` | Modify | `verify_email` flip; `VerificationSentView` context; `SignupView` uses the new helper |
| `accounts/registration.py` | Create | `create_and_login` — shared by the signup page and the funnel |
| `contributions/funnel.py` | Create | session draft helpers, one place |
| `contributions/views.py` | Modify | the three funnel views |
| `contributions/urls.py` | Modify | the three funnel routes |
| `templates/contributions/_employer_field.html` | Create | the employer picker + its JS, shared by both credit forms |
| `templates/contributions/contribution_form.html` | Modify | includes the employer partial |
| `templates/contributions/declare_game.html` | Create | step 1 |
| `templates/contributions/declare_details.html` | Create | step 2 |
| `templates/contributions/declare_account.html` | Create | step 3 |
| `templates/search/people_search.html` | Modify | the root leads with the question for anonymous visitors |
| `templates/accounts/verification_sent.html` | Modify | names the waiting credit |
| `contributions/tests/test_pending_status.py` | Create | Task 1 |
| `contributions/tests/test_declare_game.py` | Create | Task 3 |
| `contributions/tests/test_declare_details.py` | Create | Task 4 |
| `contributions/tests/test_declare_account.py` | Create | Task 5 |
| `games/tests/test_home.py` | Modify | the root now leads with the question |
| `docs/01-DESIGN.md`, `ROADMAP.md` | Modify | Task 6 |

---

## Task 1: The pending status

The foundation: a credit can exist without being published. Everything public already filters on `status='active'`, so this task's job is to add the value, flip it at verification, and **prove** the invisibility rather than assume it.

**Files:**
- Modify: `contributions/models.py` (the `Status` class, ~line 38)
- Create: `contributions/migrations/0002_contribution_status_pending.py` (generated)
- Modify: `accounts/views.py` (`verify_email`, ~lines 102–111)
- Test: `contributions/tests/test_pending_status.py` (create)

**Interfaces:**
- Produces: `Contribution.Status.PENDING` (value `"pending"`). Task 5 sets it; Task 5's landing page reads it.

- [ ] **Step 1: Write the failing test**

Create `contributions/tests/test_pending_status.py`:

```python
"""`pending` — a credit that exists but is not published.

The deferred-registration funnel writes the credit at signup, before the email
is verified (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
What the email gate protects is that nothing unverified is *published*, so these
tests pin the invisibility, not the row.
"""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import email_verification_token
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def pending() -> Contribution:
    user = User.objects.create_user(email="me@example.com", password="x", display_name="Me")
    game = Game.objects.create(title="Pending Game", source=Game.Source.MANUAL)
    return Contribution.objects.create(
        user=user,
        game=game,
        discipline=Discipline.objects.get(name="Design"),
        job_title="Level Designer",
        start_date=date(2020, 1, 1),
        status=Contribution.Status.PENDING,
    )


def test_pending_is_absent_from_the_owner_profile(client: Client, pending: Contribution) -> None:
    body = client.get(pending.user.get_absolute_url()).content
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_game_page(client: Client, pending: Contribution) -> None:
    body = client.get(pending.game.get_absolute_url()).content
    assert b"Level Designer" not in body


def test_pending_is_absent_from_the_people_search(client: Client, pending: Contribution) -> None:
    response = client.get(reverse("home"), {"discipline": pending.discipline.pk})
    assert b"Me" not in response.content


def test_verifying_the_email_publishes_the_pending_credit(
    client: Client, pending: Contribution
) -> None:
    user = pending.user
    url = _verify_url(user)

    client.get(url)

    pending.refresh_from_db()
    assert pending.status == Contribution.Status.ACTIVE
    assert b"Level Designer" in client.get(user.get_absolute_url()).content


def test_verifying_twice_changes_nothing(client: Client, pending: Contribution) -> None:
    """The link is single-use, so the second hit lands on the invalid page. The
    credit must stay active either way — this pins that the flip is not undone."""
    url = _verify_url(pending.user)
    client.get(url)
    client.get(url)
    pending.refresh_from_db()
    assert pending.status == Contribution.Status.ACTIVE


def test_verification_without_a_pending_credit_still_works(client: Client) -> None:
    """The ordinary signup path has no pending credit — verification must not
    depend on one."""
    user = User.objects.create_user(email="plain@example.com", password="x", display_name="Plain")
    client.get(_verify_url(user))
    user.refresh_from_db()
    assert user.email_verified_at is not None


def _verify_url(user: User) -> str:
    return reverse(
        "accounts:verify_email",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": email_verification_token.make_token(user),
        },
    )
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest contributions/tests/test_pending_status.py -q`
Expected: FAIL at collection/fixture time — `AttributeError: type object 'Status' has no attribute 'PENDING'`.

- [ ] **Step 3: Add the status value**

In `contributions/models.py`, replace:

```python
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DISPUTED = "disputed", _("Disputed")  # dormant — never shown publicly
        REMOVED = "removed", _("Removed")  # dormant
```

with:

```python
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        # Written by the declare funnel before the email is verified: the credit
        # exists so it survives the verification mail round trip (routinely
        # opened on another device), but nothing outside `active` is rendered
        # anywhere public. Flipped by accounts.views.verify_email.
        PENDING = "pending", _("Pending verification")
        DISPUTED = "disputed", _("Disputed")  # dormant — never shown publicly
        REMOVED = "removed", _("Removed")  # dormant
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations contributions -n contribution_status_pending`
Expected: `Migrations for 'contributions': contributions/migrations/0002_contribution_status_pending.py - Alter field status on contribution`.

Open the generated file and confirm it contains **only** an `AlterField` on `status`. If it contains anything else, revert and investigate — this plan creates exactly one migration and it changes nothing but the choices.

- [ ] **Step 5: Flip the status at verification**

In `accounts/views.py`, add the import next to the other model imports:

```python
from contributions.models import Contribution
```

Then replace the body of `verify_email`'s success branch:

```python
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        messages.success(request, _("Your email is verified — you can now add credits."))
        return redirect("accounts:my_profile")
```

with:

```python
        if user.email_verified_at is None:
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email_verified_at"])
        # Publish anything the declare funnel parked before verification. update()
        # returns the row count, which is also how we know what to say.
        published = Contribution.objects.filter(
            user=user, status=Contribution.Status.PENDING
        ).update(status=Contribution.Status.ACTIVE)
        if published:
            messages.success(
                request, _("Your email is verified — your credit is now live on your profile.")
            )
        else:
            messages.success(request, _("Your email is verified — you can now add credits."))
        return redirect("accounts:my_profile")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest contributions/tests/test_pending_status.py -q`
Expected: PASS (6 passed).

- [ ] **Step 7: Run the full gate**

Run: `uv run python manage.py migrate` (apply the new migration to the dev DB)
Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **376 passed** (370 + 6).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(contributions): a credit can be pending until the email is verified"
```

---

## Task 2: Extract the employer field

Step 2 of the funnel renders the same employer picker as the credit form — a quick-pick list loaded from the chosen game, a live search, and a create path, plus ~50 lines of JS wiring them. Duplicating that is how the two copies drift. This task is a pure refactor: the existing 27 contribution tests are the regression net.

**Files:**
- Create: `templates/contributions/_employer_field.html`
- Modify: `templates/contributions/contribution_form.html`

**Interfaces:**
- Produces: `templates/contributions/_employer_field.html`, rendered with `{% include %}` inside a `<form>` whose context has `form` (a `ContributionForm`). It reads `form.company` and emits the element ids the credit form's JS already expects. Task 4 includes it.

- [ ] **Step 1: Record the baseline**

Run: `uv run pytest contributions/ -q`
Expected: PASS. Note the number — it must be identical after the refactor.

- [ ] **Step 2: Create the partial**

Create `templates/contributions/_employer_field.html` containing exactly the employer block from `contribution_form.html` — the `<div class="autocomplete" id="employer-field" …>` element and everything up to and including its closing `</div>` (the block that starts with the `{# Employer — constrained to the game's studios… #}` comment and ends after `{{ form.company.errors }}`):

```html
{% load i18n %}
{# Employer — constrained to the game's studios, then search / create.
   Shared by the credit form and the declare funnel's step 2, so the two cannot
   drift. Expects `form` (a ContributionForm) in the context, and the including
   template to carry the employer JS. #}
<div class="autocomplete" id="employer-field" data-hidden="{{ form.company.auto_id }}"
     data-employers-url="{% url 'games:game_employers' 0 %}">
  <label>{% translate "Employer company (optional)" %}</label>
  {{ form.company }}
  <p class="employer-hint">{% translate "Pick a game above to see its studios." %}</p>
  <div id="employer-quickpicks"></div>
  <div class="employer-search" hidden>
    <input type="text" class="autocomplete-input" name="q" autocomplete="off"
           placeholder="{% translate 'Search companies…' %}"
           hx-get="{% url 'search:company_autocomplete' %}" hx-trigger="keyup changed delay:250ms"
           hx-target="next .results">
    <div class="results"></div>
  </div>
  <p class="chosen">{% if form.company.value %}{{ form.instance.company }}{% endif %}</p>
  {{ form.company.errors }}
</div>
```

> Copy the block from the live file rather than trusting this transcription: if
> the two differ, the file wins and this plan's copy is stale. The only edit is
> the added `{% load i18n %}` and the replaced comment.

- [ ] **Step 3: Include it from the credit form**

In `templates/contributions/contribution_form.html`, delete the employer block you just moved and put in its place:

```html
    {% include "contributions/_employer_field.html" %}
```

Leave the `<script>` block at the bottom of `contribution_form.html` exactly where it is — Task 4 copies it into the funnel's own template rather than moving it, because it also drives the game picker, which step 2 does not have.

- [ ] **Step 4: Run the tests to verify nothing moved**

Run: `uv run pytest contributions/ -q`
Expected: PASS, the same number as Step 1.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **376 passed** — unchanged, this task adds no test.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(contributions): the employer picker becomes a shared partial"
```

---

## Task 3: Step 1 — the question

The root leads with the question for anonymous visitors; `/declare/` turns a typed title into a chosen game. Deliberately plain HTML, no JavaScript: the disambiguation happens on its own screen where there is room for it.

> **Tasks 3, 4 and 5 land as ONE commit.** The funnel is a chain: each step's
> view redirects to the next step's URL name, so `DeclareGameView` needs
> `contributions:declare_details` (Task 4) and `DeclareDetailsView` needs
> `contributions:declare_account` (Task 5). Any split commits a view that raises
> `NoReverseMatch` at request time. Implement Task 3's steps, then Task 4's, then
> Task 5's, then run one gate and make one commit. The expected count after all
> three is **396** (376 + 7 + 5 + 8).
>
> This was a decomposition error in the plan, caught at execution — twice, once
> per boundary. The lesson for future plans: a task boundary cannot cut across a
> redirect chain, because a URL name is a compile-time-invisible, runtime-hard
> dependency.

**Files:**
- Create: `contributions/funnel.py`
- Modify: `contributions/views.py`, `contributions/urls.py`
- Create: `templates/contributions/declare_game.html`
- Modify: `templates/search/people_search.html` (the `{% block content %}` opening, ~lines 49–56)
- Modify: `games/tests/test_home.py`
- Test: `contributions/tests/test_declare_game.py` (create)

**Interfaces:**
- Produces:
  - `contributions.funnel.SESSION_KEY = "declare_credit"`, `CREDIT_FIELDS: tuple[str, ...]`, and `get_draft(session) -> dict[str, str]` / `set_draft(session, draft) -> None` / `clear_draft(session) -> None`. Tasks 4 and 5 use all of them.
  - URL name `contributions:declare` at `/declare/`, view `DeclareGameView`. Tasks 4 and 5 redirect to it.

- [ ] **Step 1: Write the failing tests**

Create `contributions/tests/test_declare_game.py`:

```python
"""Step 1 of the declare funnel — turn a typed title into a chosen game.

Plain HTML on purpose: the root only carries a text box, and the picking happens
here (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
"""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.funnel import SESSION_KEY
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def test_declare_is_open_to_anonymous_visitors(client: Client) -> None:
    """The whole point: no account needed to start."""
    assert client.get(reverse("contributions:declare")).status_code == 200


def test_posting_a_title_lists_matching_games(client: Client, game: Game) -> None:
    response = client.post(reverse("contributions:declare"), {"q": "hollow"})
    assert response.status_code == 200
    assert b"Hollow Knight" in response.content


def test_picking_a_game_stores_it_and_moves_on(client: Client, game: Game) -> None:
    response = client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_details")
    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_a_junk_game_id_does_not_500(client: Client) -> None:
    """Public page, unauthenticated POST — junk must re-render, never crash."""
    for junk in ("abc", "-1", "999999999", ""):
        response = client.post(reverse("contributions:declare"), {"game": junk})
        assert response.status_code == 200, junk
        assert SESSION_KEY not in client.session, junk


def test_no_match_says_so_and_offers_the_account(client: Client) -> None:
    """igdb_search is login-gated and stays that way, so a miss converts into a
    signup rather than a dead end."""
    body = client.post(reverse("contributions:declare"), {"q": "zzzznotagame"}).content
    assert b"No match" in body
    assert reverse("accounts:signup").encode() in body


def test_home_leads_with_the_question_for_anonymous_visitors(client: Client) -> None:
    body = client.get(reverse("home")).content
    assert b"Which game did you work on?" in body
    assert reverse("contributions:declare").encode() in body


def test_home_does_not_ask_a_member(client: Client) -> None:
    """They already have an account — the invitation is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    body = client.get(reverse("home")).content
    assert b"Which game did you work on?" not in body
    assert b"Find people by what they" in body
```

In `games/tests/test_home.py`, the pitch paragraph is replaced by the question. Replace `PITCH`:

```python
PITCH = b"Add a credit to your name"
```

`test_home_is_public_and_renders_the_search_form` asserts the old `<h1>` text, which anonymous visitors no longer see — the search now sits under an `<h2>`. Replace:

```python
    assert b"Find people by what they" in response.content
```

with:

```python
    assert b"Looking for someone?" in response.content  # the search kept its place, one heading down
```

The authenticated `<h1>` is covered by `test_home_does_not_ask_a_member` in the new module, so nothing is lost.

and rename `test_home_pitches_signup_to_an_anonymous_visitor` to
`test_home_invites_an_anonymous_visitor_to_declare`, replacing its body with:

```python
def test_home_invites_an_anonymous_visitor_to_declare(client: Client) -> None:
    """Success metric #1 is workers declaring their work. The question is the
    invitation, and it is scoped to the block that carries it — base.html's nav
    would satisfy a looser assertion."""
    body = client.get(reverse("home")).content.decode()
    assert "Which game did you work on?" in body
    match = re.search(r"<form[^>]*action=\"/declare/\"[^>]*>.*?</form>", body, re.S)
    assert match is not None, "no form posting to /declare/ on the home page"
    assert 'name="q"' in match.group(0)
```

Add `import re` to that module's imports.

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest contributions/tests/test_declare_game.py games/tests/test_home.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'contributions.funnel'` on the new module, and `NoReverseMatch: 'declare' is not a valid view function or pattern name` in `test_home.py`.

- [ ] **Step 3: Create the session helpers**

Create `contributions/funnel.py`:

```python
"""Session state for the declare funnel (spec docs/superpowers/specs/
2026-08-11-deferred-registration-funnel-design.md).

Steps 1–3 run before an account exists, so the draft has nowhere to live but the
session. That is deliberate and short-lived: one tab, minutes apart. From the
moment the account is created the credit is a database row instead, because the
verification mail is routinely opened on a different device.

Values are raw form strings, never cleaned data: Django's default session
serializer is JSON, and `date` objects are not JSON-serialisable. The draft is
re-validated through ContributionForm before it is saved.
"""

from django.contrib.sessions.backends.base import SessionBase

SESSION_KEY = "declare_credit"

# The ContributionForm fields the funnel carries, in Meta order.
CREDIT_FIELDS: tuple[str, ...] = (
    "game",
    "company",
    "discipline",
    "job_title",
    "start_date",
    "end_date",
)


def get_draft(session: SessionBase) -> dict[str, str]:
    draft = session.get(SESSION_KEY)
    return dict(draft) if isinstance(draft, dict) else {}


def set_draft(session: SessionBase, draft: dict[str, str]) -> None:
    session[SESSION_KEY] = draft


def clear_draft(session: SessionBase) -> None:
    session.pop(SESSION_KEY, None)
```

- [ ] **Step 4: Add the step 1 view**

In `contributions/views.py`, add these imports to the existing blocks:

```python
from django.shortcuts import redirect
from django.views.generic import TemplateView

from contributions.funnel import get_draft, set_draft
from games.models import Game
from search.services import search_games
```

(`redirect` is already imported; do not duplicate it.)

Then add, after `EmailVerifiedRequiredMixin`:

```python
class DeclareGameView(TemplateView):
    """Step 1 — turn a typed title into a chosen game.

    Open to anonymous visitors: asking for the account before any value is the
    friction this funnel exists to remove. Plain form posts, no htmx: the root
    carries only a text box, and the disambiguation happens here.
    """

    template_name = "contributions/declare_game.html"

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        game = self._picked_game(request)
        if game is not None:
            # `request.session` is added by middleware, which `ty` cannot see —
            # the same accommodation the codebase already uses elsewhere.
            draft = get_draft(request.session)  # ty: ignore[unresolved-attribute]
            draft["game"] = str(game.pk)
            set_draft(request.session, draft)  # ty: ignore[unresolved-attribute]
            return redirect("contributions:declare_details")
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        query = self.request.POST.get("q", "") or self.request.GET.get("q", "")
        context["query"] = query
        context["games"] = search_games(query) if query.strip() else []
        return context

    @staticmethod
    def _picked_game(request: HttpRequest) -> Game | None:
        # Unauthenticated POST on a public page: `?game=abc` must re-render, not
        # 500, so the pk is filtered rather than coerced.
        pk = request.POST.get("game", "")
        return Game.objects.filter(pk=pk).first() if pk.isdigit() else None
```

Add `"DeclareGameView"` to the module's `__all__` if it has one; if `contributions/views.py` has no `__all__`, add nothing.

- [ ] **Step 5: Move the mount so the funnel can live at the root**

`contributions.urls` is currently mounted under `credits/`, so a path added there
would become `/credits/declare/`. The spec puts the funnel at `/declare/…`, and a
second URLconf would mean a second app namespace — but every test and template in
this plan reverses `contributions:declare`, so the namespace must stay single.

Move the prefix from the mount into the patterns. In `config/urls.py`, replace:

```python
    path("credits/", include("contributions.urls")),
```

with:

```python
    path("", include("contributions.urls")),
```

Then in `contributions/urls.py`, replace the whole `urlpatterns` with:

```python
urlpatterns: list[URLPattern | URLResolver] = [
    # The declare funnel — open to anonymous visitors, account at the end.
    path("declare/", views.DeclareGameView.as_view(), name="declare"),
    # Prefixed here rather than at the mount, so the funnel can sit at the root
    # under the same app namespace. These three URLs are unchanged.
    path("credits/new/", views.ContributionCreateView.as_view(), name="create"),
    path("credits/<int:pk>/edit/", views.ContributionUpdateView.as_view(), name="edit"),
    path("credits/<int:pk>/delete/", views.ContributionDeleteView.as_view(), name="delete"),
]
```

Every existing `/credits/…` URL keeps its exact path, so no test or template that
reverses `contributions:create`, `:edit` or `:delete` changes. Step 9 verifies
this rather than assuming it.

- [ ] **Step 6: Create the step 1 template**

Create `templates/contributions/declare_game.html`:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Which game did you work on?" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "Which game did you work on?" %}</h1>

  <form method="post">
    {% csrf_token %}
    <input type="search" name="q" size="35" value="{{ query }}" required
           placeholder="{% translate 'Hollow Knight, Dishonored…' %}">
    <button type="submit">{% translate "Search" %}</button>
  </form>

  {% if query %}
    {% if games %}
      <ul>
        {% for game in games %}
          <li>
            <form method="post">
              {% csrf_token %}
              <input type="hidden" name="game" value="{{ game.pk }}">
              <button type="submit">{{ game.title }}{% if game.release_date %} ({{ game.release_date|date:"Y" }}){% endif %}</button>
            </form>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p>{% translate "No match." %}</p>
    {% endif %}
    {% comment %}
      games:igdb_search is @login_required and stays that way — it is a write
      path to an external API. A miss therefore converts into a signup instead
      of a dead end.
    {% endcomment %}
    <p class="muted">{% translate "Can't find it? Create your account and we'll help you add it." %}
      <a href="{% url 'accounts:signup' %}">{% translate "Create your account" %}</a></p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 7: Lead with the question on the root**

In `templates/search/people_search.html`, replace:

```html
{% block content %}
  <h1>{% translate "Find people by what they've worked on" %}</h1>

  {% if not user.is_authenticated %}
    <p>{% blocktranslate %}Rollcall is a credits database for the video game industry.
    Declare your work, be found by recruiters for what you actually shipped.{% endblocktranslate %}
    <a href="{% url 'accounts:signup' %}">{% translate "Create your account" %}</a></p>
  {% endif %}
```

with:

```html
{% block content %}
  {% if user.is_authenticated %}
    <h1>{% translate "Find people by what they've worked on" %}</h1>
  {% else %}
    {% comment %}
      Anonymous visitors lead with the question: metric #1 is workers declaring
      their work, and a recruiter arrives with intent. This also means crawlers
      index the home page under the question — accepted knowingly (spec
      2026-08-11-deferred-registration-funnel-design.md).
    {% endcomment %}
    <h1>{% translate "Which game did you work on?" %}</h1>
    <p>{% translate "Add a credit to your name. You can create your account at the end." %}</p>
    <form method="post" action="{% url 'contributions:declare' %}">
      {% csrf_token %}
      <input type="search" name="q" size="35" required
             placeholder="{% translate 'Hollow Knight, Dishonored…' %}">
      <button type="submit">{% translate "Continue" %}</button>
    </form>

    <h2>{% translate "Looking for someone?" %}</h2>
  {% endif %}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest contributions/tests/test_declare_game.py games/tests/test_home.py -q`
Expected: PASS (7 + 3 = 10 passed).

- [ ] **Step 9: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **383 passed** (376 + 7).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

Confirm no existing credit URL moved:

Run: `uv run python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev'); django.setup(); from django.urls import reverse; print(reverse('contributions:create'), reverse('contributions:declare'))"`
Expected: `/credits/new/ /declare/`

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(contributions): ask which game you worked on, before the account"
```

---

## Task 4: Step 2 — the credit details

The game is chosen; collect the rest. Same `ContributionForm` as `/credits/new/`, minus the game picker (the game is fixed) and plus a redirect guard.

**Files:**
- Modify: `contributions/views.py` (`DeclareDetailsView`)
- Modify: `contributions/urls.py`
- Create: `templates/contributions/declare_details.html`
- Test: `contributions/tests/test_declare_details.py` (create)

**Interfaces:**
- Consumes: `contributions.funnel.get_draft` / `set_draft` / `CREDIT_FIELDS`, URL name `contributions:declare` (Task 3); `templates/contributions/_employer_field.html` (Task 2).
- Produces: URL name `contributions:declare_details` at `/declare/details/`, view `DeclareDetailsView`. Task 5 redirects back to it.

- [ ] **Step 1: Write the failing tests**

Create `contributions/tests/test_declare_details.py`:

```python
"""Step 2 of the declare funnel — the rest of the credit, still no account."""

import pytest
from django.test import Client
from django.urls import reverse

from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def _with_game(client: Client, game: Game) -> None:
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk)}
    session.save()


def test_details_needs_a_game_first(client: Client) -> None:
    """A direct hit with an empty session must land on the question, not on a
    form with no game."""
    response = client.get(reverse("contributions:declare_details"))
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare")


def test_details_is_open_to_anonymous_visitors(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.get(reverse("contributions:declare_details"))
    assert response.status_code == 200
    assert b"Hollow Knight" in response.content  # the chosen game is shown back


def test_a_valid_credit_moves_to_the_account_step(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.post(
        reverse("contributions:declare_details"),
        {
            "game": str(game.pk),
            "discipline": str(Discipline.objects.get(name="Design").pk),
            "job_title": "Level Designer",
            "start_date": "2020-01",
            "end_date": "",
        },
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_account")
    assert client.session[SESSION_KEY]["job_title"] == "Level Designer"
    assert client.session[SESSION_KEY]["start_date"] == "2020-01"


def test_nothing_is_written_to_the_database(client: Client, game: Game) -> None:
    """No account exists yet — the draft lives in the session and nowhere else."""
    _with_game(client, game)
    client.post(
        reverse("contributions:declare_details"),
        {
            "game": str(game.pk),
            "discipline": str(Discipline.objects.get(name="Design").pk),
            "job_title": "Level Designer",
            "start_date": "2020-01",
        },
    )
    assert Contribution.objects.count() == 0


def test_an_invalid_credit_re_renders_with_errors(client: Client, game: Game) -> None:
    _with_game(client, game)
    response = client.post(
        reverse("contributions:declare_details"),
        {"game": str(game.pk), "job_title": "", "start_date": ""},
    )
    assert response.status_code == 200
    assert SESSION_KEY in client.session
    assert "discipline" not in client.session[SESSION_KEY]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest contributions/tests/test_declare_details.py -q`
Expected: FAIL — `NoReverseMatch: 'declare_details' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the view**

In `contributions/views.py`, add these imports to the existing blocks:

```python
from django.views.generic import FormView

from contributions.funnel import CREDIT_FIELDS
```

Then add, after `DeclareGameView`:

```python
class DeclareDetailsView(FormView):
    """Step 2 — the rest of the credit. The game is already chosen, so this
    renders ContributionForm without its game picker."""

    template_name = "contributions/declare_details.html"
    form_class = ContributionForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if "game" not in get_draft(request.session):
            return redirect("contributions:declare")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, Any]:
        return dict(get_draft(self.request.session))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["game"] = Game.objects.filter(
            pk=get_draft(self.request.session)["game"]
        ).first()
        return context

    def form_valid(self, form: ContributionForm) -> HttpResponse:
        # Raw POST strings, not cleaned_data: the session serializer is JSON and
        # `date` is not JSON-serialisable. Step 3 re-validates through the same
        # form, so nothing is trusted on the way back in.
        draft = {field: self.request.POST.get(field, "") for field in CREDIT_FIELDS}
        set_draft(self.request.session, draft)
        return redirect("contributions:declare_account")
```

- [ ] **Step 4: Add the route**

In `contributions/urls.py`, directly under the `declare/` path:

```python
    path("declare/details/", views.DeclareDetailsView.as_view(), name="declare_details"),
```

- [ ] **Step 5: Create the step 2 template**

Create `templates/contributions/declare_details.html`:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Your credit" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "Tell us about your work" %}</h1>
  <p>{% blocktranslate with title=game.title %}On {{ title }}.{% endblocktranslate %}
    <a href="{% url 'contributions:declare' %}">{% translate "Wrong game?" %}</a></p>

  <form method="post">
    {% csrf_token %}
    {{ form.non_field_errors }}

    {# The game is fixed by step 1 — carried as the form's hidden field. #}
    {{ form.game }}
    {{ form.game.errors }}

    {% include "contributions/_employer_field.html" %}

    <p>
      <label for="{{ form.discipline.id_for_label }}">{% translate "Discipline" %}</label>
      {{ form.discipline }} {{ form.discipline.errors }}
    </p>
    <p>
      <label for="{{ form.job_title.id_for_label }}">{% translate "Job title" %}</label>
      {{ form.job_title }} {{ form.job_title.errors }}
    </p>
    <p>
      <label for="{{ form.start_date.id_for_label }}">{{ form.start_date.label }}</label>
      {{ form.start_date }} {{ form.start_date.errors }}
    </p>
    <p>
      <label for="{{ form.end_date.id_for_label }}">{{ form.end_date.label }}</label>
      {{ form.end_date }} {{ form.end_date.errors }}
      <small>{% translate "Leave empty if you're still working on it." %}</small>
    </p>

    <button type="submit">{% translate "Continue" %}</button>
  </form>

  <script>
    const COMPANY_FIELD = "{{ form.company.auto_id }}";
    const GAME_PK = "{{ game.pk }}";

    function csrfToken() {
      return document.querySelector("[name=csrfmiddlewaretoken]").value;
    }

    // The employer quick-picks for the game chosen in step 1. The credit form's
    // version reloads this when the game changes; here the game is fixed, so it
    // runs once.
    function loadEmployers() {
      const field = document.getElementById("employer-field");
      const url = field.dataset.employersUrl.replace(/0\/employers\/$/, GAME_PK + "/employers/");
      fetch(url)
        .then((response) => response.text())
        .then((html) => {
          document.getElementById("employer-quickpicks").innerHTML = html;
          field.querySelector(".employer-hint").hidden = true;
          field.querySelector(".employer-search").hidden = false;
        });
    }

    document.addEventListener("click", function (event) {
      const option = event.target.closest("#employer-field .autocomplete-option");
      if (!option) return;
      document.getElementById(COMPANY_FIELD).value = option.dataset.id;
      document.querySelector("#employer-field .chosen").textContent = option.dataset.label;
      const results = document.querySelector("#employer-field .results");
      if (results) results.innerHTML = "";
    });

    loadEmployers();
  </script>
{% endblock %}
```

> Before writing this script, open `templates/contributions/contribution_form.html`
> and read its `<script>` block. If the employer quick-pick markup it produces
> uses different class or data attribute names than the ones above, use the names
> the live template actually emits — that file is the source of truth, and the
> two must agree because they render the same partial.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest contributions/tests/test_declare_details.py -q`
Expected: PASS (5 passed).

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **388 passed** (383 + 5).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(contributions): declare step 2 — the credit details, still no account"
```

---

## Task 5: Step 3 — the account, and the credit that survives it

The last step. The account is created and auto-logged-in, so the credit becomes a real row immediately — `pending` if the email still needs verifying, `active` if it does not.

**Files:**
- Create: `accounts/registration.py`
- Modify: `accounts/views.py` (`SignupView.form_valid`, `VerificationSentView`)
- Modify: `contributions/views.py` (`DeclareAccountView`)
- Modify: `contributions/urls.py`
- Create: `templates/contributions/declare_account.html`
- Modify: `templates/accounts/verification_sent.html`
- Test: `contributions/tests/test_declare_account.py` (create)

**Interfaces:**
- Consumes: `Contribution.Status.PENDING` (Task 1); `contributions.funnel.get_draft` / `clear_draft`, `contributions:declare` (Task 3); `contributions:declare_details` (Task 4).
- Produces: `accounts.registration.create_and_login(request: HttpRequest, form: SignupForm) -> User`; URL name `contributions:declare_account` at `/declare/account/`.

- [ ] **Step 1: Write the failing tests**

Create `contributions/tests/test_declare_account.py`:

```python
"""Step 3 of the declare funnel — the account, and the credit that survives it.

Signup auto-logs-in, so the account exists before the verification mail is ever
opened. That is why the credit becomes a row here rather than waiting in the
session: the mail is routinely opened on another device.
"""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.funnel import SESSION_KEY
from contributions.models import Contribution, Discipline
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def _with_draft(client: Client, game: Game) -> None:
    session = client.session
    session[SESSION_KEY] = {
        "game": str(game.pk),
        "company": "",
        "discipline": str(Discipline.objects.get(name="Design").pk),
        "job_title": "Level Designer",
        "start_date": "2020-01",
        "end_date": "",
    }
    session.save()


SIGNUP = {
    "email": "new@example.com",
    "display_name": "New Person",
    "password1": "a-strong-passphrase-42",
    "password2": "a-strong-passphrase-42",
    "consent": "on",
}


def test_account_step_needs_a_draft(client: Client) -> None:
    response = client.get(reverse("contributions:declare_account"))
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare")


def test_signing_up_saves_the_credit_as_pending(client: Client, game: Game) -> None:
    _with_draft(client, game)

    response = client.post(reverse("contributions:declare_account"), SIGNUP)

    credit = Contribution.objects.get()
    assert credit.status == Contribution.Status.PENDING
    assert credit.user.email == "new@example.com"
    assert credit.game == game
    assert credit.job_title == "Level Designer"
    assert response["Location"] == reverse("accounts:verification_sent")
    assert len(mail.outbox) == 1  # the verification email went out
    assert SESSION_KEY not in client.session  # the draft is consumed


def test_the_pending_credit_is_not_public_yet(client: Client, game: Game) -> None:
    _with_draft(client, game)
    client.post(reverse("contributions:declare_account"), SIGNUP)

    user = User.objects.get(email="new@example.com")
    assert b"Level Designer" not in client.get(user.get_absolute_url()).content


def test_an_already_verified_member_gets_an_active_credit(client: Client, game: Game) -> None:
    """Reached through the log-in entry point: there is nothing to wait for."""
    from django.utils import timezone

    member = User.objects.create_user(
        email="known@example.com", password="x", display_name="Known"
    )
    member.email_verified_at = timezone.now()
    member.save(update_fields=["email_verified_at"])
    client.force_login(member)
    _with_draft(client, game)

    response = client.get(reverse("contributions:declare_account"))

    credit = Contribution.objects.get()
    assert credit.status == Contribution.Status.ACTIVE
    assert credit.user == member
    assert response["Location"] == member.get_absolute_url()


def test_an_unverified_member_gets_a_pending_credit(client: Client, game: Game) -> None:
    member = User.objects.create_user(email="unv@example.com", password="x", display_name="Unv")
    assert member.email_verified_at is None
    client.force_login(member)
    _with_draft(client, game)

    client.get(reverse("contributions:declare_account"))

    assert Contribution.objects.get().status == Contribution.Status.PENDING


def test_a_stale_draft_goes_back_to_the_details_step(client: Client, game: Game) -> None:
    """The draft no longer validates — send them back to fix it rather than
    dropping the credit on the floor."""
    _with_draft(client, game)
    session = client.session
    session[SESSION_KEY]["discipline"] = ""
    session.save()

    response = client.post(reverse("contributions:declare_account"), SIGNUP)

    assert response["Location"] == reverse("contributions:declare_details")
    assert Contribution.objects.count() == 0


def test_verification_sent_names_the_waiting_credit(client: Client, game: Game) -> None:
    """The verification click collects something instead of lifting a
    restriction — it is the funnel's last exit."""
    _with_draft(client, game)
    client.post(reverse("contributions:declare_account"), SIGNUP)

    body = client.get(reverse("accounts:verification_sent")).content
    assert b"Hollow Knight" in body


def test_verification_sent_is_generic_without_a_credit(client: Client) -> None:
    user = User.objects.create_user(email="plain@example.com", password="x", display_name="P")
    client.force_login(user)
    assert b"Check your inbox" in client.get(reverse("accounts:verification_sent")).content
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest contributions/tests/test_declare_account.py -q`
Expected: FAIL — `NoReverseMatch: 'declare_account' is not a valid view function or pattern name`.

- [ ] **Step 3: Extract the registration helper**

Create `accounts/registration.py`:

```python
"""Account creation, shared by the signup page and the declare funnel.

The three steps below must stay together — a funnel that created an account
without sending the verification email, or without logging in, would strand the
member. Keeping them in one place is what stops the two call sites drifting.
"""

from django.contrib.auth import login
from django.http import HttpRequest

from accounts.emails import send_verification_email
from accounts.forms import SignupForm
from accounts.models import User


def create_and_login(request: HttpRequest, form: SignupForm) -> User:
    """Create the account, send the verification email, log the user in.

    Auto-login is deliberate: the gate is on creating contributions, not on
    logging in.
    """
    user: User = form.save()
    send_verification_email(request, user)
    login(request, user)
    return user
```

In `accounts/views.py`, add `from accounts.registration import create_and_login` and replace `SignupView.form_valid`:

```python
    def form_valid(self, form: SignupForm) -> HttpResponse:
        user = form.save()
        send_verification_email(self.request, user)
        # Auto-login: the gate is on creating contributions, not on logging in.
        login(self.request, user)
        return redirect("accounts:verification_sent")
```

with:

```python
    def form_valid(self, form: SignupForm) -> HttpResponse:
        create_and_login(self.request, form)
        return redirect("accounts:verification_sent")
```

If `login` or `send_verification_email` become unused in `accounts/views.py` after this, remove those imports — `ruff check` will flag them with `F401` otherwise.

- [ ] **Step 4: Add the step 3 view**

In `contributions/views.py`, add these imports:

```python
from accounts.forms import SignupForm
from accounts.models import User
from accounts.registration import create_and_login
from contributions.funnel import clear_draft
```

Then add, after `DeclareDetailsView`:

```python
class DeclareAccountView(FormView):
    """Step 3 — create the account, then the credit.

    Signup auto-logs-in, so by the time the credit is written the FK is
    satisfiable and the verification mail carries no state at all: verifying two
    days later from a phone works, because there is a row to flip.
    """

    template_name = "contributions/declare_account.html"
    form_class = SignupForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        draft = get_draft(request.session)
        if "game" not in draft or "discipline" not in draft:
            return redirect("contributions:declare")
        if request.user.is_authenticated:
            # Already a member — nothing to sign up for.
            return self._save_credit(request, request.user)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form: SignupForm) -> HttpResponse:
        user = create_and_login(self.request, form)
        return self._save_credit(self.request, user)

    def _save_credit(self, request: HttpRequest, user: User) -> HttpResponse:
        form = ContributionForm(get_draft(request.session))
        if not form.is_valid():
            # The draft stopped validating — a game deleted, say. Send them back
            # to fix it rather than dropping the credit silently.
            return redirect("contributions:declare_details")
        credit = form.save(commit=False)
        credit.user = user
        credit.status = (
            Contribution.Status.ACTIVE
            if user.is_email_verified
            else Contribution.Status.PENDING
        )
        credit.save()
        clear_draft(request.session)
        if credit.status == Contribution.Status.ACTIVE:
            messages.success(request, _("Credit added."))
            return redirect(str(user.get_absolute_url()))
        return redirect("accounts:verification_sent")
```

- [ ] **Step 5: Add the route**

In `contributions/urls.py`, directly under the `declare/details/` path:

```python
    path("declare/account/", views.DeclareAccountView.as_view(), name="declare_account"),
```

- [ ] **Step 6: Create the step 3 template**

Create `templates/contributions/declare_account.html`:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Create your account" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "Last step — your account" %}</h1>
  <p>{% translate "Your credit is ready. Create an account to put your name on it." %}</p>

  <form method="post">
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit">{% translate "Create my account" %}</button>
  </form>

  <p>{% translate "Already have an account?" %}
    <a href="{% url 'accounts:login' %}?next={% url 'contributions:declare_account' %}">{% translate "Log in" %}</a>
    — {% translate "your credit is kept." %}</p>
{% endblock %}
```

- [ ] **Step 7: Name the waiting credit on the verification page**

In `accounts/views.py`, replace:

```python
class VerificationSentView(TemplateView):
    template_name = "accounts/verification_sent.html"
```

with:

```python
class VerificationSentView(TemplateView):
    template_name = "accounts/verification_sent.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        # Named so the verification click collects something rather than lifting
        # a restriction — it is the declare funnel's last exit.
        user: Any = self.request.user
        context["pending_credit"] = (
            Contribution.objects.filter(user=user, status=Contribution.Status.PENDING)
            .select_related("game")
            .order_by("-id")
            .first()
            if user.is_authenticated
            else None
        )
        return context
```

Replace the whole `{% block content %}` of `templates/accounts/verification_sent.html` with:

```html
{% block content %}
  {% if pending_credit %}
    <h1>{% translate "One more step" %}</h1>
    <p>{% blocktranslate with title=pending_credit.game.title %}Your credit on {{ title }} is
    saved. Verify your email to publish it — check your inbox.{% endblocktranslate %}</p>
  {% else %}
    <h1>{% translate "Check your inbox" %}</h1>
    <p>{% blocktranslate %}We sent you a verification link. Click it to confirm your
    email — you need a verified email before you can add credits.{% endblocktranslate %}</p>
  {% endif %}

  <form method="post" action="{% url 'accounts:resend_verification' %}">
    {% csrf_token %}
    <button type="submit">{% translate "Resend the verification email" %}</button>
  </form>
{% endblock %}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest contributions/tests/test_declare_account.py -q`
Expected: PASS (8 passed).

- [ ] **Step 9: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **396 passed** (388 + 8).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(contributions): declare step 3 — the account, and the credit that survives it"
```

---

## Task 6: Verify in the browser and record it

The repo's convention is that user-facing work is verified live, not only by tests.

**Files:**
- Modify: `docs/01-DESIGN.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Start the app**

```bash
docker compose up -d db
```

Then start the dev server on port 8010 (`.claude/launch.json`, config `rollcall-dev`).

- [ ] **Step 2: Walk the loop**

Log out first — the funnel is anonymous-only on the root.

1. `/` leads with "Which game did you work on?"; the people search is still there under "Looking for someone?".
2. Type a fixture game, Continue → `/declare/` lists matches; pick one.
3. `/declare/details/` shows the chosen game. **Pick an employer from the quick-picks** — this is the JS path Task 4 rewrote, and no test covers it.
4. Fill discipline, job title, start date. Continue.
5. `/declare/account/` → create an account. You land on the verification page, and it **names your game**.
6. Your profile does **not** show the credit yet. Neither does the game page, nor the people search filtered on that discipline.
7. Copy the verification link from the console email backend, open it → the message says the credit is live, and it now appears on your profile and the game page.
8. Log in as an existing verified fixture user (`devuser1@example.com` / `devpassword`), go to `/declare/`, and walk the funnel again: it skips the account step and the credit is active immediately.
9. `/credits/new/` still works unchanged for a logged-in verified member.

- [ ] **Step 3: Record the relaxation in the design doc**

In `docs/01-DESIGN.md` §3.3, add this bullet at the end of the section:

```markdown
- **Deferred registration** (added 2026-08-11, spec `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`): an anonymous visitor answers "which game did you work on?" on the home page, fills a complete credit, and creates the account last. Because signup auto-logs-in, the credit is written at that moment with `status='pending'` and published by email verification — so the verification mail, routinely opened on another device, carries no state. **This is a scoped relaxation of the email-verified gate**: what the gate protects is that nothing unverified is *published*, and a pending credit is rendered nowhere. `/credits/new/` keeps the gate unchanged, so a member who signs up the ordinary way still cannot add a credit before verifying. Nobody may record anything about another person: the funnel only ever writes the visitor's own credit.
```

- [ ] **Step 4: Record it in the roadmap**

In `ROADMAP.md`, under `## Post-roadmap additions`, add as the last bullet:

```markdown
- [x] **Deferred registration funnel** (2026-08-11): the home page asks "which game did you work on?" before it asks for anything else; the visitor fills a complete credit and creates the account at the end. The load-bearing discovery is that `SignupView` already auto-logs-in, so the account exists before the verification mail is opened — the credit becomes a row at signup with a new `Contribution.Status.PENDING` and is published by `verify_email`, which means verifying from a phone two days later works. Steps 1–3 hold raw form strings in the session (the session serializer is JSON, so `date` objects can't go there) and re-validate through `ContributionForm` before saving. The anonymous root leads with the question, so crawlers now index the home page under it — accepted knowingly. `igdb_search`, `igdb_import` and `company_create` stay `@login_required`: a game missing from the catalogue converts into a signup rather than opening a write endpoint to anonymous traffic. One migration. Spec: `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md`.
- [ ] **Referral loop** (deferred 2026-08-11, no spec yet): let a member name colleagues they worked with so Rollcall can invite them. Build the version where the invitation link lands the invited person on a *pre-filled* credit form — the data is shown only to the person it describes. Do **not** build the variant that publishes a "pending credits" list on game and company pages: a game page is public, so hiding it from search and the sitemap does not contain it, and it contradicts the rule that nobody writes another person's credit. Prerequisites: GDPR Article 14 handling and counsel review, a per-sender send limit like the contact relay's, a claim channel (pending entries without an email have none, so they shouldn't exist), and person-record dedup. Reasoning recorded in `docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md` §Deferred.
```

- [ ] **Step 5: Commit**

```bash
git add docs/01-DESIGN.md ROADMAP.md
git commit -m "docs: deferred registration; record the deferred referral loop"
```

---

## Self-review

**Spec coverage.** The flow table → Tasks 3, 4, 5. The pending status and the #6 relaxation → Task 1 (code) and Task 6 (docs). Routes → Tasks 3, 4, 5; the `contributions/urls.py` re-mount that keeps `/credits/…` unchanged is pinned in Task 3 Step 5. The root page, the h1 swap and the SEO consequence → Task 3 Steps 7 and 9, plus the comment in the template. "What an anonymous visitor cannot do" → Task 3's `test_no_match_says_so_and_offers_the_account` and the template comment; no task touches the three `@login_required` endpoints. Verification as a reward → Task 1 (the message) and Task 5 (the page). Edge cases → Task 5's tests, one per case, plus Task 4's redirect guard. Testing list → the test module in each task. Deferred → Task 6 Step 4. "Not doing" → no task adds a third-party record, touches the people search, changes `/credits/new/`, opens an anonymous write endpoint, or activates `Vouch`.

**Types and names.** `Contribution.Status.PENDING` is created in Task 1 and used in Tasks 1 and 5. `contributions.funnel`'s `SESSION_KEY`, `CREDIT_FIELDS`, `get_draft`, `set_draft`, `clear_draft` are created in Task 3 and used in Tasks 3, 4 and 5 under those exact names. `contributions:declare` (Task 3) is reversed in Tasks 3, 4 and 5; `contributions:declare_details` (Task 4) in Tasks 4 and 5; `contributions:declare_account` (Task 5) in Tasks 4 and 5. `accounts.registration.create_and_login(request, form) -> User` is created and used in Task 5 only. `_employer_field.html` is created in Task 2 and included in Task 4.

**Two things the implementer must check against the live files rather than this plan**, both flagged inline: the exact employer block copied in Task 2 Step 2, and the employer JS attribute names in Task 4 Step 5. Both are transcriptions of existing code, and the file wins if they differ.

**Test counts.** The repo is at **370** before Task 1. Task 1 adds 6 → **376**. Task 2 is a pure refactor and adds none → **376**. Task 3 adds 7 (`test_declare_game.py`) and rewrites one existing home test in place → **383**. Task 4 adds 5 → **388**. Task 5 adds 8 → **396**.
