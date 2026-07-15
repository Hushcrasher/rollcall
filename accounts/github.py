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
from typing import Any

from django.conf import settings

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
