"""GitHub integration for member profiles — the "Public side projects" block.

A member pastes their GitHub URL in settings (no OAuth, same trust model as a
LinkedIn link). This module parses the login, fetches public activity via the
REST + GraphQL APIs, and caches it with a DB-backed cache-aside TTL: past years
are immutable (fetched once), only the current year carries a 24h TTL.

Network is isolated in `GitHubClient._http` so tests stub it — no network.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from accounts.models import GitHubSnapshot, GitHubYearlyContribution, User

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_TIMEOUT = 4

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
    login = (user.github_login or "").strip()  # ty: ignore[unresolved-attribute]
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
        return fetched is None or (now - fetched) >= _NOT_FOUND_RETRY  # ty: ignore[unsupported-operator]
    if snapshot.status == GitHubSnapshot.Status.ERROR:
        return fetched is None or (now - fetched) >= _PROFILE_TTL  # ty: ignore[unsupported-operator]
    # status OK: refresh when the current year's row is missing or stale.
    return (
        current_row is None
        or (now - current_row.fetched_at) >= _PROFILE_TTL  # ty: ignore[unsupported-operator]
    )


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
        public_repos=snapshot.public_repos,  # ty: ignore[invalid-argument-type]
        followers=snapshot.followers,  # ty: ignore[invalid-argument-type]
        account_created_at=snapshot.account_created_at,  # ty: ignore[invalid-argument-type]
        years=years,
    )
