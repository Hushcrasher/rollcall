"""Recruiter search view — open to everyone (platform is free; findability IS
the service). Anti-scraping: the IP rate limit, pagination and `profile_public`
are the real mitigations; the >=1-filter rule is only a UX guard."""

import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.cache import cache
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
    response = client.get(reverse("search:recruiter_search"))
    assert response.status_code == 200
    assert b"discipline" in response.content.lower()


def test_member_is_not_redirected_to_apply(client: Client) -> None:
    member = User.objects.create_user(email="m@example.com", password="x", display_name="M")
    client.force_login(member)
    assert client.get(reverse("search:recruiter_search")).status_code == 200


def test_zero_filters_shows_error_and_no_people(client: Client) -> None:
    """UX guard: the accidental filterless submit lists nobody."""
    _candidate()
    response = client.get(reverse("search:recruiter_search"), {"discipline": ""})
    assert b"Pick at least one filter." in response.content
    assert b"Great Candidate" not in response.content


def test_anonymous_search_returns_matches_without_leaking_email(client: Client) -> None:
    _candidate()
    design = Discipline.objects.get(name="Design")

    response = client.get(reverse("search:recruiter_search"), {"discipline": design.pk})

    assert b"Great Candidate" in response.content
    assert b"candidate@example.com" not in response.content


def test_private_profile_is_never_listed(client: Client) -> None:
    _candidate(profile_public=False)
    design = Discipline.objects.get(name="Design")

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert "Great Candidate" not in content
    assert "No people match these filters." in content


def test_result_card_shows_credit_location_and_stats(client: Client) -> None:
    _candidate(location="Lyon", country="FR")
    design = Discipline.objects.get(name="Design")

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert "Card Game" in content  # the matching credit
    assert "Level Designer" in content
    assert "(Design)</em>" in content  # the discipline of the matching credit
    assert "2020–2021" in content  # the credit's dates
    assert "Lyon · France" in content
    # Career stats. Asserted as the whole rendered line, singulars included:
    # a `{% blocktranslate count %}` that silently lost its {% plural %} branch
    # would print "1 credits" and still satisfy a loose `"1 credit" in content`.
    assert "1 credit · 1 game · 2020–2021" in content
    # An unguarded {% if r.more_credits_count %} renders "+0 more" on every
    # card that has <=3 credits — i.e. on most of them.
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

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert "2020–present" in content  # career years, open end
    assert "2022–present" in content  # the ongoing credit's own dates
    assert "2 credits · 2 games" in content
    assert "None" not in content
    # The label is load-bearing, not decoration: bare "Unreal Engine 100%" under
    # a career-stats line reads as a proficiency score for the person, which the
    # "no numeric public score" non-negotiable exists to prevent. The words are
    # what make the number factual — about games, not about the person.
    assert "Engines on credited games: Unreal Engine 100%" in content


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

    content = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk}
    ).content.decode()

    assert "+2 more matching credits" in content


def test_rate_limited(client: Client, settings: Any) -> None:
    settings.RATELIMIT_ENABLE = True
    settings.SEARCH_RATELIMIT = "1/m"
    cache.clear()

    url = reverse("search:recruiter_search")
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 403


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

    url = reverse("search:recruiter_search")
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
        reverse("search:recruiter_search"),
        {"engines": [unreal.pk, unity.pk]},
    ).content.decode()

    params = _link_params(content, "Next")
    assert sorted(params["engines"]) == sorted([str(unreal.pk), str(unity.pk)])
    assert params["page"] == ["2"]


def test_junk_page_param_does_not_error(client: Client) -> None:
    _candidate()
    design = Discipline.objects.get(name="Design")
    response = client.get(
        reverse("search:recruiter_search"), {"discipline": design.pk, "page": "abc"}
    )
    assert response.status_code == 200
    assert b"Great Candidate" in response.content
