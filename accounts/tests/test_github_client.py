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
