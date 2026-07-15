# GitHub Profile Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Public side projects" block to member profiles, driven by public GitHub activity (repo count + commits/year), fetched lazily with a DB-backed cache-aside TTL and loaded non-blocking via htmx.

**Architecture:** Everything lives in the `accounts` app (a profile feature), mirroring how `games/igdb.py` keeps the IGDB client inside its domain app. A `GitHubClient` (REST + GraphQL, network isolated in `_http` for stubbing) is wrapped by a `get_github_activity()` cache-aside service backed by two models (`GitHubSnapshot`, `GitHubYearlyContribution`). The profile page renders instantly; a `hx-trigger="load"` fragment endpoint pulls the block separately and can never 500 the page.

**Tech Stack:** Django 6, Python 3.12, `urllib` (no new deps), htmx, pytest, uv + ruff + ty.

**Conventions (match the existing repo):**
- Run tests with `uv run pytest ...`. Full gate: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`.
- Fully typed Python (ty has no Django plugin — use the same accommodations already in the codebase: `ClassVar` managers, `str(field)` bridges, `Any` for FK/descriptor access, `AuthedHttpRequest`).
- Postgres runs in Docker on port **5433** (the repo's `.env` sets `POSTGRES_PORT`). It should already be up; if a test run errors on DB connection, start it with `docker compose up -d` (compose.yml).
- Commit after every task. Work on the current `github-profile-integration` branch.

---

## File structure

| File | New/Modified | Responsibility |
|---|---|---|
| `config/settings/base.py` | Modify | `GITHUB_TOKEN` env var |
| `config/settings/test.py` | Modify | blank `GITHUB_TOKEN` (no accidental network) |
| `accounts/github.py` | Create | `extract_login`, `GitHubClient`, `get_github_activity` + dataclasses |
| `accounts/models.py` | Modify | `User.github_login`, `GitHubSnapshot`, `GitHubYearlyContribution` |
| `accounts/migrations/0003_github.py` | Create (generated) | the migration |
| `accounts/forms.py` | Modify | `github_url` field on `SettingsForm` |
| `accounts/views.py` | Modify | `github_activity` fragment view |
| `accounts/urls.py` | Modify | `u/<slug>/github/` route |
| `templates/accounts/_github_block.html` | Create | the block + its states |
| `templates/accounts/profile.html` | Modify | htmx loader section |
| `accounts/tests/test_github_parsing.py` | Create | parser table |
| `accounts/tests/test_github_client.py` | Create | client (stubbed network) |
| `accounts/tests/test_github_service.py` | Create | cache-aside logic |
| `accounts/tests/test_github_view.py` | Create | fragment view |
| `accounts/tests/test_github_settings.py` | Create | settings form |
| `DEPLOY.md` | Modify | PAT setup note |

---

## Task 1: Settings — `GITHUB_TOKEN`

**Files:**
- Modify: `config/settings/base.py` (near the IGDB block, ~line 145)
- Modify: `config/settings/test.py` (near the IGDB block, ~line 24)

- [ ] **Step 1: Add the env var in base.py**

After the `IGDB_CLIENT_SECRET` line, add:

```python
# GitHub API — public "side projects" block on member profiles. Single
# server-side classic PAT (read:user scope is enough). Never client-side.
GITHUB_TOKEN = env("GITHUB_TOKEN", default="")
```

- [ ] **Step 2: Blank it in test.py**

After the `IGDB_CLIENT_SECRET = ""` line, add:

```python
# GitHub client is always stubbed in tests; keep it unconfigured so nothing
# can hit the network by accident.
GITHUB_TOKEN = ""
```

- [ ] **Step 3: Sanity-check the settings import**

Run: `uv run python -c "from config.settings import test as t; print(repr(t.GITHUB_TOKEN))"`
Expected: `''`

- [ ] **Step 4: Commit**

```bash
git add config/settings/base.py config/settings/test.py
git commit -s -m "feat(github): add GITHUB_TOKEN setting"
```

---

## Task 2: URL parser — `extract_login`

**Files:**
- Create: `accounts/github.py`
- Test: `accounts/tests/test_github_parsing.py`

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_parsing.py`:

```python
"""extract_login — parse a GitHub login from a pasted URL or bare handle."""

import pytest

from accounts.github import extract_login


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://github.com/torvalds", "torvalds"),
        ("github.com/torvalds", "torvalds"),
        ("https://github.com/torvalds/", "torvalds"),
        ("torvalds", "torvalds"),
        ("  https://github.com/torvalds  ", "torvalds"),
        ("https://www.github.com/torvalds", "torvalds"),
        ("github.com/torvalds/linux", "torvalds"),  # repo URL -> first segment
        ("https://github.com/a-b-c", "a-b-c"),
        ("torvalds?tab=repositories", "torvalds"),
        ("", None),
        ("   ", None),
        ("https://github.com/", None),
        ("-badstart", None),  # login cannot start with a hyphen
        ("bad--double", None),  # consecutive hyphens are invalid
        ("this-name-is-way-too-long-to-be-a-valid-github-login-x", None),  # >39 chars
        ("https://gitlab.com/torvalds", "torvalds"),  # not github: treat path as bare
    ],
)
def test_extract_login(raw: str, expected: str | None) -> None:
    assert extract_login(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_parsing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.github'`

- [ ] **Step 3: Write the parser**

Create `accounts/github.py`:

```python
"""GitHub integration for member profiles — the "Public side projects" block.

A member pastes their GitHub URL in settings (no OAuth, same trust model as a
LinkedIn link). This module parses the login, fetches public activity via the
REST + GraphQL APIs, and caches it with a DB-backed cache-aside TTL: past years
are immutable (fetched once), only the current year carries a 24h TTL.

Network is isolated in `GitHubClient._http` so tests stub it — no network.
"""

import re

# GitHub's own login rule: 1-39 chars, alnum or single internal hyphens.
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def extract_login(raw: str) -> str | None:
    """Extract a GitHub login from a pasted profile URL or a bare handle.

    Accepts full/scheme-less URLs, trailing slashes, and bare logins. A repo
    URL (github.com/user/repo) yields the first path segment (user). Returns
    None if no valid login can be extracted.
    """
    text = (raw or "").strip()
    if not text:
        return None
    text = _SCHEME_RE.sub("", text)
    lowered = text.lower()
    if "github.com" in lowered:
        text = text[lowered.index("github.com") + len("github.com") :].lstrip("/")
    candidate = text.split("/", 1)[0].split("?", 1)[0].strip()
    return candidate if _LOGIN_RE.match(candidate) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_parsing.py -q`
Expected: PASS (16 cases)

- [ ] **Step 5: Commit**

```bash
git add accounts/github.py accounts/tests/test_github_parsing.py
git commit -s -m "feat(github): extract_login URL/handle parser"
```

---

## Task 3: Models — `github_login`, `GitHubSnapshot`, `GitHubYearlyContribution`

**Files:**
- Modify: `accounts/models.py`
- Create (generated): `accounts/migrations/0003_github.py`
- Test: `accounts/tests/test_github_models.py`

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_models.py`:

```python
"""GitHub cache models — snapshot + per-year contributions."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


def _user() -> User:
    return User.objects.create_user(email="g@example.com", password="x", display_name="G")


def test_snapshot_is_one_per_user() -> None:
    user = _user()
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    with pytest.raises(IntegrityError):
        GitHubSnapshot.objects.create(user=user, login="torvalds2")


def test_snapshot_defaults_to_never_fetched() -> None:
    snap = GitHubSnapshot.objects.create(user=_user(), login="torvalds")
    assert snap.status == GitHubSnapshot.Status.NEVER_FETCHED
    assert snap.public_repos is None


def test_yearly_rows_are_unique_per_user_year() -> None:
    user = _user()
    now = timezone.now()
    GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=now, is_final=True)
    with pytest.raises(IntegrityError):
        GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=now)


def test_user_github_login_defaults_blank() -> None:
    assert _user().github_login == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'GitHubSnapshot'`

- [ ] **Step 3: Add the field to `User`**

In `accounts/models.py`, inside the `User` class after the `location` field (~line 100), add:

```python
    github_login = models.CharField(
        _("GitHub login"),
        max_length=39,
        blank=True,
        default="",
        help_text=_("Declared GitHub handle — not verified (same trust model as a LinkedIn link)."),
    )
```

- [ ] **Step 4: Add the two models**

At the end of `accounts/models.py`, add:

```python
class GitHubSnapshot(models.Model):
    """Profile-level GitHub cache (one per user). 24h TTL via profile_fetched_at."""

    class Status(models.TextChoices):
        NEVER_FETCHED = "never_fetched", _("Never fetched")
        OK = "ok", _("OK")
        NOT_FOUND = "not_found", _("Not found")
        ERROR = "error", _("Error")

    objects: ClassVar[models.Manager["GitHubSnapshot"]] = models.Manager()

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="github_snapshot")
    login = models.CharField(max_length=39, blank=True, default="")
    avatar_url = models.URLField(max_length=500, blank=True, default="")
    public_repos = models.PositiveIntegerField(null=True, blank=True)
    followers = models.PositiveIntegerField(null=True, blank=True)
    account_created_at = models.DateTimeField(null=True, blank=True)
    profile_fetched_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEVER_FETCHED
    )
    last_error = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"github:{self.login} [{self.status}]"


class GitHubYearlyContribution(models.Model):
    """One row per (user, year). Past years are immutable (is_final=True)."""

    objects: ClassVar[models.Manager["GitHubYearlyContribution"]] = models.Manager()

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="github_yearly_contributions"
    )
    year = models.PositiveIntegerField()
    total_commits = models.PositiveIntegerField(default=0)
    total_contributions = models.PositiveIntegerField(default=0)
    private_count = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField()
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(fields=["user", "year"], name="one_row_per_user_year"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.year}: {self.total_commits} commits"
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations accounts --name github`
Expected: creates `accounts/migrations/0003_github.py` adding one field + two models.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_models.py -q`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add accounts/models.py accounts/migrations/0003_github.py accounts/tests/test_github_models.py
git commit -s -m "feat(github): User.github_login + snapshot/yearly cache models"
```

---

## Task 4: `GitHubClient` — REST profile + error mapping

**Files:**
- Modify: `accounts/github.py`
- Test: `accounts/tests/test_github_client.py`

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_client.py`:

```python
"""GitHubClient — network isolated in _http; stubbed here (no network)."""

import io
import urllib.error
from typing import Any

import pytest

from accounts.github import GitHubClient, GitHubError, GitHubNotFound, GitHubRateLimited


def _client() -> GitHubClient:
    return GitHubClient(token="tok")


def test_unconfigured_client() -> None:
    assert GitHubClient(token="").configured is False
    assert _client().configured is True


def test_get_profile_returns_mapped_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_http(self: GitHubClient, method: str, url: str, data: Any, headers: Any) -> Any:
        captured["method"], captured["url"] = method, url
        return {"public_repos": 12, "followers": 3, "avatar_url": "a", "created_at": "2013-01-01"}

    monkeypatch.setattr(GitHubClient, "_http", fake_http)
    result = _client().get_profile("torvalds")

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/users/torvalds")
    assert result["public_repos"] == 12


def _raise_http(code: int, headers: dict[str, str] | None = None) -> Any:
    def _urlopen(request: Any, timeout: float | None = None) -> Any:
        raise urllib.error.HTTPError(
            request.full_url, code, "err", headers or {}, io.BytesIO(b"")
        )

    return _urlopen


def test_404_maps_to_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(404))
    with pytest.raises(GitHubNotFound):
        _client().get_profile("ghost")


def test_403_maps_to_rate_limited_with_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen", _raise_http(403, {"x-ratelimit-reset": "1893456000"})
    )
    with pytest.raises(GitHubRateLimited) as exc:
        _client().get_profile("torvalds")
    assert exc.value.reset == 1893456000


def test_other_http_error_maps_to_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", _raise_http(500))
    with pytest.raises(GitHubError):
        _client().get_profile("torvalds")


def test_unconfigured_client_never_calls_network() -> None:
    with pytest.raises(GitHubError):
        GitHubClient(token="").get_profile("torvalds")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_client.py -q`
Expected: FAIL — `ImportError: cannot import name 'GitHubClient'`

- [ ] **Step 3: Add the client (REST + errors + `_http`)**

In `accounts/github.py`, add these imports at the top (below the existing `import re`):

```python
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_TIMEOUT = 4
```

Then append the exceptions + client:

```python
class GitHubError(Exception):
    """GitHub is unreachable or returned an unexpected error."""


class GitHubNotFound(GitHubError):
    """The GitHub user does not exist (404)."""


class GitHubRateLimited(GitHubError):
    """GitHub rate limit hit (403/429)."""

    def __init__(self, message: str, reset: int | None = None) -> None:
        super().__init__(message)
        self.reset = reset


class GitHubClient:
    """REST (profile) + GraphQL (contributions). All network via `_http`."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else settings.GITHUB_TOKEN

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def get_profile(self, login: str) -> dict[str, Any]:
        data = self._http(
            "GET",
            f"{_API_BASE}/users/{login}",
            None,
            {"Accept": "application/vnd.github+json"},
        )
        return data if isinstance(data, dict) else {}

    def _http(self, method: str, url: str, data: bytes | None, headers: dict[str, str]) -> Any:
        if not self.configured:
            raise GitHubError("GITHUB_TOKEN is not configured")
        request_headers = {"Authorization": f"Bearer {self.token}", **headers}
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
                self._log_rate_limit(response.headers)
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            self._log_rate_limit(exc.headers)
            if exc.code == 404:
                raise GitHubNotFound(f"GitHub 404: {url}") from exc
            if exc.code in (403, 429):
                reset = exc.headers.get("x-ratelimit-reset")
                raise GitHubRateLimited(
                    f"GitHub rate limited: {url}", int(reset) if reset else None
                ) from exc
            raise GitHubError(f"GitHub HTTP {exc.code}: {url}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GitHubError(f"GitHub request failed: {exc}") from exc

    @staticmethod
    def _log_rate_limit(headers: Any) -> None:
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None:
            logger.info(
                "GitHub rate limit: remaining=%s reset=%s",
                remaining,
                headers.get("x-ratelimit-reset"),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_client.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add accounts/github.py accounts/tests/test_github_client.py
git commit -s -m "feat(github): GitHubClient REST profile + error mapping"
```

---

## Task 5: `GitHubClient` — GraphQL contributions

**Files:**
- Modify: `accounts/github.py`
- Test: `accounts/tests/test_github_client.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `accounts/tests/test_github_client.py`:

```python
def test_get_contribution_years(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_http(self: GitHubClient, method: str, url: str, data: Any, headers: Any) -> Any:
        assert method == "POST"
        assert url.endswith("/graphql")
        return {"data": {"user": {"contributionsCollection": {"contributionYears": [2026, 2025]}}}}

    monkeypatch.setattr(GitHubClient, "_http", fake_http)
    assert _client().get_contribution_years("torvalds") == [2026, 2025]


def test_get_contribution_years_missing_user_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GitHubClient, "_http", lambda *a, **k: {"data": {"user": None}}
    )
    with pytest.raises(GitHubNotFound):
        _client().get_contribution_years("ghost")


def test_get_year_contributions_builds_one_year_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_http(self: GitHubClient, method: str, url: str, data: Any, headers: Any) -> Any:
        captured["body"] = json.loads(data.decode())
        return {
            "data": {
                "user": {
                    "contributionsCollection": {
                        "totalCommitContributions": 200,
                        "restrictedContributionsCount": 42,
                        "contributionCalendar": {"totalContributions": 250},
                    }
                }
            }
        }

    monkeypatch.setattr(GitHubClient, "_http", fake_http)
    result = _client().get_year_contributions("torvalds", 2024)

    assert captured["body"]["variables"]["from"] == "2024-01-01T00:00:00Z"
    assert captured["body"]["variables"]["to"] == "2024-12-31T23:59:59Z"
    assert result == {"total_commits": 200, "private_count": 42, "total_contributions": 250}
```

Add `import json` at the top of the test file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_client.py -q`
Expected: FAIL — `AttributeError: 'GitHubClient' object has no attribute 'get_contribution_years'`

- [ ] **Step 3: Add the GraphQL methods**

In `accounts/github.py`, inside `GitHubClient` (after `get_profile`), add:

```python
    def get_contribution_years(self, login: str) -> list[int]:
        query = (
            "query($login: String!) { user(login: $login) { "
            "contributionsCollection { contributionYears } } }"
        )
        user = self._graphql_user(query, {"login": login})
        return list(user["contributionsCollection"]["contributionYears"])

    def get_year_contributions(self, login: str, year: int) -> dict[str, int]:
        query = (
            "query($login: String!, $from: DateTime!, $to: DateTime!) { "
            "user(login: $login) { contributionsCollection(from: $from, to: $to) { "
            "totalCommitContributions restrictedContributionsCount "
            "contributionCalendar { totalContributions } } } }"
        )
        variables = {
            "login": login,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year}-12-31T23:59:59Z",
        }
        cc = self._graphql_user(query, variables)["contributionsCollection"]
        return {
            "total_commits": cc["totalCommitContributions"],
            "private_count": cc["restrictedContributionsCount"],
            "total_contributions": cc["contributionCalendar"]["totalContributions"],
        }

    def _graphql_user(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        data = self._http("POST", f"{_API_BASE}/graphql", body, {})
        user = ((data or {}).get("data") or {}).get("user")
        if user is None:
            raise GitHubNotFound(f"No GitHub user: {variables.get('login')}")
        return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_client.py -q`
Expected: PASS (9 tests total)

- [ ] **Step 5: Commit**

```bash
git add accounts/github.py accounts/tests/test_github_client.py
git commit -s -m "feat(github): GraphQL contribution years + per-year query"
```

---

## Task 6: Cache-aside service — `get_github_activity`

**Files:**
- Modify: `accounts/github.py`
- Test: `accounts/tests/test_github_service.py`

**Design notes for this task:**
- `GitHubActivity` / `YearActivity` are frozen dataclasses returned to the view.
- Refresh decision is centralized. `full` fetch = cold (no snapshot or `never_fetched`); `partial` fetch = warm but current-year row missing/stale.
- On error/not_found we update only status + last_error + `profile_fetched_at` (keep prior good profile fields) and **serve stale**.
- Every fetch sets `profile_fetched_at = now`, so the back-off timers (24h TTL, 7-day not-found) work uniformly.

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_service.py`:

```python
"""get_github_activity — cache-aside with a DB-backed TTL."""

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from accounts.github import GitHubClient, GitHubError, GitHubNotFound, get_github_activity
from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


class FakeClient:
    """Configured stub that counts calls; no network."""

    def __init__(self, years: list[int] | None = None, raise_on: str | None = None) -> None:
        self.years = years if years is not None else [timezone.now().year, timezone.now().year - 1]
        self.raise_on = raise_on
        self.calls: list[str] = []

    configured = True

    def get_profile(self, login: str) -> dict[str, Any]:
        self.calls.append("profile")
        if self.raise_on == "profile":
            raise GitHubError("boom")
        if self.raise_on == "not_found":
            raise GitHubNotFound("ghost")
        return {"public_repos": 7, "followers": 2, "avatar_url": "a", "created_at": "2013-05-01T00:00:00Z"}

    def get_contribution_years(self, login: str) -> list[int]:
        self.calls.append("years")
        return self.years

    def get_year_contributions(self, login: str, year: int) -> dict[str, int]:
        self.calls.append(f"year:{year}")
        return {"total_commits": 10 + year % 5, "private_count": year % 3, "total_contributions": 20}


def _user(login: str = "torvalds") -> User:
    return User.objects.create_user(
        email="s@example.com", password="x", display_name="S", github_login=login
    )


def test_no_login_returns_none() -> None:
    assert get_github_activity(_user(login=""), FakeClient()) is None


def test_unconfigured_client_returns_none() -> None:
    assert get_github_activity(_user(), GitHubClient(token="")) is None


def test_cold_fetch_fetches_profile_years_and_each_year() -> None:
    user = _user()
    client = FakeClient(years=[2026, 2025, 2024])
    activity = get_github_activity(user, client)

    assert activity is not None
    assert activity.status == "ok"
    assert activity.public_repos == 7
    assert client.calls == ["profile", "years", "year:2026", "year:2025", "year:2024"]
    # Past years are final; current year is not.
    assert GitHubYearlyContribution.objects.get(user=user, year=2024).is_final is True
    assert GitHubYearlyContribution.objects.get(user=user, year=2026).is_final is False


def test_history_is_capped_at_five_years() -> None:
    user = _user()
    client = FakeClient(years=[2026, 2025, 2024, 2023, 2022, 2021, 2020])
    get_github_activity(user, client)
    assert GitHubYearlyContribution.objects.filter(user=user).count() == 5
    assert not GitHubYearlyContribution.objects.filter(user=user, year=2021).exists()


def test_warm_and_fresh_makes_no_calls() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # cold
    client = FakeClient()
    get_github_activity(user, client)  # warm
    assert client.calls == []


def test_stale_current_year_does_one_partial_fetch() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # cold
    # Age the current-year row past the 24h TTL.
    current_year = timezone.now().year
    row = GitHubYearlyContribution.objects.get(user=user, year=current_year)
    row.fetched_at = timezone.now() - timedelta(hours=25)
    row.save(update_fields=["fetched_at"])

    client = FakeClient()
    get_github_activity(user, client)
    assert client.calls == ["profile", f"year:{current_year}"]  # NOT the whole history


def test_not_found_is_recorded_and_not_retried_for_7_days() -> None:
    user = _user()
    client = FakeClient(raise_on="not_found")
    activity = get_github_activity(user, client)
    assert activity is not None
    assert activity.status == "not_found"

    client2 = FakeClient(raise_on="not_found")
    get_github_activity(user, client2)
    assert client2.calls == []  # no retry within 7 days


def test_error_serves_stale_data() -> None:
    user = _user()
    get_github_activity(user, FakeClient())  # good cold fetch
    current_year = timezone.now().year
    row = GitHubYearlyContribution.objects.get(user=user, year=current_year)
    row.fetched_at = timezone.now() - timedelta(hours=25)
    row.save(update_fields=["fetched_at"])

    activity = get_github_activity(user, FakeClient(raise_on="profile"))
    assert activity is not None
    assert activity.public_repos == 7  # stale-but-present data still served
    snap = GitHubSnapshot.objects.get(user=user)
    assert snap.status == GitHubSnapshot.Status.ERROR
    assert snap.last_error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'get_github_activity'`

- [ ] **Step 3: Add the dataclasses + service**

In `accounts/github.py`, extend the top imports to:

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
```

and add (Django model imports must be inside the module top with the others):

```python
from django.utils import timezone

from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User
```

Then append the dataclasses, constants, and service:

```python
_HISTORY_YEARS = 5
_PROFILE_TTL = timedelta(hours=24)
_NOT_FOUND_RETRY = timedelta(days=7)


@dataclass(frozen=True)
class YearActivity:
    year: int
    total_commits: int
    total_contributions: int
    private_count: int


@dataclass(frozen=True)
class GitHubActivity:
    login: str
    status: str
    avatar_url: str = ""
    public_repos: int | None = None
    followers: int | None = None
    account_created_at: datetime | None = None
    years: list[YearActivity] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return self.public_repos is not None or bool(self.years)

    @property
    def private_total(self) -> int:
        return sum(y.private_count for y in self.years)


def get_github_activity(user: User, client: GitHubClient | None = None) -> GitHubActivity | None:
    """Serve a member's GitHub activity, refreshing lazily (cache-aside)."""
    login = (user.github_login or "").strip()
    if not login:
        return None
    client = client or GitHubClient()
    if not client.configured:
        return None

    now = timezone.now()
    current_year = now.year
    snapshot = GitHubSnapshot.objects.filter(user=user).first()
    current_row = GitHubYearlyContribution.objects.filter(user=user, year=current_year).first()

    if _needs_refresh(snapshot, current_row, now):
        cold = snapshot is None or snapshot.status == GitHubSnapshot.Status.NEVER_FETCHED
        try:
            if cold:
                _full_fetch(user, login, client, now, current_year)
            else:
                _partial_fetch(user, login, client, now, current_year)
        except GitHubNotFound:
            _record_status(user, login, GitHubSnapshot.Status.NOT_FOUND, now, "not found")
        except GitHubError as exc:
            _record_status(user, login, GitHubSnapshot.Status.ERROR, now, str(exc))
        snapshot = GitHubSnapshot.objects.filter(user=user).first()

    if snapshot is None:
        return None
    return _activity_from_db(snapshot, user)


def _needs_refresh(
    snapshot: "GitHubSnapshot | None",
    current_row: "GitHubYearlyContribution | None",
    now: datetime,
) -> bool:
    if snapshot is None or snapshot.status == GitHubSnapshot.Status.NEVER_FETCHED:
        return True
    fetched = snapshot.profile_fetched_at
    if snapshot.status == GitHubSnapshot.Status.NOT_FOUND:
        return fetched is None or (now - fetched) >= _NOT_FOUND_RETRY
    if snapshot.status == GitHubSnapshot.Status.ERROR:
        return fetched is None or (now - fetched) >= _PROFILE_TTL
    # status OK: refresh when the current year's row is missing or stale.
    return current_row is None or (now - current_row.fetched_at) >= _PROFILE_TTL


def _account_created(profile: dict[str, Any]) -> datetime | None:
    raw = profile.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _full_fetch(
    user: User, login: str, client: GitHubClient, now: datetime, current_year: int
) -> None:
    profile = client.get_profile(login)
    years = [y for y in client.get_contribution_years(login) if y <= current_year]
    years = sorted(years, reverse=True)[:_HISTORY_YEARS]
    for year in years:
        data = client.get_year_contributions(login, year)
        _upsert_year(user, year, data, now, is_final=year < current_year)
    _save_ok(user, login, profile, now)


def _partial_fetch(
    user: User, login: str, client: GitHubClient, now: datetime, current_year: int
) -> None:
    profile = client.get_profile(login)
    data = client.get_year_contributions(login, current_year)
    _upsert_year(user, current_year, data, now, is_final=False)
    # Any prior year lingering as non-final is now immutable.
    GitHubYearlyContribution.objects.filter(
        user=user, year__lt=current_year, is_final=False
    ).update(is_final=True)
    _save_ok(user, login, profile, now)


def _upsert_year(
    user: User, year: int, data: dict[str, int], now: datetime, *, is_final: bool
) -> None:
    GitHubYearlyContribution.objects.update_or_create(
        user=user,
        year=year,
        defaults={
            "total_commits": data["total_commits"],
            "total_contributions": data["total_contributions"],
            "private_count": data["private_count"],
            "fetched_at": now,
            "is_final": is_final,
        },
    )


def _save_ok(user: User, login: str, profile: dict[str, Any], now: datetime) -> None:
    GitHubSnapshot.objects.update_or_create(
        user=user,
        defaults={
            "login": login,
            "avatar_url": profile.get("avatar_url", "") or "",
            "public_repos": profile.get("public_repos"),
            "followers": profile.get("followers"),
            "account_created_at": _account_created(profile),
            "profile_fetched_at": now,
            "status": GitHubSnapshot.Status.OK,
            "last_error": "",
        },
    )


def _record_status(user: User, login: str, status: str, now: datetime, error: str) -> None:
    # Keep any previously-good profile fields; only touch status/error/timestamp.
    GitHubSnapshot.objects.update_or_create(
        user=user,
        defaults={
            "login": login,
            "profile_fetched_at": now,
            "status": status,
            "last_error": error,
        },
    )


def _activity_from_db(snapshot: GitHubSnapshot, user: User) -> GitHubActivity:
    years = [
        YearActivity(
            year=row.year,
            total_commits=row.total_commits,
            total_contributions=row.total_contributions,
            private_count=row.private_count,
        )
        for row in GitHubYearlyContribution.objects.filter(user=user).order_by("-year")
    ]
    return GitHubActivity(
        login=str(snapshot.login),
        status=str(snapshot.status),
        avatar_url=str(snapshot.avatar_url),
        public_repos=snapshot.public_repos,
        followers=snapshot.followers,
        account_created_at=snapshot.account_created_at,
        years=years,
    )
```

Note: `datetime` and `UTC` are imported for `_account_created`; `UTC` may be unused — if ruff flags it, drop `UTC` from the import.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_service.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Run ruff + ty on the module**

Run: `uv run ruff check accounts/github.py && uv run ty check accounts/github.py`
Expected: clean (fix any unused import, e.g. drop `UTC` if flagged).

- [ ] **Step 6: Commit**

```bash
git add accounts/github.py accounts/tests/test_github_service.py
git commit -s -m "feat(github): cache-aside get_github_activity service"
```

---

## Task 7: Fragment view + URL + templates

**Files:**
- Modify: `accounts/views.py`
- Modify: `accounts/urls.py`
- Create: `templates/accounts/_github_block.html`
- Modify: `templates/accounts/profile.html`
- Test: `accounts/tests/test_github_view.py`

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_view.py`:

```python
"""github_activity fragment view — never breaks the profile page."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import github as gh
from accounts.models import GitHubSnapshot, User

pytestmark = pytest.mark.django_db


def _user(**kw: Any) -> User:
    defaults = dict(email="v@example.com", password="x", display_name="V", github_login="torvalds")
    defaults.update(kw)
    return User.objects.create_user(**defaults)


def _url(user: User) -> str:
    return reverse("accounts:github_activity", kwargs={"slug": user.slug})


def test_renders_ok_block_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user,
        login="torvalds",
        public_repos=7,
        status=GitHubSnapshot.Status.OK,
        profile_fetched_at=timezone.now(),
    )
    # Freshness: no network. Force the service to serve from DB.
    monkeypatch.setattr(gh, "_needs_refresh", lambda *a, **k: False)

    response = Client().get(_url(user))
    assert response.status_code == 200
    assert b"Public side projects" in response.content
    assert b"7" in response.content


def test_hidden_when_no_login() -> None:
    user = _user(github_login="")
    response = Client().get(_url(user))
    assert response.status_code == 200
    assert b"Public side projects" not in response.content


def test_never_500s_when_service_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    monkeypatch.setattr(gh, "get_github_activity", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    response = Client().get(_url(user))
    assert response.status_code == 200  # degraded, not crashed


def test_private_profile_is_404_to_others() -> None:
    user = _user(profile_public=False)
    response = Client().get(_url(user))
    assert response.status_code == 404


def test_never_leaks_email(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user()
    GitHubSnapshot.objects.create(
        user=user, login="torvalds", public_repos=1,
        status=GitHubSnapshot.Status.OK, profile_fetched_at=timezone.now(),
    )
    monkeypatch.setattr(gh, "_needs_refresh", lambda *a, **k: False)
    response = Client().get(_url(user))
    assert b"v@example.com" not in response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_view.py -q`
Expected: FAIL — `NoReverseMatch: 'github_activity' is not a valid view function or pattern name`

- [ ] **Step 3: Add the view**

In `accounts/views.py`, add imports near the top:

```python
import logging

from django.http import Http404

from accounts.github import get_github_activity

logger = logging.getLogger(__name__)
```

Add to `__all__`: `"github_activity",`.

Append the view at the end of the module:

```python
def github_activity(request: HttpRequest, slug: str) -> HttpResponse:
    """htmx fragment: a member's public GitHub activity. Never 500s — any
    failure degrades to a quiet state so the profile page is unaffected."""
    if request.user.is_authenticated:
        qs = User.objects.filter(Q(profile_public=True) | Q(pk=request.user.pk))
    else:
        qs = User.objects.filter(profile_public=True)
    profile_user = qs.filter(slug=slug).first()
    if profile_user is None:
        raise Http404
    activity = None
    try:
        activity = get_github_activity(profile_user)
    except Exception:  # noqa: BLE001 — the block must never break the page
        logger.exception("GitHub activity block failed for %s", slug)
    return render(request, "accounts/_github_block.html", {"activity": activity})
```

- [ ] **Step 4: Add the URL**

In `accounts/urls.py`, add this **before** the final `u/<slug:slug>/` profile route (so it isn't shadowed):

```python
    path("u/<slug:slug>/github/", views.github_activity, name="github_activity"),
```

- [ ] **Step 5: Create the block template**

Create `templates/accounts/_github_block.html`:

```html
{% load i18n %}
{% if activity %}
  {% if activity.status == "not_found" %}
    <section class="github-block">
      <h2>{% translate "Public side projects" %}</h2>
      <p class="muted">{% translate "GitHub profile not found." %}</p>
    </section>
  {% elif activity.has_data %}
    <section class="github-block">
      <h2>{% translate "Public side projects" %}</h2>
      <p class="muted">
        {% translate "Open-source and side-project activity. Most games work lives in private Perforce repos under NDA — an empty block here means nothing." %}
      </p>
      <div class="github-head">
        {% if activity.avatar_url %}
          <img src="{{ activity.avatar_url }}" alt="" width="48" height="48">
        {% endif %}
        <ul class="github-stats">
          <li>{{ activity.public_repos }} {% translate "public repos" %}</li>
          {% if activity.followers is not None %}
            <li>{{ activity.followers }} {% translate "followers" %}</li>
          {% endif %}
          {% if activity.account_created_at %}
            <li>{% blocktranslate with y=activity.account_created_at|date:"Y" %}On GitHub since {{ y }}{% endblocktranslate %}</li>
          {% endif %}
        </ul>
      </div>
      <ul class="github-years">
        {% for y in activity.years %}
          <li><span class="year">{{ y.year }}</span> — {{ y.total_commits }} {% translate "commits" %}</li>
        {% empty %}
          <li>{% translate "No public commits in the last 5 years." %}</li>
        {% endfor %}
      </ul>
      {% if activity.private_total %}
        <p class="github-private">
          {% blocktranslate with n=activity.private_total %}+{{ n }} private contributions (last 5y){% endblocktranslate %}
        </p>
      {% endif %}
    </section>
  {% endif %}
{% endif %}
```

- [ ] **Step 6: Wire the loader into the profile page**

In `templates/accounts/profile.html`, add before the closing `{% endblock %}` (after the credits `</section>`):

```html
  {% if profile_user.github_login %}
    <section hx-get="{% url 'accounts:github_activity' profile_user.slug %}"
             hx-trigger="load" hx-swap="outerHTML">
      <p class="muted">{% translate "Loading GitHub activity…" %}</p>
    </section>
  {% endif %}
```

- [ ] **Step 7: Run tests + type check**

Run: `uv run pytest accounts/tests/test_github_view.py -q && uv run ty check accounts/views.py`
Expected: PASS (5 tests), ty clean.

- [ ] **Step 8: Commit**

```bash
git add accounts/views.py accounts/urls.py templates/accounts/_github_block.html templates/accounts/profile.html accounts/tests/test_github_view.py
git commit -s -m "feat(github): non-blocking activity fragment on profiles"
```

---

## Task 8: Settings form — `github_url` field

**Files:**
- Modify: `accounts/forms.py`
- Test: `accounts/tests/test_github_settings.py`

Note: `settings.html` renders `{{ form.as_p }}`, so the new field appears automatically — no template change.

- [ ] **Step 1: Write the failing test**

Create `accounts/tests/test_github_settings.py`:

```python
"""SettingsForm.github_url — parse to a login and manage the cache."""

import pytest
from django.utils import timezone

from accounts.forms import SettingsForm
from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

pytestmark = pytest.mark.django_db


def _user(**kw: str) -> User:
    return User.objects.create_user(
        email="f@example.com", password="x", display_name="F", **kw
    )


def _data(**overrides: str) -> dict[str, str]:
    data = {
        "display_name": "F",
        "bio": "",
        "location": "",
        "profile_public": "on",
        "contactable": "on",
        "open_to_work": "",
        "github_url": "",
    }
    data.update(overrides)
    return data


def test_valid_url_is_stored_as_login() -> None:
    user = _user()
    form = SettingsForm(_data(github_url="https://github.com/torvalds"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.github_login == "torvalds"


def test_repo_url_keeps_first_segment() -> None:
    user = _user()
    form = SettingsForm(_data(github_url="github.com/torvalds/linux"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.github_login == "torvalds"


def test_invalid_url_is_a_validation_error() -> None:
    form = SettingsForm(_data(github_url="not a url !!"), instance=_user())
    assert not form.is_valid()
    assert "github_url" in form.errors


def test_initial_prefills_from_existing_login() -> None:
    user = _user(github_login="torvalds")
    form = SettingsForm(instance=user)
    assert form.fields["github_url"].initial == "torvalds"


def test_changing_the_handle_wipes_the_cache() -> None:
    user = _user(github_login="torvalds")
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    GitHubYearlyContribution.objects.create(user=user, year=2024, fetched_at=timezone.now())

    form = SettingsForm(_data(github_url="github.com/gvanrossum"), instance=user)
    assert form.is_valid(), form.errors
    form.save()

    assert not GitHubSnapshot.objects.filter(user=user).exists()
    assert not GitHubYearlyContribution.objects.filter(user=user).exists()
    user.refresh_from_db()
    assert user.github_login == "gvanrossum"


def test_unchanged_handle_keeps_the_cache() -> None:
    user = _user(github_login="torvalds")
    GitHubSnapshot.objects.create(user=user, login="torvalds")
    form = SettingsForm(_data(github_url="https://github.com/torvalds"), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    assert GitHubSnapshot.objects.filter(user=user).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest accounts/tests/test_github_settings.py -q`
Expected: FAIL — `KeyError: 'github_url'` (field not on the form yet)

- [ ] **Step 3: Extend `SettingsForm`**

In `accounts/forms.py`, add the import at the top:

```python
from accounts.github import extract_login
from accounts.models import GitHubSnapshot, GitHubYearlyContribution
```

(There is already `from accounts.models import RecruiterApplication, User` — extend it or add a second import line as shown.)

Replace the `SettingsForm` class with:

```python
class SettingsForm(forms.ModelForm):
    """Profile + the three visibility booleans (docs/01-DESIGN.md §3.4),
    plus an optional GitHub handle (stored parsed as a login)."""

    github_url = forms.CharField(
        required=False,
        label=_("GitHub profile URL"),
        help_text=_("Optional — shown as 'Public side projects'. e.g. https://github.com/yourhandle"),
    )

    class Meta:
        model = User
        fields = [
            "display_name",
            "bio",
            "location",
            "avatar",
            "profile_public",
            "contactable",
            "open_to_work",
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["github_url"].initial = str(self.instance.github_login)

    def clean_github_url(self) -> str:
        raw = self.cleaned_data.get("github_url", "").strip()
        if not raw:
            return ""
        login = extract_login(raw)
        if login is None:
            raise forms.ValidationError(_("Enter a valid GitHub profile URL or username."))
        return login

    def save(self, commit: bool = True) -> User:
        user: Any = super().save(commit=False)
        new_login = self.cleaned_data.get("github_url", "")
        if new_login != user.github_login:
            user.github_login = new_login
            if commit:
                GitHubSnapshot.objects.filter(user=user).delete()
                GitHubYearlyContribution.objects.filter(user=user).delete()
        if commit:
            user.save()
        return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest accounts/tests/test_github_settings.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add accounts/forms.py accounts/tests/test_github_settings.py
git commit -s -m "feat(github): github_url field on settings form"
```

---

## Task 9: Admin, docs, and the full gate

**Files:**
- Modify: `accounts/admin.py`
- Modify: `DEPLOY.md`

- [ ] **Step 1: Register the snapshot in admin (read-only convenience)**

In `accounts/admin.py`, add:

```python
from accounts.models import GitHubSnapshot

@admin.register(GitHubSnapshot)
class GitHubSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "login", "status", "public_repos", "profile_fetched_at")
    list_filter = ("status",)
    search_fields = ("login", "user__email")
    readonly_fields = ("profile_fetched_at",)
```

Match the existing import/registration style already in that file (if it uses `admin.site.register(...)` instead of decorators, follow that).

- [ ] **Step 2: Document the PAT in DEPLOY.md**

Add a new section after §4 (Sentry):

```markdown
## 4b. GitHub — "Public side projects" block

Set `GITHUB_TOKEN` to a **classic Personal Access Token** with the `read:user`
scope (no repo access needed). It is used server-side only for the profile
GitHub block (REST profile + GraphQL contributions). Without it the block is
hidden — the rest of the profile is unaffected. Rate limit with a token is
5,000 req/h; the cache-aside TTL means a warm profile view costs zero calls and
a daily refresh costs one.
```

- [ ] **Step 3: Run the full gate**

Run: `uv run ruff format . && uv run ruff check . && uv run ty check && uv run pytest -q`
Expected: format clean, ruff "All checks passed!", ty "All checks passed!", all tests pass (182 prior + the new GitHub tests).

- [ ] **Step 4: Commit**

```bash
git add accounts/admin.py DEPLOY.md
git commit -s -m "feat(github): admin registration + DEPLOY note; full gate green"
```

---

## Manual verification (after all tasks)

With the dev server running and a real `GITHUB_TOKEN` in `.env`:

1. Log in, go to **Settings**, paste `https://github.com/torvalds` (or your own), save.
2. Visit your profile → the "Public side projects" block loads a beat after the page (htmx), showing repos, followers, "On GitHub since …", and commits/year.
3. Reload → the block appears instantly (warm cache, zero calls — confirm via server logs showing no GitHub rate-limit line on the second load).
4. Set the handle to a non-existent user → block shows "GitHub profile not found"; it won't refetch for 7 days.
5. Clear the field → block disappears; snapshot rows are gone.
6. Unset `GITHUB_TOKEN` → block is hidden entirely, profile otherwise unchanged.

---

## Self-review (completed at authoring time)

- **Spec coverage:** §1 parsing → Task 2 + 8; §2 REST/GraphQL/rate-limit-logging → Tasks 4–5; §3 cache-aside/TTL/immutable-past/non-blocking → Tasks 6–7; §4 data model → Task 3; §5 error handling (404/403/timeout/5xx/empty) → Tasks 4 + 6 + template; §6 "Public side projects" framing → Task 7 template; §7 out-of-scope respected (no OAuth, no Perforce, no MobyGames, stampede documented not built). Config/token → Task 1 + 9.
- **Placeholders:** none — every code step is complete.
- **Type consistency:** `extract_login`, `GitHubClient.get_profile/get_contribution_years/get_year_contributions`, `get_github_activity`, `GitHubActivity(.has_data/.private_total)`, `YearActivity`, and the model names (`GitHubSnapshot`, `GitHubYearlyContribution`, `Status`) are used identically across tasks.
