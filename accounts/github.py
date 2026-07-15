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
