"""Shared test helpers used across more than one app's test suite. Fixtures
and factories that belong to a single app still live in that app's tests."""

import socket
import urllib.request
from typing import Any

import pytest


def header(body: str) -> str:
    """The nav's own <header>, sliced out of a full page body.

    people_search.html (rendered in <main> on the home page) has its own
    search input, and other pages have their own headings — scoping to
    <header> is what makes assertions on the nav's markup specific to it.
    """
    return body[: body.index("</header>")]


_LOOPBACK_HOSTS = frozenset({"localhost", "::1", "::ffff:127.0.0.1"})


def _is_loopback(address: Any) -> bool:
    # AF_UNIX addresses are a path, not a host/port pair — a local socket, not
    # an outbound connection, so it is allowed through.
    if not isinstance(address, tuple) or not address:
        return True
    host = address[0]
    if not isinstance(host, str):
        return False
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that opens a connection off this machine.

    A test on `feat/igdb-auto-fallback` stubbed `IGDBClient.get_game` but not
    `search_games`, and the re-render path reached a live
    `POST https://id.twitch.tv/oauth2/token` — it *passed*, because the call
    succeeded. Only review caught it. Stubbing the right method is not
    something every future IGDB-adjacent test can be relied on to remember, so
    the suite refuses the connection instead (ROADMAP, known follow-ups).

    Loopback stays open: Postgres, and any local server a test starts. The
    error is a `RuntimeError` on purpose — `games/igdb.py` and
    `accounts/github.py` both swallow `URLError` into their own exception
    type, so a network-shaped failure would be caught and the test would go on
    asserting the "third party is down" branch instead of failing.
    """
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if not _is_loopback(address):
            raise RuntimeError(
                f"Test attempted an outbound network connection to {address!r}. "
                "Stub the client instead (see conftest._no_outbound_network)."
            )
        real_connect(self, address)

    def refuse_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Test attempted urllib.request.urlopen. Stub the client instead "
            "(see conftest._no_outbound_network)."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(urllib.request, "urlopen", refuse_urlopen)
