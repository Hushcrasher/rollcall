# Profile / Account Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the eight profile fields (plus the GitHub URL) off the account page onto a dedicated `/profile/edit/`, shrink the account page to email verification + export + deletion and rename it "Account", and give the profile page a "View as member" preview plus a neutral private-profile notice.

**Architecture:** Pure routing / view / template work in the `accounts` app — no model change and **no migration**. `SettingsForm` becomes `ProfileForm` behind a new `ProfileEditView`; `SettingsView` loses its form and becomes `AccountView` (a `TemplateView`). `ProfileView` gains three context flags (`is_owner`, `preview`, `private_notice`) that switch what the same template renders. A slugless `/profile/` redirect exists because `LOGIN_REDIRECT_URL` is a plain string setting and cannot pass a slug to `reverse()`.

**Tech Stack:** Django 6, Python 3.12, htmx, pytest, uv + ruff + ty.

Spec: [docs/superpowers/specs/2026-08-04-profile-account-split-design.md](../specs/2026-08-04-profile-account-split-design.md)

## Global Constraints

- Fully typed Python. Full gate before each commit: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`.
- `ty` has no Django plugin — reuse the accommodations already in the codebase (`AuthedHttpRequest`, `ClassVar` managers, `str(field)` bridges, `Any` for FK/descriptor access, `# ty: ignore[...]` with the exact rule name).
- Postgres runs in Docker on port **5433** (`.env` sets `POSTGRES_PORT`). Start it with `docker compose up -d db` if a test run errors on the DB connection.
- Every user-facing string goes through `{% translate %}` in templates and `gettext_lazy as _` in Python.
- Commit after every task. Work on a branch off `main`: `feat/profile-account-split`.
- **No migration is created by this plan.** If `makemigrations` wants one, something was changed that shouldn't have been.

---

## File structure

| File | New/Modified | Responsibility |
|---|---|---|
| `accounts/urls.py` | Modify | the `/profile/`, `/profile/edit/`, `/account/*` routes |
| `accounts/views.py` | Modify | `my_profile_redirect`, `ProfileEditView`, `AccountView`, `ProfileView` context |
| `accounts/forms.py` | Modify | `SettingsForm` → `ProfileForm` |
| `config/settings/base.py` | Modify | `LOGIN_REDIRECT_URL` |
| `config/sitemaps.py` | Modify | robots.txt `_DISALLOW` |
| `contact/views.py` | Modify | `ReportView.success_url` reference only |
| `templates/base.html` | Modify | logo target, nav links, `.preview-bar` / `.notice` styles |
| `templates/accounts/settings.html` | Rename → `account.html` | the thin account page |
| `templates/accounts/profile_edit.html` | Create | the moved form |
| `templates/accounts/profile.html` | Modify | owner controls, preview, private notice |
| `templates/accounts/account_delete.html` | Modify | Cancel link |
| `accounts/tests/test_profile_redirect.py` | Create | `/profile/` |
| `accounts/tests/test_settings.py` | Rename → `test_account.py` | thin account page |
| `accounts/tests/test_profile_edit.py` | Create | the moved field tests |
| `accounts/tests/test_github_settings.py` | Rename → `test_github_profile_form.py` | `ProfileForm.github_url` |
| `accounts/tests/test_profile_preview.py` | Create | preview modes |
| `accounts/tests/test_profile_privacy_notice.py` | Create | the private notice |
| `games/tests/test_seo.py` | Modify | robots.txt assertion |

---

## Task 1: `/profile/` — the slugless entry point

Gives `LOGIN_REDIRECT_URL` and the nav a target that resolves the slug at request time. Also fixes the logo, which points at the account page today.

**Files:**
- Modify: `accounts/urls.py`
- Modify: `accounts/views.py` (`__all__` ~line 41, new view after `_visible_users` ~line 65)
- Modify: `config/settings/base.py:98`
- Modify: `templates/base.html:34` and `:44`
- Test: `accounts/tests/test_profile_redirect.py` (create)

**Interfaces:**
- Produces: `accounts.views.my_profile_redirect(request: AuthedHttpRequest) -> HttpResponse`, URL name `accounts:my_profile` at `/profile/`. Tasks 2–5 and the nav rely on this name.

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_profile_redirect.py`:

```python
"""/profile/ — the slugless entry point to one's own profile."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_my_profile_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:my_profile"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_my_profile_redirects_to_own_slug(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.get(reverse("accounts:my_profile"))
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:profile", kwargs={"slug": user.slug})
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest accounts/tests/test_profile_redirect.py -q`
Expected: FAIL — `NoReverseMatch: 'my_profile' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the view**

In `accounts/views.py`, after the `_visible_users` helper, add:

```python
@login_required
def my_profile_redirect(request: AuthedHttpRequest) -> HttpResponse:
    """Slugless entry point to one's own profile. LOGIN_REDIRECT_URL is a plain
    string setting and cannot pass a slug to reverse(), so the slug is resolved
    here at request time instead."""
    return redirect(request.user.get_absolute_url())
```

Add `"my_profile_redirect"` to `__all__`, keeping it alphabetically sorted (it goes between `github_activity` and `resend_verification`).

- [ ] **Step 4: Add the route**

In `accounts/urls.py`, immediately above the `# Public profile — kept last` comment:

```python
    # Own profile — slugless, so settings and templates can link without a slug.
    path("profile/", views.my_profile_redirect, name="my_profile"),
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest accounts/tests/test_profile_redirect.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Point the login landing and the nav at it**

In `config/settings/base.py:98`, replace:

```python
LOGIN_REDIRECT_URL = "accounts:settings"
```

with:

```python
LOGIN_REDIRECT_URL = "accounts:my_profile"
```

In `templates/base.html`, line 34, replace `<a href="{% url 'accounts:settings' %}">Rollcall</a>` with:

```html
      <a href="{% url 'home' %}">Rollcall</a>
```

and line 44, replace `<a href="{% url 'accounts:profile' user.slug %}">{% translate "My profile" %}</a>` with:

```html
        <a href="{% url 'accounts:my_profile' %}">{% translate "My profile" %}</a>
```

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, 347 passed.

- [ ] **Step 8: Commit**

```bash
git add accounts/urls.py accounts/views.py config/settings/base.py templates/base.html accounts/tests/test_profile_redirect.py
git commit -m "feat(accounts): slugless /profile/ entry point; login lands on the profile"
```

---

## Task 2: Rename the account surface

A pure rename — `/settings/` → `/account/`, `accounts:settings` → `accounts:account`, `SettingsView` → `AccountView`. No behavior changes. The URL rename is safe because `/settings/` is `Disallow`ed from crawlers and the POC has no inbound links to it.

**Files:**
- Modify: `accounts/urls.py` (3 paths)
- Modify: `accounts/views.py` (class name, `__all__`, 4 `reverse`/`redirect` references)
- Modify: `contact/views.py:90`
- Modify: `config/sitemaps.py:16`
- Modify: `templates/base.html:45`, `templates/accounts/account_delete.html:19`
- Rename: `templates/accounts/settings.html` → `templates/accounts/account.html`
- Rename: `accounts/tests/test_settings.py` → `accounts/tests/test_account.py`
- Test: `games/tests/test_seo.py:22`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: URL name `accounts:account` at `/account/`, view class `accounts.views.AccountView`. Task 3 replaces its body.

- [ ] **Step 1: Write the failing tests**

In `games/tests/test_seo.py`, line 22, replace `assert b"Disallow: /settings/" in body` with:

```python
    assert b"Disallow: /account/" in body
    assert b"Disallow: /profile/" in body
```

Rename the test module and update every `reverse` in it:

```bash
git mv accounts/tests/test_settings.py accounts/tests/test_account.py
```

In `accounts/tests/test_account.py`, replace all six occurrences of `reverse("accounts:settings")` with `reverse("accounts:account")`, and rename the two tests that carry the old word:
- `test_settings_requires_login` → `test_account_requires_login`
- `test_settings_exposes_the_contactable_toggle` → `test_account_exposes_the_contactable_toggle`
- `test_update_country_from_settings` → `test_update_country`

Update the module docstring to `"""Account page — edit profile + the three visibility booleans (docs/01-DESIGN.md §3.4)."""`

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest accounts/tests/test_account.py games/tests/test_seo.py -q`
Expected: FAIL — `NoReverseMatch: 'account' is not a valid view function or pattern name`, and the robots assertion fails.

- [ ] **Step 3: Rename the routes**

In `accounts/urls.py`, replace the three settings paths:

```python
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("settings/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    path("settings/export/", views.export_personal_data, name="export_data"),
```

with:

```python
    path("account/", views.AccountView.as_view(), name="account"),
    path("account/delete/", views.AccountDeleteView.as_view(), name="account_delete"),
    path("account/export/", views.export_personal_data, name="export_data"),
```

and update the section comment above them from `# Settings + GDPR (deletion, export)` to `# Account + GDPR (deletion, export)`.

- [ ] **Step 4: Rename the view and its references**

In `accounts/views.py`:
- rename `class SettingsView(LoginRequiredMixin, UpdateView):` to `class AccountView(LoginRequiredMixin, UpdateView):`
- change its `template_name` to `"accounts/account.html"` and its `success_url` to `reverse_lazy("accounts:account")`
- in `__all__`, replace `"SettingsView"` with `"AccountView"` and re-sort (it moves to just after `"AccountDeleteView"`)
- replace the remaining three `redirect("accounts:settings")` / `reverse_lazy("accounts:settings")` at lines 99, 112, 171 and 183 with `"accounts:account"`
- update the module docstring's `settings` mention to `account`

In `contact/views.py:90`, replace `success_url = reverse_lazy("accounts:settings")` with `success_url = reverse_lazy("accounts:account")`.

> These last references keep landing on the account page. The destination is
> deliberately not revisited here — only the name it is spelled with.

- [ ] **Step 5: Rename the template and its links**

```bash
git mv templates/accounts/settings.html templates/accounts/account.html
```

In `templates/accounts/account.html`, replace both `{% translate "Settings" %}` occurrences (the `{% block title %}` and the `<h1>`) with `{% translate "Account" %}`.

In `templates/accounts/account_delete.html:19`, replace `{% url 'accounts:settings' %}` with `{% url 'accounts:account' %}`.

In `templates/base.html:45`, replace the nav link with:

```html
        <a href="{% url 'accounts:account' %}">{% translate "Account" %}</a>
```

- [ ] **Step 6: Disallow the new paths from crawlers**

In `config/sitemaps.py:16`, replace:

```python
_DISALLOW = ["/admin/", "/settings/", "/credits/", "/contact/", "/report/", "/search/"]
```

with:

```python
_DISALLOW = ["/admin/", "/account/", "/profile/", "/credits/", "/contact/", "/report/", "/search/"]
```

`/profile/` covers `/profile/edit/` by prefix. It does not affect `/u/`, which stays allowed.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, 347 passed (Task 2 adds no test).

Also confirm no migration was provoked:

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(accounts): rename the settings surface to /account/"
```

---

## Task 3: Move the profile fields to `/profile/edit/`

**Files:**
- Modify: `accounts/forms.py` (`SettingsForm` → `ProfileForm`)
- Modify: `accounts/views.py` (`AccountView` loses its form; new `ProfileEditView`)
- Modify: `accounts/urls.py`
- Create: `templates/accounts/profile_edit.html`
- Modify: `templates/accounts/account.html`
- Create: `accounts/tests/test_profile_edit.py`
- Modify: `accounts/tests/test_account.py`
- Rename: `accounts/tests/test_github_settings.py` → `accounts/tests/test_github_profile_form.py`

**Interfaces:**
- Consumes: `accounts:account` (Task 2).
- Produces: `accounts.forms.ProfileForm` (same fields and `save()` contract as the old `SettingsForm`), `accounts.views.ProfileEditView`, URL name `accounts:profile_edit` at `/profile/edit/`. Tasks 4 and 5 link to `accounts:profile_edit`.

- [ ] **Step 1: Write the failing tests for the new page**

Create `accounts/tests/test_profile_edit.py` — the six field tests moved off the account page, re-aimed:

```python
"""Profile edit — the profile fields and the three visibility booleans
(docs/01-DESIGN.md §3.4), moved off the account page."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_profile_edit_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:profile_edit"))
    assert response.status_code == 302  # redirected to login


def test_profile_edit_exposes_the_contactable_toggle(client: Client, user: User) -> None:
    """The contactable toggle must be easy to find (ease of exit, no dark pattern)."""
    client.force_login(user)
    response = client.get(reverse("accounts:profile_edit"))
    assert response.status_code == 200
    assert b"contactable" in response.content


def test_update_profile_fields(client: Client, user: User) -> None:
    client.force_login(user)
    client.post(
        reverse("accounts:profile_edit"),
        {"display_name": "Renamed", "bio": "Gameplay dev", "location": "Lyon"},
    )
    user.refresh_from_db()
    assert user.display_name == "Renamed"
    assert user.bio == "Gameplay dev"


def test_saving_lands_back_on_the_profile(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.post(reverse("accounts:profile_edit"), {"display_name": "Me"})
    assert response.status_code == 302
    assert response["Location"] == user.get_absolute_url()


def test_toggle_visibility_booleans(client: Client, user: User) -> None:
    assert user.profile_public is True and user.open_to_work is False
    client.force_login(user)

    # Unchecked checkboxes aren't submitted → they become False; open_to_work on.
    client.post(
        reverse("accounts:profile_edit"),
        {"display_name": "Me", "open_to_work": "on"},
    )

    user.refresh_from_db()
    assert user.profile_public is False
    assert user.contactable is False
    assert user.open_to_work is True


def test_update_country(client: Client, user: User) -> None:
    client.force_login(user)
    client.post(
        reverse("accounts:profile_edit"),
        {"display_name": "Me", "country": "FR", "location": "Lyon"},
    )
    user.refresh_from_db()
    assert user.country.code == "FR"  # ty: ignore[unresolved-attribute]
    assert user.location == "Lyon"


def test_country_can_be_cleared(client: Client, user: User) -> None:
    user.country = "SE"  # ty: ignore[invalid-assignment]
    user.save(update_fields=["country"])
    client.force_login(user)
    client.post(reverse("accounts:profile_edit"), {"display_name": "Me", "country": ""})
    user.refresh_from_db()
    assert not user.country
```

- [ ] **Step 2: Write the failing tests for the thinned account page**

Replace the whole body of `accounts/tests/test_account.py` with:

```python
"""Account page — email verification, data export, deletion. Nothing else:
the profile fields live on /profile/edit/ (docs/superpowers/specs/
2026-08-04-profile-account-split-design.md)."""

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_account_requires_login(client: Client) -> None:
    response = client.get(reverse("accounts:account"))
    assert response.status_code == 302  # redirected to login


def test_account_offers_export_and_deletion(client: Client, user: User) -> None:
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("accounts:export_data") in body
    assert reverse("accounts:account_delete") in body


def test_account_warns_an_unverified_email(client: Client, user: User) -> None:
    assert user.email_verified_at is None
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert b"not verified yet" in response.content


def test_verified_email_gets_no_warning(client: Client, user: User) -> None:
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    client.force_login(user)
    response = client.get(reverse("accounts:account"))
    assert b"not verified yet" not in response.content


def test_account_carries_no_profile_form(client: Client, user: User) -> None:
    """The profile fields moved out — the page must not edit them any more.
    Asserted on the field names, not on <form>: base.html carries a logout form
    on every page."""
    client.force_login(user)
    body = client.get(reverse("accounts:account")).content
    for field in (b"display_name", b"contactable", b"profile_public", b"github_url", b"avatar"):
        assert field not in body
```

- [ ] **Step 3: Rename the GitHub form test module**

```bash
git mv accounts/tests/test_github_settings.py accounts/tests/test_github_profile_form.py
```

In it, replace the import `from accounts.forms import SettingsForm` with `from accounts.forms import ProfileForm`, replace all six `SettingsForm(` call sites with `ProfileForm(`, and change the module docstring to `"""ProfileForm.github_url — parse to a login and manage the cache."""`.

- [ ] **Step 4: Run them to make sure they fail**

Run: `uv run pytest accounts/tests/test_profile_edit.py accounts/tests/test_account.py accounts/tests/test_github_profile_form.py -q`
Expected: FAIL — `NoReverseMatch: 'profile_edit' ...` and `ImportError: cannot import name 'ProfileForm'`.

- [ ] **Step 5: Rename the form**

In `accounts/forms.py`, rename `class SettingsForm(forms.ModelForm):` to `class ProfileForm(forms.ModelForm):` and update its docstring to:

```python
class ProfileForm(forms.ModelForm):
    """The profile fields + the three visibility booleans (docs/01-DESIGN.md §3.4),
    plus an optional GitHub handle (stored parsed as a login)."""
```

Everything else in the class — the `github_url` field, `Meta.fields`, `__init__`, `clean_github_url`, `save` — stays byte-for-byte as it is.

- [ ] **Step 6: Split the views**

In `accounts/views.py`, replace the whole `AccountView` class with these two:

```python
class ProfileEditView(LoginRequiredMixin, UpdateView):
    """The profile fields. Slugless: the object is always the requester, so a
    slug in the URL could only ever disagree with it."""

    form_class = ProfileForm
    template_name = "accounts/profile_edit.html"

    def get_object(self, queryset: QuerySet[User] | None = None) -> User:
        return self.request.user

    def get_success_url(self) -> str:
        # Land on the profile so the member sees the result of the edit.
        return str(self.object.get_absolute_url())  # ty: ignore[unresolved-attribute]

    def form_valid(self, form: ProfileForm) -> HttpResponse:
        messages.success(self.request, _("Your profile was saved."))
        return super().form_valid(form)


class AccountView(LoginRequiredMixin, TemplateView):
    """Email verification, data export, account deletion. The profile fields
    moved to ProfileEditView."""

    template_name = "accounts/account.html"
```

Update the imports: replace `SettingsForm` with `ProfileForm` in the `from accounts.forms import (...)` block, and add `"ProfileEditView"` to `__all__` (sorted — it goes between `"ProfileView"` and `"RecruiterApplyView"`).

- [ ] **Step 7: Add the route**

In `accounts/urls.py`, directly under the `path("profile/", ...)` line from Task 1:

```python
    path("profile/edit/", views.ProfileEditView.as_view(), name="profile_edit"),
```

- [ ] **Step 8: Create the edit template**

Create `templates/accounts/profile_edit.html`:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Edit my profile" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "Edit my profile" %}</h1>

  <form method="post" enctype="multipart/form-data" novalidate>
    {% csrf_token %}
    {{ form.as_p }}
    <button type="submit">{% translate "Save" %}</button>
  </form>

  <p><a href="{% url 'accounts:my_profile' %}">{% translate "Back to my profile" %}</a></p>
{% endblock %}
```

`enctype="multipart/form-data"` is load-bearing — without it the avatar upload silently does nothing.

- [ ] **Step 9: Thin out the account template**

Replace the whole body of `templates/accounts/account.html` with:

```html
{% extends "base.html" %}
{% load i18n %}

{% block title %}{% translate "Account" %} · Rollcall{% endblock %}

{% block content %}
  <h1>{% translate "Account" %}</h1>

  {% if not user.is_email_verified %}
    <p class="warning">
      {% translate "Your email is not verified yet — verify it to add credits." %}
      <a href="{% url 'accounts:verification_sent' %}">{% translate "Resend the link" %}</a>
    </p>
  {% endif %}

  <section>
    <h2>{% translate "Your data" %}</h2>
    <p>
      <a href="{% url 'accounts:export_data' %}">{% translate "Download my data (JSON)" %}</a>
    </p>
    <p>
      <a href="{% url 'accounts:account_delete' %}">{% translate "Delete my account" %}</a>
    </p>
  </section>
{% endblock %}
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest accounts/tests/test_profile_edit.py accounts/tests/test_account.py accounts/tests/test_github_profile_form.py -q`
Expected: PASS (7 + 5 + 6 = 18 passed).

- [ ] **Step 11: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, 353 passed.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat(accounts): profile fields move to /profile/edit/; account page keeps GDPR only"
```

---

## Task 4: Owner controls and the "View as member" preview

**Files:**
- Modify: `accounts/views.py` (`ProfileView.get_context_data`, ~line 124)
- Modify: `templates/accounts/profile.html`
- Modify: `templates/base.html` (one style rule)
- Test: `accounts/tests/test_profile_preview.py` (create)

**Interfaces:**
- Consumes: `accounts:profile_edit` (Task 3).
- Produces: `ProfileView` context keys `is_owner: bool` and `preview: bool`. Task 5 adds `private_notice` alongside them.

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_profile_preview.py`:

```python
"""'View as member' — the owner previews their own profile as a logged-in
member sees it (docs/superpowers/specs/2026-08-04-profile-account-split-design.md)."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


@pytest.fixture
def other() -> User:
    return User.objects.create_user(email="you@example.com", password="x", display_name="You")


def test_owner_sees_the_edit_and_preview_links(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url()).content
    assert b"Edit my profile" in body
    assert b"View as member" in body


def test_preview_hides_every_owner_control(client: Client, user: User) -> None:
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Edit my profile" not in body
    assert b"View as member" not in body
    assert b"Add a credit" not in body
    assert b"Back to my profile" in body


def test_preview_renders_contact_inert(client: Client, user: User) -> None:
    """The label is shown so the owner knows members can reach them, but it is
    not a link: contacting yourself is refused by the relay, a dead end."""
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Contact" in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) not in body


def test_preview_hides_contact_when_not_contactable(client: Client, user: User) -> None:
    user.contactable = False
    user.save(update_fields=["contactable"])
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert b"Contact" not in body


def test_preview_param_is_inert_for_a_visitor(client: Client, user: User, other: User) -> None:
    """A third party already sees the member view — the param must not give them
    a different page, and must not strip their real Contact link."""
    client.force_login(other)
    body = client.get(user.get_absolute_url() + "?preview=member").content.decode()
    assert "Back to my profile" not in body
    assert reverse("contact:contact", kwargs={"slug": user.slug}) in body


def test_anonymous_visitor_is_unaffected(client: Client, user: User) -> None:
    response = client.get(user.get_absolute_url() + "?preview=member")
    assert response.status_code == 200
    assert b"Back to my profile" not in response.content
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest accounts/tests/test_profile_preview.py -q`
Expected: FAIL — `assert b"Edit my profile" in body` fails; the profile page has no such link yet.

- [ ] **Step 3: Compute the flags in the view**

In `accounts/views.py`, replace `ProfileView.get_context_data` with:

```python
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["contributions"] = (
            Contribution.objects.filter(user=self.object, status=Contribution.Status.ACTIVE)
            .select_related("game", "company", "discipline")
            .order_by("-start_date")
        )
        # `?preview=member` is honored for the owner only — for anyone else this
        # already *is* the member view, so the param can never change what a
        # third party sees.
        user: Any = self.request.user
        is_self = user.is_authenticated and user.pk == self.object.pk
        preview = is_self and self.request.GET.get("preview") == "member"
        context["is_owner"] = is_self and not preview
        context["preview"] = preview
        return context
```

- [ ] **Step 4: Switch the template on the flags**

In `templates/accounts/profile.html`, replace everything from `{% block content %}` down to the closing `</article>` with:

```html
{% block content %}
  {% if preview %}
    <p class="preview-bar">
      {% translate "Preview — what a logged-in member sees." %}
      <a href="{% url 'accounts:profile' profile_user.slug %}">{% translate "Back to my profile" %}</a>
    </p>
  {% endif %}

  <article>
    {% if profile_user.avatar %}
      <img src="{{ profile_user.avatar.url }}" alt="" width="120" height="120">
    {% endif %}

    <h1>{{ profile_user.display_name }}</h1>

    {% if profile_user.open_to_work %}
      <p class="badge">{% translate "Open to work" %}</p>
    {% endif %}
    {% if profile_user.location_display %}<p>{{ profile_user.location_display }}</p>{% endif %}
    {% if profile_user.bio %}<p>{{ profile_user.bio }}</p>{% endif %}

    {% if is_owner %}
      <p>
        <a href="{% url 'accounts:profile_edit' %}">{% translate "Edit my profile" %}</a>
        <a href="?preview=member">{% translate "View as member" %}</a>
      </p>
    {% endif %}

    {% if profile_user.contactable %}
      {% if preview %}
        <p><span class="muted">{% translate "Contact" %}</span></p>
      {% elif user.is_authenticated and user != profile_user %}
        <p><a href="{% url 'contact:contact' profile_user.slug %}">{% translate "Contact" %}</a></p>
      {% endif %}
    {% endif %}

    {% if preview %}
      <p><span class="muted">{% translate "Report this profile" %}</span></p>
    {% elif user.is_authenticated and user != profile_user %}
      <p><a href="{% url 'contact:report' %}?type=user&amp;id={{ profile_user.pk }}">{% translate "Report this profile" %}</a></p>
    {% endif %}
  </article>
```

Then, further down in the same file, replace both `{% if request.user == profile_user %}` guards — the one wrapping "Add a credit" and the one wrapping the per-credit Edit/Delete links — with `{% if is_owner %}`.

- [ ] **Step 5: Style the preview bar**

In `templates/base.html`, inside the `<style>` block, after the `.muted { opacity: .7; }` rule:

```css
    .preview-bar { border: 1px solid GrayText; padding: .4rem .6rem; }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest accounts/tests/test_profile_preview.py -q`
Expected: PASS (6 passed).

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, 359 passed. `accounts/tests/test_profile.py` and `test_profile_credits.py` must still pass untouched — they pin the private-profile 404 and the "email never rendered" rule.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(accounts): 'View as member' preview on the profile page"
```

---

## Task 5: The private-profile notice

`profile_public=False` hides the member everywhere, but `_visible_users` exempts the owner — so nothing tells them they are invisible. This is a neutral statement of fact, not a prompt: the flag is a safety valve, and someone hiding deliberately must not be nagged about it.

**Files:**
- Modify: `accounts/views.py` (`ProfileView.get_context_data`)
- Modify: `templates/accounts/profile.html`
- Modify: `templates/base.html` (one style rule)
- Test: `accounts/tests/test_profile_privacy_notice.py` (create)

**Interfaces:**
- Consumes: `ProfileView` context flags from Task 4, `accounts:profile_edit` from Task 3.
- Produces: `ProfileView` context key `private_notice: bool`.

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_profile_privacy_notice.py`:

```python
"""profile_public=False is a silent state: the owner keeps seeing their own
profile normally (_visible_users exempts them), so nothing would otherwise tell
them they are invisible everywhere."""

import pytest
from django.test import Client

from accounts.models import User

pytestmark = pytest.mark.django_db

NOTICE = b"Your profile is private"


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="me@example.com", password="x", display_name="Me")


def test_private_profile_warns_its_owner(client: Client, user: User) -> None:
    user.profile_public = False
    user.save(update_fields=["profile_public"])
    client.force_login(user)
    assert NOTICE in client.get(user.get_absolute_url()).content


def test_the_notice_survives_the_preview(client: Client, user: User) -> None:
    """The preview does not fake the visitor's 404 — it answers the real
    question, which is whether anyone can see the page at all."""
    user.profile_public = False
    user.save(update_fields=["profile_public"])
    client.force_login(user)
    body = client.get(user.get_absolute_url() + "?preview=member").content
    assert NOTICE in body


def test_a_public_profile_has_no_notice(client: Client, user: User) -> None:
    assert user.profile_public is True
    client.force_login(user)
    assert NOTICE not in client.get(user.get_absolute_url()).content


def test_a_visitor_never_sees_the_notice(client: Client, user: User) -> None:
    other = User.objects.create_user(email="you@example.com", password="x", display_name="You")
    client.force_login(other)
    assert NOTICE not in client.get(user.get_absolute_url()).content
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest accounts/tests/test_profile_privacy_notice.py -q`
Expected: FAIL — 2 failed (the two that expect the notice), 2 passed.

- [ ] **Step 3: Add the flag**

In `accounts/views.py`, in `ProfileView.get_context_data`, directly after the `context["preview"] = preview` line:

```python
        # profile_public=False hides the member everywhere but is invisible to
        # them, since _visible_users exempts the owner. Shown in the preview too.
        context["private_notice"] = is_self and not self.object.profile_public
```

- [ ] **Step 4: Render it**

In `templates/accounts/profile.html`, directly after `{% block content %}` and **before** the `{% if preview %}` bar:

```html
  {% if private_notice %}
    <p class="notice">
      {% translate "Your profile is private: nobody else can see this page, and you don't appear in any search." %}
      <a href="{% url 'accounts:profile_edit' %}">{% translate "Change this" %}</a>
    </p>
  {% endif %}
```

- [ ] **Step 5: Style it**

In `templates/base.html`, inside the `<style>` block, next to the `.preview-bar` rule from Task 4:

```css
    .notice { border: 1px solid GrayText; padding: .4rem .6rem; }
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest accounts/tests/test_profile_privacy_notice.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, 363 passed.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(accounts): neutral notice when your own profile is private"
```

---

## Task 6: Verify in the browser and record it

The repo's convention is that user-facing phases are verified live, not only by tests (see the Phase 3–6 entries in ROADMAP.md).

**Files:**
- Modify: `ROADMAP.md` (Post-roadmap additions section)

- [ ] **Step 1: Start the app**

```bash
docker compose up -d db
```

Then start the dev server on port 8010 (`.claude/launch.json`, config `rollcall-dev`) and log in as a fixture user.

- [ ] **Step 2: Walk the loop**

Check each by hand:
1. Login lands on your own profile, not the account page.
2. The "Rollcall" logo goes to the home page.
3. "Edit my profile" → the form has all nine fields; changing the display name and saving lands back on the profile with the new name.
4. Upload an avatar and save — it appears. (This is what a missing `enctype` would break, and no test catches it.)
5. "View as member" → owner controls gone, bar present, Contact not clickable; "Back to my profile" returns.
6. Turn "Public profile" off in the edit form → the notice appears on the profile, in both the plain and preview views.
7. `/account/` shows only the verification warning, export and delete.

- [ ] **Step 3: Record it in the roadmap**

In `ROADMAP.md`, under `## Post-roadmap additions`, add:

```markdown
- [x] **Profile / Account split** (2026-08-04): the eight profile fields + GitHub URL move from `/settings/` to `/profile/edit/`; `/settings/` becomes `/account/` and keeps only email verification, JSON export and account deletion. A slugless `/profile/` resolves `LOGIN_REDIRECT_URL`, which now lands members on their own profile. The profile page gains **View as member** (`?preview=member`, owner-only, owner controls hidden and Contact/Report rendered inert) and a neutral **private-profile notice** — `profile_public=False` hides a member everywhere while `_visible_users` keeps showing them their own page, a silent state nothing else surfaced. No migration. Spec: `docs/superpowers/specs/2026-08-04-profile-account-split-design.md`.
```

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: record the profile / account split"
```

---

## Self-review

**Spec coverage.** Routes table → Tasks 1, 2, 3. Form and views → Task 3. Three views of a profile → Task 4. Private notice → Task 5. Navigation and redirects → Tasks 1 and 2. `robots.txt` `_DISALLOW` → Task 2 Step 6. Testing → the test module in each task, matching the spec's list. The out-of-scope `ReportView` / `RecruiterApplyView` destinations are renamed but not redirected, as the spec requires. Browser verification → Task 6.

**Types and names.** `ProfileForm` is introduced in Task 3 and used under that name in Task 3's view and in `test_github_profile_form.py`. `accounts:profile_edit` is created in Task 3 and consumed in Tasks 4 and 5. `accounts:my_profile` is created in Task 1 and consumed in Tasks 1 and 3. `is_owner` / `preview` are produced in Task 4 and consumed in Tasks 4 and 5; `private_notice` is added in Task 5 only. `AccountView` is named in Task 2 and re-bodied in Task 3.

**Test counts.** The repo is at **345** before Task 1. Task 1 adds 2 → **347**. Task 2 is a pure rename and adds no test (its SEO change is an extra assertion inside an existing test) → **347**. Task 3 removes one test from the account module and adds seven on the new page → **353**. Task 4 → **359**. Task 5 → **363**.
