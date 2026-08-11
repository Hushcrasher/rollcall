# The Home Page Becomes the People Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the open people search at `/`, retire the menu home page and the "For recruiters" promise page, keep the pitch for anonymous visitors, and stop the IP rate limit from applying to the bare front door.

**Architecture:** Pure routing / view / template work across the `search`, `games` and `config` layers — no model change and **no migration**. `RecruiterSearchView` is renamed `PeopleSearchView` and mounted on `""` in `config/urls.py` under the existing URL name `home`, so `{% url 'home' %}` keeps resolving everywhere. Its class-level `@ratelimit` decorator becomes a conditional check inside `get()` so only requests carrying a query string spend quota. `RecruitersLandingView` and `templates/home.html` are deleted outright.

**Tech Stack:** Django 6, Python 3.12, htmx, django-ratelimit, pytest, uv + ruff + ty.

Spec: [docs/superpowers/specs/2026-08-11-home-is-people-search-design.md](../specs/2026-08-11-home-is-people-search-design.md)

## Global Constraints

- Fully typed Python. Full gate before each commit: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`.
- `ty` has no Django plugin — reuse the accommodations already in the codebase (`AuthedHttpRequest`, `ClassVar` managers, `str(field)` bridges, `Any` for FK/descriptor access, `# ty: ignore[...]` with the exact rule name).
- Postgres runs in Docker on port **5433** (`.env` sets `POSTGRES_PORT`). Start it with `docker compose up -d db` if a test run errors on the DB connection.
- Every user-facing string goes through `{% translate %}` in templates and `gettext_lazy as _` in Python.
- Commit after every task. Work on a branch off `main`: `feat/home-is-people-search`.
- **No migration is created by this plan.** If `makemigrations` wants one, something was changed that shouldn't have been.
- The search itself is out of scope: `recruiter_search()` in `search/services.py`, `RecruiterSearchForm` in `search/forms.py`, the filters, the result cards and the pagination are **not** touched. If a filter or result-card test needs editing, something moved that shouldn't have.

---

## File structure

| File | New/Modified | Responsibility |
|---|---|---|
| `search/views.py` | Modify | drop `RecruitersLandingView`; rename + re-body `RecruiterSearchView` → `PeopleSearchView` |
| `search/urls.py` | Modify | drop the `for-recruiters/` and `recruiters/` routes |
| `config/urls.py` | Modify | mount `PeopleSearchView` on `""` under the name `home` |
| `config/sitemaps.py` | Modify | `_ALLOW` / `_DISALLOW` for the moved crawl trap |
| `accounts/views.py` | Modify | one `redirect()` target rename |
| `templates/home.html` | **Delete** | the menu page |
| `templates/search/recruiters_landing.html` | **Delete** | the promise page |
| `templates/search/recruiter_search.html` | Rename → `people_search.html` | the root page: pitch + form + results + canonical |
| `templates/base.html` | Modify | footer link out; nav search placeholder + width |
| `games/tests/test_home.py` | Rewrite | the root is the search, with the anonymous pitch |
| `games/tests/test_seo.py` | Modify | robots assertions for the moved trap |
| `search/tests/test_recruiters_landing.py` | **Delete** | with the page |
| `search/tests/test_recruiter_search_view.py` | Rename → `test_people_search_view.py` | reverses + the rate-limit tests |
| `search/tests/test_filter_autocomplete.py` | Modify | one reverse |
| `search/tests/test_nav_search_box.py` | Create | the nav placeholder |
| `docs/01-DESIGN.md`, `ROADMAP.md` | Modify | §3.6 and the roadmap entry |

---

## Task 1: Retire the "For recruiters" page

Done first, before the root moves, so no task edits a file another task is about to delete. The page's view, template, tests, footer link, home-page link and robots.txt carve-out all go together — leaving any one of them behind is a `NoReverseMatch` on every page of the site.

**Files:**
- Modify: `search/urls.py:10`
- Modify: `search/views.py` (delete `RecruitersLandingView`, lines ~42–52, and two imports that become unused)
- Delete: `templates/search/recruiters_landing.html`
- Delete: `search/tests/test_recruiters_landing.py`
- Modify: `templates/base.html:74`
- Modify: `templates/home.html:19`
- Modify: `config/sitemaps.py` (`_ALLOW` and its comment)
- Modify: `games/tests/test_seo.py` (the promise-page test)
- Modify: `games/tests/test_home.py:14`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. `search:recruiters_landing` ceases to exist as a URL name; `accounts:recruiter_apply` survives, routed but unlinked.

- [ ] **Step 1: Write the failing test**

In `games/tests/test_seo.py`, replace the whole `test_robots_txt_opens_the_promise_page_but_not_the_filter_search` function (its docstring included) with:

```python
def test_robots_txt_keeps_content_pages_and_denies_private_areas(client: Client) -> None:
    """Asserted by parsing the response with a real robots parser rather than
    grepping for the lines: a rule can be present and still be silently inert
    under first-match parsers if it is emitted in the wrong order (verified:
    `urllib.robotparser` is one of them). This fails if a rule is dropped OR
    merely reordered.
    """
    body = client.get("/robots.txt").content.decode()

    parser = RobotFileParser()
    parser.parse(body.splitlines())

    assert parser.can_fetch("*", "/u/someone/")  # public profiles are the SEO channel
    assert parser.can_fetch("*", "/g/some-game/")
    assert parser.can_fetch("*", "/c/some-studio/")
    assert not parser.can_fetch("*", "/search/")
    assert not parser.can_fetch("*", "/account/")
    # No carve-out survives the promise page it was written for.
    assert not parser.can_fetch("*", "/search/for-recruiters/")
```

In the same file, delete `test_robots_txt_opens_the_promise_page_but_not_the_filter_search` if it is still present after the replacement above.

In `games/tests/test_home.py`, delete this line only (line 14) and leave the rest of the module alone — Task 2 rewrites it:

```python
    assert reverse("search:recruiters_landing").encode() in response.content
```

Delete the test module for the page:

```bash
git rm search/tests/test_recruiters_landing.py
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest games/tests/test_seo.py -q`
Expected: FAIL — `test_robots_txt_keeps_content_pages_and_denies_private_areas` fails on its **last** assertion, `assert not parser.can_fetch("*", "/search/for-recruiters/")`: the `Allow` carve-out is still emitted, so the parser still grants the page.

> Only that one assertion is red. The other five describe rules this task does
> not change, and they pass before and after — that is the point of keeping them
> in the same test: it fails if the carve-out removal takes a neighbouring rule
> with it.

- [ ] **Step 3: Drop the route**

In `search/urls.py`, delete this line entirely:

```python
    path("for-recruiters/", views.RecruitersLandingView.as_view(), name="recruiters_landing"),
```

- [ ] **Step 4: Drop the view and its now-unused imports**

In `search/views.py`, delete the whole `RecruitersLandingView` class:

```python
class RecruitersLandingView(TemplateView):
    """Public promise page. Honest, real counts — no inflated counters."""

    template_name = "search/recruiters_landing.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["public_profiles"] = User.objects.filter(profile_public=True).count()
        context["games"] = Game.objects.count()
        return context
```

That class held the only uses of two imports. Delete this line:

```python
from accounts.models import User
```

and narrow this one:

```python
from games.models import Engine, Game, Genre
```

to:

```python
from games.models import Engine, Genre
```

`Engine` and `Genre` stay — `_reference_options` still uses them. Leaving `User` or `Game` behind fails `ruff check` with `F401`.

- [ ] **Step 5: Delete the templates' links and the page itself**

```bash
git rm templates/search/recruiters_landing.html
```

In `templates/base.html`, delete line 74 from the footer nav:

```html
      <a href="{% url 'search:recruiters_landing' %}">{% translate "For recruiters" %}</a>
```

In `templates/home.html`, delete line 19:

```html
    <li><a href="{% url 'search:recruiters_landing' %}">{% translate "For recruiters" %}</a></li>
```

- [ ] **Step 6: Drop the robots.txt carve-out**

In `config/sitemaps.py`, replace the whole `_ALLOW` block — the long comment above it and the assignment — with:

```python
# Emitted BEFORE the disallows, and that order is load-bearing. RFC 9309 §2.2.2
# picks the longest match, but parsers with first-match semantics — Python's own
# `urllib.robotparser` among them — take whichever rule they read first.
# Allow-first is correct under both.
#
# Public profile, game and company pages are a major acquisition channel ("who
# worked on X"), so they are explicitly opened despite the disallows below.
_ALLOW = ["/u/", "/g/", "/c/"]
```

The deleted paragraph explained why `/search/for-recruiters/` was carved out of the blanket `/search/` disallow. The page is gone, so the carve-out and its rationale go with it.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest games/tests/test_seo.py games/tests/test_home.py -q`
Expected: PASS (5 passed).

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **363 passed** (367 today, minus the 4 tests in `test_recruiters_landing.py`).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(search): retire the 'For recruiters' promise page"
```

---

## Task 2: Serve the people search at `/`

The root stops being a menu and becomes the tool. The view moves under the existing URL name `home`, so the logo and every other `{% url 'home' %}` keep resolving untouched.

**Files:**
- Modify: `search/views.py` (`RecruiterSearchView` → `PeopleSearchView`, docstring, `template_name`)
- Modify: `search/urls.py` (drop the `recruiters/` route)
- Modify: `config/urls.py` (root route + import)
- Rename: `templates/search/recruiter_search.html` → `templates/search/people_search.html`, and add the pitch + canonical
- Delete: `templates/home.html`
- Modify: `accounts/views.py:212`
- Rewrite: `games/tests/test_home.py`
- Rename: `search/tests/test_recruiter_search_view.py` → `search/tests/test_people_search_view.py`, and update its 13 reverses
- Modify: `search/tests/test_filter_autocomplete.py:128`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `search.views.PeopleSearchView`, served at `/` under the URL name **`home`** (unchanged name, new view). Tasks 3, 4 and 5 all target this view and its template. `search:recruiter_search` no longer exists as a name.

- [ ] **Step 1: Write the failing tests**

Replace the whole body of `games/tests/test_home.py` with:

```python
"""The home page IS the people search (spec docs/superpowers/specs/
2026-08-11-home-is-people-search-design.md). It used to be a menu of four links
that were all reachable from the nav bar anyway."""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db

PITCH = b"credits database for the video game industry"


def test_home_is_public_and_renders_the_search_form(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    # Substring stops before the apostrophe in "they've": how a template engine
    # renders that entity is not what this test is about.
    assert b"Find people by what they" in response.content
    assert b"discipline" in response.content.lower()


def test_home_pitches_signup_to_an_anonymous_visitor(client: Client) -> None:
    """Success metric #1 is workers signing up. With the "For recruiters" page
    gone, this line is the only surviving statement of the recruiter promise
    that docs/01-DESIGN.md §3.6 calls load-bearing for worker motivation."""
    response = client.get(reverse("home"))
    assert PITCH in response.content
    assert reverse("accounts:signup").encode() in response.content


def test_a_member_gets_the_tool_without_the_pitch(client: Client) -> None:
    """They already have an account — the pitch is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    response = client.get(reverse("home"))
    assert PITCH not in response.content
    assert b"discipline" in response.content.lower()  # the tool is still there
```

Rename the view's test module and re-aim it:

```bash
git mv search/tests/test_recruiter_search_view.py search/tests/test_people_search_view.py
```

In `search/tests/test_people_search_view.py`, replace **all 13** occurrences of `reverse("search:recruiter_search")` with `reverse("home")`, and replace the module docstring with:

```python
"""The people search — the home page, open to everyone (platform is free;
findability IS the service). Anti-scraping: the IP rate limit, pagination and
`profile_public` are the real mitigations; the >=1-filter rule is only a UX
guard."""
```

In `search/tests/test_filter_autocomplete.py:128`, replace:

```python
    return client.get(reverse("search:recruiter_search") + query).content.decode()
```

with:

```python
    return client.get(reverse("home") + query).content.decode()
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest games/tests/test_home.py search/tests/test_people_search_view.py -q`
Expected: FAIL — `test_home_is_public_and_renders_the_search_form` fails on `assert b"Find people by what they" in response.content` (the root still serves the old menu page), and the renamed module fails throughout on `NoReverseMatch: Reverse for 'home' ...` resolving to the menu page with no `discipline` control.

- [ ] **Step 3: Rename the view**

In `search/views.py`, replace the class statement and docstring:

```python
@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET", block=True), name="get")
class RecruiterSearchView(TemplateView):
    """Open to everyone — the platform is free, and showing workers that the
    recruiter-side tool exists is part of the promise (spec 2026-07-16).
    Anti-scraping: the IP rate limit above, pagination, and `profile_public`.
    The form's >=1-filter rule is a UX guard only, not a boundary."""

    template_name = "search/recruiter_search.html"
```

with:

```python
@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET", block=True), name="get")
class PeopleSearchView(TemplateView):
    """The home page: find people by what they've worked on. Open to everyone —
    the platform is free, and showing workers that the recruiter-side tool
    exists is part of the promise (spec 2026-07-16).
    Anti-scraping: the IP rate limit above, pagination, and `profile_public`.
    The form's >=1-filter rule is a UX guard only, not a boundary."""

    template_name = "search/people_search.html"
```

The decorator stays exactly as it is for now — Task 3 replaces it.

Everything below `template_name` — the whole `get_context_data` — stays byte-for-byte as it is.

- [ ] **Step 4: Move the routes**

In `search/urls.py`, delete this line:

```python
    path("recruiters/", views.RecruiterSearchView.as_view(), name="recruiter_search"),
```

In `config/urls.py`, add the import after the existing `from config.sitemaps import ...` line:

```python
from search.views import PeopleSearchView
```

and replace the root route:

```python
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
```

with:

```python
    # The root IS the people search — not a redirect to it, so the URL name
    # `home` keeps resolving for the logo and every other link.
    path("", PeopleSearchView.as_view(), name="home"),
```

Keep the `TemplateView` import: `/terms/` and `/privacy/` still use it.

- [ ] **Step 5: Rename the template and add the pitch**

```bash
git mv templates/search/recruiter_search.html templates/search/people_search.html
git rm templates/home.html
```

Leave `{% block title %}` as it is — `Find people · Rollcall` is still accurate,
and the spec settled the page's wording at the `<h1>`.

Directly under the `<h1>` line (`{% block content %}` opens just above it), insert the anonymous pitch:

```html
  {% if not user.is_authenticated %}
    <p>{% blocktranslate %}Rollcall is a credits database for the video game industry.
    Declare your work, be found by recruiters for what you actually shipped.{% endblocktranslate %}
    <a href="{% url 'accounts:signup' %}">{% translate "Create your account" %}</a></p>
  {% endif %}
```

This copy is `home.html`'s, moved verbatim. Everything else in the template — the `typeahead-scratch` form, the `noscript` note, the filter form, the chips script, the results section, the pagination — is untouched.

- [ ] **Step 6: Repoint the one redirect**

In `accounts/views.py:212`, replace:

```python
                return redirect("search:recruiter_search")
```

with:

```python
                return redirect("home")
```

This is the "approved recruiter opens the apply page → send them to the search" branch. Its *destination* is unchanged; only the name it is spelled with.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest games/tests/test_home.py search/tests/test_people_search_view.py search/tests/test_filter_autocomplete.py -q`
Expected: PASS (3 + 13 + 21 = 37 passed).

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **365 passed** (363 after Task 1, minus the 1 old home test, plus the 3 new ones).

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

Also confirm nothing still references the deleted URL names or template:

Run: `grep -rn "search:recruiters_landing\|search:recruiter_search\|home\.html" --include="*.py" --include="*.html" . | grep -v "\.venv"`
Expected: no hits.

> The `search:` prefix is load-bearing in that pattern. A bare `recruiter_search`
> also matches `search/services.py`'s `recruiter_search()` function and its many
> call sites in `test_recruiter_search.py` — none of which this plan renames.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(search): the people search becomes the home page"
```

---

## Task 3: Rate-limit real searches, not the front door

The view now answers on `/`. A class-level decorator would let one office behind a single NAT turn the site's front door into a 403 — and the counter lives in the per-process in-memory cache, so the behavior is already uneven. Quota becomes payable only by requests carrying a query string, which is exactly the surface worth protecting.

**Files:**
- Modify: `search/views.py` (`PeopleSearchView`: drop the decorator, add `get()`; imports)
- Modify: `search/tests/test_people_search_view.py` (the two rate-limit tests, plus one new one)

**Interfaces:**
- Consumes: `search.views.PeopleSearchView` (Task 2).
- Produces: `PeopleSearchView.get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse`, and the module constant `_RATELIMIT_GROUP = "people_search"`.

- [ ] **Step 1: Write the failing tests**

In `search/tests/test_people_search_view.py`, replace `test_rate_limited` with these two:

```python
def test_the_bare_home_page_is_never_rate_limited(client: Client, settings: Any) -> None:
    """This view is the front door now. A 403 on a search page is an annoyance;
    a 403 on `/` is the site being down for everyone behind that IP — an office
    NAT, a link-preview fetcher, a health check."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("home")
    for _ in range(5):
        assert client.get(url).status_code == 200


def test_a_real_search_is_rate_limited(client: Client, settings: Any) -> None:
    """Any query string counts, `?page=2` and junk params included: they are the
    same generated URL space, and leaving them free would unmeter the cheapest
    enumeration path."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("home")
    assert client.get(url, {"open_to_work": "on"}).status_code == 200
    assert client.get(url, {"open_to_work": "on"}).status_code == 403
    # A bare hit still answers — the counter is spent, the front door is not.
    assert client.get(url).status_code == 200
```

In the same file, `test_rate_limit_holds_while_other_ips_fill_the_cache` must now make real searches. Replace its two-line setup and its final assertion:

```python
    url = reverse("home")
    assert client.get(url, REMOTE_ADDR="10.0.0.1").status_code == 200
    assert client.get(url, REMOTE_ADDR="10.0.0.1").status_code == 403

    for i in range(1_000):
        cache.set(f"rlbucket:10.1.{i // 256}.{i % 256}", 1, 60)

    assert client.get(url, REMOTE_ADDR="10.0.0.1").status_code == 403
```

with:

```python
    url = reverse("home")
    search = {"open_to_work": "on"}
    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 200
    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 403

    for i in range(1_000):
        cache.set(f"rlbucket:10.1.{i // 256}.{i % 256}", 1, 60)

    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 403
```

Its docstring stays as it is — the invariant it pins ("the limit holds under traffic") is unchanged.

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest search/tests/test_people_search_view.py -q -k "rate"`
Expected: FAIL — `test_the_bare_home_page_is_never_rate_limited` fails on the second iteration with `403 != 200`; the decorator still bills every GET.

- [ ] **Step 3: Swap the decorator for a conditional check**

In `search/views.py`, add the imports next to the existing `from django_ratelimit.decorators import ratelimit`:

```python
from django_ratelimit.core import is_ratelimited
from django_ratelimit.exceptions import Ratelimited
```

`ratelimit` itself stays imported — `SearchView` and the autocomplete endpoints still use the decorator.

Above the class, add the group constant:

```python
# Named explicitly: django-ratelimit derives a decorator's group from the view's
# module and qualname, so renaming the view would have silently moved the
# counter. Distinct from SearchView's, which is the behavior today.
_RATELIMIT_GROUP = "people_search"
```

Then delete the decorator line from `PeopleSearchView`:

```python
@method_decorator(ratelimit(key="ip", rate=_search_rate, method="GET", block=True), name="get")
```

and add this method as the class's first, directly under `template_name`:

```python
    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Only a real search spends quota. This view is the home page now, so a
        # blanket limit would let one shared IP turn the front door into a 403.
        # Any query string counts — `?page=2` and junk params are part of the
        # same generated URL space, and that space is what needs metering.
        if request.GET and is_ratelimited(
            request=request,
            group=_RATELIMIT_GROUP,
            key="ip",
            rate=settings.SEARCH_RATELIMIT,
            method="GET",
            increment=True,
        ):
            raise Ratelimited
        return super().get(request, *args, **kwargs)
```

`Ratelimited` subclasses `PermissionDenied`, so Django renders the same 403 the decorator produced — the response is unchanged, only who is billed for it.

`settings.SEARCH_RATELIMIT` is read here at request time, so the `_search_rate` callable is not needed for this view. Leave `_search_rate` in place: `SearchView` and the three filter-autocomplete endpoints still pass it to their decorators, which are evaluated at import time and genuinely need the indirection.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest search/tests/test_people_search_view.py -q`
Expected: PASS (14 passed — the module's 13, with `test_rate_limited` replaced by two).

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **366 passed**.

> If `ty` reports an untyped-call diagnostic on `is_ratelimited` (django-ratelimit
> ships no stubs), add `# ty: ignore[...]` with the exact rule name it printed —
> the codebase's established accommodation. Do not widen the annotation to `Any`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "fix(search): only a real search spends rate-limit quota, not the home page"
```

---

## Task 4: Close the crawl trap at the root

The combinatorial filter-URL space moved to `/`, where a path prefix cannot reach it: `Disallow: /` would delist the entire site. It is closed by query string instead, and the root template gets a canonical as the second layer.

**Files:**
- Modify: `config/sitemaps.py` (`_DISALLOW`)
- Modify: `templates/search/people_search.html` (`{% block extra_head %}`)
- Modify: `games/tests/test_seo.py` (new test)

**Interfaces:**
- Consumes: URL name `home` (Task 2), `templates/search/people_search.html` (Task 2).
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing test**

In `games/tests/test_seo.py`, add after `test_robots_txt_keeps_content_pages_and_denies_private_areas`:

```python
def test_robots_txt_closes_the_root_filter_trap(client: Client) -> None:
    """The people search is the home page, so `/` must stay crawlable while
    `/?discipline=3&engines=5&page=2` must not.

    Asserted on the literal line and NOT through `RobotFileParser`: Python's
    parser ignores wildcards and would read `/*?` as a literal prefix matching
    nothing, so it cannot express this rule either way. Google and Bing do
    implement RFC 9309 §2.2.3 wildcards, and they are the crawlers whose budget
    the trap would burn. Coverage is deliberately partial; the root template's
    rel=canonical is the second layer.
    """
    body = client.get("/robots.txt").content.decode()

    assert "Disallow: /*?" in body

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    assert parser.can_fetch("*", "/")  # the home page itself stays indexable


def test_the_home_page_declares_itself_canonical(client: Client) -> None:
    """Filtered result pages are not distinct content. robots.txt stops the
    crawl; this collapses any variant reached from an external link anyway."""
    body = client.get(reverse("home")).content.decode()
    assert '<link rel="canonical" href="/">' in body
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest games/tests/test_seo.py -q`
Expected: FAIL — 2 failed (`assert "Disallow: /*?" in body` and the canonical assertion), the rest passing.

- [ ] **Step 3: Add the disallow**

In `config/sitemaps.py`, replace:

```python
_DISALLOW = ["/admin/", "/account/", "/profile/", "/credits/", "/contact/", "/report/", "/search/"]
```

with:

```python
_DISALLOW = [
    "/admin/",
    "/account/",
    "/profile/",
    "/credits/",
    "/contact/",
    "/report/",
    "/search/",
    # The people search is the home page, so its combinatorial filter-URL space
    # (`/?discipline=3&engines=5&page=2`) cannot be closed with a path prefix —
    # `Disallow: /` would delist the whole site. Closed by query string instead:
    # `/` carries none and stays crawlable, as a home page must, and `/u/`,
    # `/g/`, `/c/` are clean-path URLs, so nothing indexable is lost.
    #
    # Coverage is PARTIAL and deliberately so. RFC 9309 §2.2.3 defines `*` in a
    # path and Google and Bing implement it, but `urllib.robotparser` ignores
    # wildcards and reads this as a literal prefix matching nothing. The trap is
    # shut for the crawlers that would actually burn budget on it. The root
    # template's rel=canonical is the second layer for anything that gets past.
    "/*?",
]
```

No `_ALLOW` entry matches a root query-string URL, so this applies under both first-match and longest-match parsers — the ordering already documented above `_ALLOW` is unaffected.

- [ ] **Step 4: Add the canonical**

In `templates/search/people_search.html`, immediately after the `{% block extra_head %}` line and **before** the `<style>` tag:

```html
<link rel="canonical" href="{% url 'home' %}">
```

Relative, not absolute: it is valid per the HTML spec, and it keeps the tag independent of the request's host — there is no configured production domain yet.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest games/tests/test_seo.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **368 passed**.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix(seo): close the filter crawl trap now that it lives at the root"
```

---

## Task 5: The nav search box says what it matches

`suggest()` returns games, people **and** companies. The box is labelled `Search…`, and is narrow enough to truncate anything longer.

**Files:**
- Modify: `templates/base.html:39`
- Create: `search/tests/test_nav_search_box.py`

**Interfaces:**
- Consumes: URL name `home` (Task 2).
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing test**

Create `search/tests/test_nav_search_box.py`:

```python
"""The nav search box — sitewide chrome in base.html, backed by search:suggest."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_the_placeholder_names_all_three_things_it_matches(client: Client) -> None:
    """`suggest()` returns games, people AND companies; "Search…" said none of
    it, and the box is the only route to game/company lookup now."""
    body = client.get(reverse("home")).content
    assert b"Search games, companies and people" in body


def test_the_box_is_wide_enough_for_its_placeholder(client: Client) -> None:
    """Without a declared width the input falls to the browser default of about
    20 characters and truncates the label — which would make the fix above
    invisible, the exact failure it exists to correct."""
    body = client.get(reverse("home")).content
    assert b'size="35"' in body
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest search/tests/test_nav_search_box.py -q`
Expected: FAIL — 2 failed; the placeholder is still `Search…` and the input has no `size`.

- [ ] **Step 3: Fix the input**

In `templates/base.html`, replace lines 39–41:

```html
          <input type="search" name="q" placeholder="{% translate 'Search…' %}" autocomplete="off"
                 hx-get="{% url 'search:suggest' %}" hx-trigger="keyup changed delay:250ms"
                 hx-target="#nav-suggest">
```

with:

```html
          {# size=35 — one more than the 34-character placeholder, which the ~20-char browser default would truncate. #}
          <input type="search" name="q" size="35" autocomplete="off"
                 placeholder="{% translate 'Search games, companies and people' %}"
                 hx-get="{% url 'search:suggest' %}" hx-trigger="keyup changed delay:250ms"
                 hx-target="#nav-suggest">
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest search/tests/test_nav_search_box.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: all green, **370 passed**.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(search): the nav box names games, companies and people"
```

---

## Task 6: Verify in the browser and record it

The repo's convention is that user-facing changes are verified live, not only by tests (see the Phase 3–6 entries in ROADMAP.md). `docs/01-DESIGN.md` is the behavior source of truth and currently describes a page this plan deleted.

**Files:**
- Modify: `docs/01-DESIGN.md` (§3.6)
- Modify: `ROADMAP.md` (Post-roadmap additions)

- [ ] **Step 1: Start the app**

```bash
docker compose up -d db
```

Then start the dev server on port 8010 (`.claude/launch.json`, config `rollcall-dev`).

- [ ] **Step 2: Walk the loop**

Check each by hand:
1. `/` shows the search form, logged out, with the pitch line and a working "Create your account" link.
2. Log in as `devuser1@example.com` / `devpassword` — `/` now shows the form with **no** pitch line.
3. Clicking the "Rollcall" logo from any page lands on `/`.
4. Run a real search (tick "Open to work only" → Search). Results render, and the URL carries the filters.
5. Page 2 of a multi-page result set keeps the filters.
6. The nav box shows the new placeholder in full, is not truncated, and its typeahead still returns games, companies and people.
7. `/search/for-recruiters/` and `/search/recruiters/` both return 404.
8. `/robots.txt` contains `Disallow: /*?` and no `Allow: /search/for-recruiters/`.
9. The footer has Terms and Privacy, no "For recruiters".

- [ ] **Step 3: Correct the design doc**

In `docs/01-DESIGN.md` §3.6, replace the bullet that begins `- **Public "For recruiters" page** carrying the promise to candidates.` with:

```markdown
- **The people search IS the home page** (changed 2026-08-11, spec `docs/superpowers/specs/2026-08-11-home-is-people-search-design.md`). The separate public "For recruiters" promise page is deleted: once the search itself is the root, the tool is its own proof that the recruiter side exists. Its honest-counts commitment is not transferred — no counter is displayed anywhere, which cannot be inflated. For anonymous visitors the root carries one pitch line above the form ("Rollcall is a credits database… be found by recruiters for what you actually shipped") plus a signup link; that line is now the only statement of the recruiter promise, and it is why it stays. `robots.txt` no longer carves anything out of the `/search/` disallow; instead `Disallow: /*?` keeps the filter-URL space out of the index while `/` stays crawlable — partial coverage by design, since only wildcard-aware crawlers honor it (see `config/sitemaps.py`). The recruiter application flow keeps working but loses its last inbound link, which is what dormant looks like.
```

- [ ] **Step 4: Record it in the roadmap**

In `ROADMAP.md`, under `## Post-roadmap additions`, add:

```markdown
- [x] **The home page becomes the people search** (2026-08-11): `/` served a menu of four links that were all reachable from the nav bar anyway; it now serves the open people search directly, under the same URL name `home` (a view move, not a redirect, so `{% url 'home' %}` keeps resolving). The "For recruiters" promise page and the old landing are deleted outright — 404, no redirect, since nothing indexed points at either and the site is not deployed. Anonymous visitors get one pitch line plus a signup link above the form; members get the tool alone. Two consequences carried the real work: the combinatorial filter-URL space moved to the root, where a path prefix cannot close it (`Disallow: /` would delist the site), so it is closed by query string with `Disallow: /*?` — honoured by Google and Bing, ignored by `urllib.robotparser`, with a `rel=canonical` as the second layer; and the IP rate limit had to stop applying to the bare page, or one office behind a single NAT would turn the front door into a 403 (quota is now spent only by requests carrying a query string). The nav box, now the only route to game/company lookup, says so: "Search games, companies and people". The recruiter application flow stays routed but unlinked. No migration. Spec: `docs/superpowers/specs/2026-08-11-home-is-people-search-design.md`.
```

- [ ] **Step 5: Commit**

```bash
git add docs/01-DESIGN.md ROADMAP.md
git commit -m "docs: the search is the home page; retire the For recruiters page"
```

---

## Self-review

**Spec coverage.** Routes table → Tasks 1 and 2. Renames → Task 2. The root page (h1, pitch, member/anonymous split) → Task 2. Rate limiting → Task 3. robots.txt and the canonical → Task 4. Navigation (footer link, placeholder, width) → Tasks 1 and 5. Dormant flow → asserted by omission; no task links `accounts:recruiter_apply`, and Task 2 Step 8's grep confirms no stale reference. Testing table → the test module named in each task. Docs to update → Task 6. "Not doing" → no task adds a redirect, touches the search query/filters/cards, or creates a migration; every task's gate includes `makemigrations --check`.

**Types and names.** `PeopleSearchView` is introduced in Task 2 and consumed under that name in Tasks 3 and 4. The URL name `home` pre-exists, is re-pointed in Task 2, and is reversed in Tasks 2, 3, 4 and 5. `templates/search/people_search.html` is created in Task 2 and modified in Task 4. `_RATELIMIT_GROUP` is introduced and used only in Task 3. `search:recruiters_landing` dies in Task 1 and is referenced by no later task. `search:recruiter_search` has 17 call sites: 2 of them (`templates/search/recruiters_landing.html:20` and `search/tests/test_recruiters_landing.py:39`) disappear with the files Task 1 deletes, and Task 2 rewrites the remaining 15 — 13 in the renamed view-test module, 1 in `test_filter_autocomplete.py`, 1 in `accounts/views.py`. The name itself dies in Task 2.

**Test counts.** The repo is at **367** before Task 1. Task 1 removes the 4 landing tests → **363**. Task 2 removes the 1 old home test and adds 3 → **365**. Task 3 replaces 1 rate-limit test with 2 → **366**. Task 4 adds 2 → **368**. Task 5 adds 2 → **370**.
