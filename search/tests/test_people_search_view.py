"""The people search — the home page, open to everyone (platform is free;
findability IS the service). Anti-scraping: the IP rate limit, pagination and
`profile_public` are the real mitigations; the >=1-filter rule is only a UX
guard."""

import re
from datetime import date
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.cache import cache, caches
from django.test import Client
from django.urls import reverse

from accounts.models import User
from contributions.models import Contribution, Discipline
from games.models import Engine, Game

pytestmark = pytest.mark.django_db


def _link_params(content: str, label: str) -> dict[str, list[str]]:
    """The GET params of the "Next"/"Previous" link's own href.

    Asserted through the href rather than `"discipline=2" in content`: that
    looser form passes on a link that dropped every filter, as long as the
    string occurs anywhere else on the page (it did — a malformed comment was
    emitting one).
    """
    match = re.search(rf'<a href="([^"]*)">{label}</a>', content)
    assert match is not None, f"no {label} link in:\n{content[-3000:]}"
    from html import unescape

    return parse_qs(urlparse(unescape(match.group(1))).query)


def _candidate(name: str = "Great Candidate", **user_kwargs: Any) -> User:
    design = Discipline.objects.get(name="Design")
    game = Game.objects.create(title="Card Game", source=Game.Source.MANUAL)
    user = User.objects.create_user(
        email="candidate@example.com", password="x", display_name=name, **user_kwargs
    )
    Contribution.objects.create(
        user=user,
        game=game,
        discipline=design,
        job_title="Level Designer",
        start_date=date(2020, 1, 1),
        end_date=date(2021, 6, 1),
    )
    return user


def test_search_page_is_public(client: Client) -> None:
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert b"discipline" in response.content.lower()


def test_member_is_not_redirected_to_apply(client: Client) -> None:
    member = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(member)
    assert client.get(reverse("home")).status_code == 200


def test_zero_filters_shows_error_and_no_people(client: Client) -> None:
    """UX guard: the accidental filterless submit lists nobody."""
    _candidate()
    response = client.get(reverse("home"), {"discipline": ""})
    assert b"Pick at least one filter." in response.content
    assert b"Great Candidate" not in response.content


def test_anonymous_search_returns_matches_without_leaking_email(client: Client) -> None:
    _candidate()
    design = Discipline.objects.get(name="Design")

    response = client.get(reverse("home"), {"discipline": design.pk})

    assert b"Great Candidate" in response.content
    assert b"candidate@example.com" not in response.content


def test_private_profile_is_never_listed(client: Client) -> None:
    _candidate(profile_public=False)
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert "Great Candidate" not in content
    assert "No people match these filters." in content


def test_result_card_shows_credit_location_and_stats(client: Client) -> None:
    _candidate(location="Lyon", country="FR")
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert "Card Game" in content  # the matching credit
    assert "Level Designer" in content
    assert "(Design)</em>" in content  # the discipline of the matching credit
    assert "2020–2021" in content  # the credit's dates
    assert "Lyon · France" in content
    # Career stats live in their own columns now (spec 2026-08-24-results-table),
    # so the old combined line is gone and with it the {% plural %} branch it
    # guarded — a count column is a bare number under a header, which has no
    # singular. Asserted per cell, header included, so a column silently losing
    # its data-label (which is what reinstates the header on a phone) fails here.
    assert '<td class="num" data-label="Credits">1</td>' in content
    assert '<td class="num" data-label="Games">1</td>' in content
    assert "2020–2021" in content  # the industry span column
    # An unguarded {% if r.more_credits_count %} renders "+0 more" on every
    # row that has <=3 credits — i.e. on most of them.
    assert "+0 more" not in content


def test_card_renders_present_and_engine_shares_and_never_none(client: Client) -> None:
    unreal = Engine.objects.create(name="Unreal Engine")
    user = _candidate()  # a closed 2020–2021 credit on "Card Game"
    design = Discipline.objects.get(name="Design")
    ongoing_game = Game.objects.create(title="Ongoing Game", source=Game.Source.MANUAL)
    ongoing_game.engines.add(unreal)
    Contribution.objects.create(
        user=user,
        game=ongoing_game,
        discipline=design,
        job_title="Designer",
        start_date=date(2022, 1, 1),
    )

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert "2020–present" in content  # career years, open end
    assert "2022–present" in content  # the ongoing credit's own dates
    assert '<td class="num" data-label="Credits">2</td>' in content
    assert '<td class="num" data-label="Games">2</td>' in content
    assert "None" not in content
    # The label is load-bearing, not decoration: a bare "Unreal Engine 100%"
    # beside a person reads as a proficiency score for them, which the "no
    # numeric public score" non-negotiable exists to prevent. In a table the
    # COLUMN HEADER carries that job, so it has to name what the number measures
    # — the person's credited games, not the person.
    assert '<th scope="col">Engines on credited games</th>' in content
    assert "Unreal Engine 100%" in content


def test_more_credits_count_is_shown_beyond_three(client: Client) -> None:
    user = _candidate()
    design = Discipline.objects.get(name="Design")
    for i in range(4):  # 1 existing + 4 = 5 matching credits, 3 shown
        game = Game.objects.create(title=f"Extra Game {i}", source=Game.Source.MANUAL)
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=design,
            job_title="Designer",
            start_date=date(2022, 1, 1 + i),
        )

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert "+2 more matching credits" in content


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


def test_rate_limit_holds_while_other_ips_fill_the_cache(client: Client, settings: Any) -> None:
    """A blocked IP stays blocked while ordinary traffic flows.

    Rate-limit counters are one cache key per client IP, and LocMemCache culls
    keys once past `MAX_ENTRIES` — at the 300-entry default, ~300 other visitors
    evict a live counter and the limit resets to zero. Silent, and it needs no
    attacker: 300 distinct IPs is a normal day. `docs/01-DESIGN.md` §3.6 names
    this limit as the real anti-scraping mitigation, so "it holds under traffic"
    is the invariant, not "the decorator is applied".

    The other IPs are written straight to the cache: eviction pressure is key
    count, and 1k real requests would cost seconds for the same pressure.

    Prod no longer uses this backend — its cache is Redis, which does not cull
    on `MAX_ENTRIES` — so the scenario below is a dev/test-only concern now.
    The test stays anyway, because the backend it exercises (`LocMemCache`)
    stays in dev and tests.
    """
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("home")
    search = {"open_to_work": "on"}
    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 200
    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 403

    for i in range(1_000):
        cache.set(f"rlbucket:10.1.{i // 256}.{i % 256}", 1, 60)

    assert client.get(url, search, REMOTE_ADDR="10.0.0.1").status_code == 403


def test_a_cache_failure_does_not_lock_everyone_out(client: Client, settings: Any) -> None:
    """django-ratelimit fails CLOSED by default: when the cache does not answer
    it returns `should_limit: True`, so a Redis outage would 403 every
    rate-limited page at once. The limit is a mitigation, not a boundary
    (docs/01-DESIGN.md §3.6) — the site staying up is worth more than a window
    of unmetered traffic.

    The failure is simulated rather than staged with a real Redis: this is
    exactly the shape django-redis's IGNORE_EXCEPTIONS produces — `add` returns
    falsy, `incr` returns `None` (django_ratelimit/core.py notes memcached
    raises ValueError on an unreachable server, while redis simply returns
    None) — so the branch under test is the one prod will take.
    """
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    backend = caches["default"]
    url = reverse("home")
    search = {"open_to_work": "on"}

    with (
        mock.patch.object(backend, "add", return_value=False),
        mock.patch.object(backend, "incr", return_value=None),
    ):
        # Well past the 1/m limit: none of these may be refused.
        for _ in range(5):
            assert client.get(url, search).status_code == 200


def test_pagination_preserves_filters(client: Client) -> None:
    design = Discipline.objects.get(name="Design")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    for i in range(21):  # RESULTS_PER_PAGE + 1
        user = User.objects.create_user(
            email=f"u{i}@example.com", password="x", display_name=f"Person {i:02d}"
        )
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=design,
            job_title="Dev",
            start_date=date(2020, 1, 1),
        )

    url = reverse("home")
    content = client.get(url, {"discipline": design.pk}).content.decode()

    # The filter must ride along in the Next link itself, or page 2 silently
    # paginates an unfiltered search.
    assert _link_params(content, "Next") == {"discipline": [str(design.pk)], "page": ["2"]}
    assert "Person 20" not in content  # page 1 stops at 20 people
    assert ">Previous<" not in content  # no dead Previous link on page 1
    # A `{# … #}` comment spanning >1 line is not lexed as a comment: its text
    # leaks into the HTML and the tags inside it execute. Use {% comment %}.
    assert "{#" not in content
    # base.html already emits two unlabelled <nav>s; without this the page has
    # three identical "navigation" landmarks for screen readers.
    assert '<nav class="pagination" aria-label="Pagination">' in content

    page2 = client.get(url, {"discipline": design.pk, "page": "2"}).content.decode()
    assert "Person 20" in page2
    assert _link_params(page2, "Previous") == {"discipline": [str(design.pk)], "page": ["1"]}
    assert ">Next<" not in page2  # last page


def test_multi_value_filters_survive_pagination_links(client: Client) -> None:
    """{% querystring %} must keep repeated params, not collapse them."""
    design = Discipline.objects.get(name="Design")
    unreal = Engine.objects.create(name="Unreal Engine")
    unity = Engine.objects.create(name="Unity")
    game = Game.objects.create(title="G", source=Game.Source.MANUAL)
    game.engines.add(unreal)
    for i in range(21):
        user = User.objects.create_user(
            email=f"u{i}@example.com", password="x", display_name=f"Person {i:02d}"
        )
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=design,
            job_title="Dev",
            start_date=date(2020, 1, 1),
        )

    content = client.get(
        reverse("home"),
        {"engines": [unreal.pk, unity.pk]},
    ).content.decode()

    params = _link_params(content, "Next")
    assert sorted(params["engines"]) == sorted([str(unreal.pk), str(unity.pk)])
    assert params["page"] == ["2"]


def test_junk_page_param_does_not_error(client: Client) -> None:
    _candidate()
    design = Discipline.objects.get(name="Design")
    response = client.get(reverse("home"), {"discipline": design.pk, "page": "abc"})
    assert response.status_code == 200
    assert b"Great Candidate" in response.content


def test_result_card_has_no_message_button(client: Client) -> None:
    """Spec 2026-08-24 §2: the profile is the single contact entry point —
    a card links to the person, never to the relay."""
    user = _candidate()
    design = Discipline.objects.get(name="Design")
    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()
    assert reverse("accounts:profile", args=[user.slug]) in content
    assert reverse("contact:contact", args=[user.slug]) not in content


def test_games_facet_filters_the_page(client: Client) -> None:
    """?games=<pk> is a real search: it binds the form, replaces the feed, and
    returns only people credited on that game."""
    hades = Game.objects.create(title="Hades", source=Game.Source.MANUAL)
    other = Game.objects.create(title="Other", source=Game.Source.MANUAL)
    discipline = Discipline.objects.get(name="Design")
    on_hades = User.objects.create_user(
        email="h@example.com", password="x", display_name="Hades Dev"
    )
    Contribution.objects.create(
        user=on_hades,
        game=hades,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )
    elsewhere = User.objects.create_user(
        email="o@example.com", password="x", display_name="Other Dev"
    )
    Contribution.objects.create(
        user=elsewhere,
        game=other,
        discipline=discipline,
        job_title="Dev",
        start_date=date(2020, 1, 1),
    )

    content = client.get(reverse("home"), {"games": str(hades.pk)}).content.decode()

    assert "Hades Dev" in content
    assert "Other Dev" not in content
    assert "Latest credits" not in content


# --- The results table (spec 2026-08-24-results-table) ----------------------


def test_results_render_as_one_table_with_named_columns(client: Client) -> None:
    """A recruiter compares people, and comparing is what a table is for. The
    seven headers are the contract the narrow-screen rules restore per cell."""
    _candidate()
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert '<table class="results-table">' in content
    for header in (
        "Name",
        "Based in",
        "Experience",
        "Credits",
        "Games",
        "In the industry",
        "Engines on credited games",
    ):
        assert f'<th scope="col">{header}</th>' in content, header
    assert content.count("<tbody>") == 1


def test_every_cell_carries_its_header_for_narrow_screens(client: Client) -> None:
    """Below 768px the columns stack and app.css reinstates each header from
    `data-label`. A cell without one loses its meaning on a phone, and no CSS
    test can catch that — this is the guard."""
    _candidate()
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()
    row = content[content.index("<tbody>") : content.index("</tbody>")]

    cells = re.findall(r"<t[hd][^>]*>", row)
    assert cells, "no cells rendered"
    assert all("data-label=" in cell for cell in cells), row


def test_the_table_can_scroll_inside_its_own_box(client: Client) -> None:
    """Seven columns must not push the page sideways — wide content scrolls in
    its own container, never the document."""
    _candidate()
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert '<div class="table-scroll">' in content


def test_an_experience_line_reads_dates_role_then_game(client: Client) -> None:
    _candidate(location="Lyon", country="FR")
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert "01/2020–06/2021" in content
    assert "Level Designer <em>(Design)</em> at" in content


def test_the_extra_credits_count_links_to_the_profile(client: Client) -> None:
    """ "+N more" is where the rest of a career is — it has to be reachable, not
    a dead count."""
    user = _candidate()
    design = Discipline.objects.get(name="Design")
    for n in range(4):
        game = Game.objects.create(title=f"Extra {n}", source=Game.Source.MANUAL)
        Contribution.objects.create(
            user=user,
            game=game,
            discipline=design,
            job_title="Designer",
            start_date=date(2015, 1, 1),
        )

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    profile = reverse("accounts:profile", args=[user.slug])
    assert f'<a class="more-credits" href="{profile}">' in content
    assert "more matching credits" in content


def test_a_person_with_no_location_gets_a_dash_not_a_blank(client: Client) -> None:
    """An empty cell in a table reads as missing data rather than "not given",
    and leaves the row looking broken."""
    _candidate()  # no location, no country
    design = Discipline.objects.get(name="Design")

    content = client.get(reverse("home"), {"discipline": design.pk}).content.decode()

    assert '<td data-label="Based in">—</td>' in content


def test_no_results_shows_the_message_and_no_empty_table(client: Client) -> None:
    """An empty table is a header row with nothing under it — worse than a
    sentence."""
    _candidate()
    other = Discipline.objects.get(name="Audio")

    content = client.get(reverse("home"), {"discipline": other.pk}).content.decode()

    assert "No people match these filters." in content
    assert '<table class="results-table">' not in content
