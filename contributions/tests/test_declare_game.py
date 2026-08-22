"""Step 1 of the declare funnel — turn a typed title into a chosen game.

Plain HTML on purpose: the root only carries a text box, and the picking happens
here (spec docs/superpowers/specs/2026-08-11-deferred-registration-funnel-design.md).
"""

import re
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.funnel import SESSION_KEY
from games.igdb import IGDBClient, IGDBError
from games.models import Game

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


@pytest.fixture
def igdb_configured(settings: Any) -> None:
    settings.IGDB_CLIENT_ID = "cid"
    settings.IGDB_CLIENT_SECRET = "secret"


@pytest.fixture
def game() -> Game:
    return Game.objects.create(title="Hollow Knight", source=Game.Source.MANUAL)


def test_declare_is_open_to_anonymous_visitors(client: Client) -> None:
    """The whole point: no account needed to start."""
    assert client.get(reverse("contributions:declare")).status_code == 200


# A non-greedy `.*?</form>` under re.S does not stop at the FIRST `</form>` —
# it stops at the first position where the rest of the pattern also matches,
# which can be several forms later. On this page that let a match starting at
# base.html's nav search form run straight through to a `name="game"` deep in
# the picking form, "bounded" only by whichever `</form>` happened to follow.
# The negative-lookahead idiom below excludes `</form>` from what `.` can
# consume, so the match cannot cross a form boundary at all.
_GAME_FORM_RE = r'<form[^>]*>(?:(?!</form>).)*?name="game"(?:(?!</form>).)*?</form>'


def test_posting_a_title_lists_matching_games(client: Client, game: Game) -> None:
    """Scoped to the form carrying the hidden `game` input, not just the page
    text — the search box's own placeholder ("Hollow Knight, Dishonored…")
    would satisfy a bare `b"Hollow Knight" in response.content` even when
    nothing matched."""
    response = client.post(reverse("contributions:declare"), {"q": "hollow"})
    assert response.status_code == 200
    body = response.content.decode()
    match = re.search(_GAME_FORM_RE, body, re.S)
    assert match is not None, "no form carrying a pickable game"
    assert "Hollow Knight" in match.group(0)


def test_picking_a_game_stores_it_and_moves_on(client: Client, game: Game) -> None:
    response = client.post(reverse("contributions:declare"), {"game": str(game.pk)})
    assert response.status_code == 302
    assert response["Location"] == reverse("contributions:declare_details")
    assert client.session[SESSION_KEY]["game"] == str(game.pk)


def test_a_junk_game_id_does_not_500(client: Client) -> None:
    """Public page, unauthenticated POST — junk must re-render, never crash."""
    for junk in ("abc", "-1", "999999999", "", "²"):
        response = client.post(reverse("contributions:declare"), {"game": junk})
        assert response.status_code == 200, junk
        assert SESSION_KEY not in client.session, junk


def test_repicking_a_different_game_clears_the_old_employer(client: Client, game: Game) -> None:
    """Step 2's own "Wrong game?" link leads here. The stale employer is
    unclearable through the UI (the funnel's JS can only set a company, never
    clear one), so a different pick must drop it — but `discipline`,
    `job_title`, `start_date` and `end_date` are game-independent, so a
    different pick must not throw those away too."""
    other = Game.objects.create(title="Celeste", source=Game.Source.MANUAL)
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk), "company": "42", "job_title": "Artist"}
    session.save()

    client.post(reverse("contributions:declare"), {"game": str(other.pk)})

    assert client.session[SESSION_KEY] == {"game": str(other.pk), "job_title": "Artist"}


def test_repicking_the_same_game_keeps_the_draft(client: Client, game: Game) -> None:
    """A visitor who re-picks the title they already had must not lose what
    they typed."""
    session = client.session
    session[SESSION_KEY] = {"game": str(game.pk), "company": "42", "job_title": "Artist"}
    session.save()

    client.post(reverse("contributions:declare"), {"game": str(game.pk)})

    assert client.session[SESSION_KEY] == {
        "game": str(game.pk),
        "company": "42",
        "job_title": "Artist",
    }


def test_no_match_says_so_and_offers_the_account(client: Client) -> None:
    """igdb_search is login-gated and stays that way, so a miss converts into a
    signup rather than a dead end."""
    body = client.post(reverse("contributions:declare"), {"q": "zzzznotagame"}).content
    assert b"No match" in body
    assert reverse("accounts:signup").encode() in body


def test_home_routes_anonymous_visitors_to_declare(client: Client) -> None:
    """The question and its game form live at /declare/ now; the home page
    links there from a one-line banner (spec 2026-08-20 supersedes the
    2026-08-11 funnel-first order)."""
    body = client.get(reverse("home")).content.decode()
    assert "Which game did you work on?" not in body
    main = body[body.index("<main") : body.index("</main>")]
    assert reverse("contributions:declare") in main


def test_the_search_post_is_rate_limited(client: Client, settings: Any) -> None:
    """This is where /declare/'s trigram search over Game actually runs — an
    unmetered anonymous search otherwise (docs/02-ARCHITECTURE.md §5)."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    assert client.post(url, {"q": "a"}).status_code == 200
    assert client.post(url, {"q": "a"}).status_code == 403


def test_a_bare_get_is_never_rate_limited(client: Client, settings: Any) -> None:
    """The page itself must always answer, the same reason the home page's
    front door is unmetered — only a request that actually searches (carries
    a non-blank `q`) spends quota. This pins the bare-GET case specifically;
    it says nothing about a GET that carries `q` — see
    test_a_searching_get_is_rate_limited for that one, which used to pass for
    free through this same view."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    client.post(url, {"q": "a"})
    client.post(url, {"q": "a"})
    assert client.get(url).status_code == 200


def test_a_searching_get_is_rate_limited(client: Client, settings: Any) -> None:
    """`GET /declare/?q=…` used to run the trigram search over the whole
    `Game` table with no metering at all: get_context_data() read `q` from
    either GET or POST, but the rate-limit check only ever ran inside
    post() — a one-character bypass of the POST-only limit. GET and POST now
    share one counter."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    assert client.get(url, {"q": "hollow"}).status_code == 200
    assert client.get(url, {"q": "hollow"}).status_code == 403


def test_a_searching_get_and_the_search_post_share_one_counter(
    client: Client, settings: Any
) -> None:
    """Both metered paths spend from the same named counter
    (_DECLARE_GAME_RATELIMIT_GROUP) — a visitor cannot dodge the limit by
    switching methods mid-stream."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    assert client.post(url, {"q": "hollow"}).status_code == 200
    assert client.get(url, {"q": "hollow"}).status_code == 403


def test_picking_a_game_is_never_rate_limited(client: Client, game: Game, settings: Any) -> None:
    """PeopleSearchView — this view's cited model — meters only requests that
    actually search. The POST that carries `game` is a pick, not a search, so
    it must not share the search POST's quota: a visitor who searched once
    and is now clicking a result must not find the click itself blocked."""
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("contributions:declare")
    for _ in range(3):
        response = client.post(url, {"game": str(game.pk)})
        assert response.status_code == 302


def test_home_does_not_pitch_a_member(client: Client) -> None:
    """They already have an account — the invitation is spent."""
    user = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(user)
    body = client.get(reverse("home")).content
    assert b"Worked on a game?" not in body
    assert b"Find people by what they" in body


def test_a_local_miss_offers_igdb_matches_to_an_anonymous_visitor(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The funnel is where a signed-out visitor first meets a missing game.
    It used to be a dead end that offered signup (spec §4)."""
    monkeypatch.setattr(
        IGDBClient,
        "search_games",
        lambda self, q, limit=10: [
            {"id": 40477, "name": "Slay the Spire", "first_release_date": 1548201600}
        ],
    )
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert b"Not in our catalogue yet" in response.content
    assert b"Slay the Spire (2019)" in response.content
    assert b'name="igdb" value="40477"' in response.content


def test_local_matches_never_reach_igdb(
    client: Client, game: Game, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or [])
    response = client.get(reverse("contributions:declare"), {"q": "Hollow Knight"})
    assert b"Hollow Knight" in response.content
    assert calls == []


def test_igdb_being_down_leaves_the_page_usable(
    client: Client, igdb_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never an error page: the visitor still gets the signup route."""

    def boom(self: IGDBClient, query: str, limit: int = 10) -> list[dict[str, Any]]:
        raise IGDBError("down")

    monkeypatch.setattr(IGDBClient, "search_games", boom)
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert b"IGDB is unavailable right now" in response.content
    assert b"Create your account" in response.content


def test_over_quota_falls_back_to_the_signup_line(
    client: Client, igdb_configured: None, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.IGDB_RATELIMIT = "0/m"
    calls: list[str] = []
    monkeypatch.setattr(IGDBClient, "search_games", lambda self, q, limit=10: calls.append(q) or [])
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert response.status_code == 200
    assert calls == []
    assert b"Create your account" in response.content


def test_unconfigured_igdb_changes_nothing(client: Client) -> None:
    """Default test settings blank the credentials: byte-for-byte the old
    behaviour."""
    response = client.get(reverse("contributions:declare"), {"q": "Slay the Spire"})
    assert b"Not in our catalogue yet" not in response.content
    assert b"Create your account" in response.content
