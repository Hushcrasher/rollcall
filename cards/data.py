"""CardData builders — the only fields a card may ever show (spec §2)."""

import hashlib
from dataclasses import astuple
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from accounts.models import User
from cards.render import DEFAULT_TAGLINE, CardData
from contributions.models import Contribution
from games.models import Game
from search.services import profile_summary


def default_card() -> CardData:
    return CardData(kind="default", title="ROLLCALL", footer=str(DEFAULT_TAGLINE))


def profile_card(user: User) -> CardData:
    latest = (
        Contribution.objects.filter(user=user, status=Contribution.Status.ACTIVE)
        .order_by("-start_date", "-id")
        .values_list("job_title", flat=True)
        .first()
    )
    summary = profile_summary(user)
    stats = ""
    if summary:
        credits_label = ngettext("%(n)d credit", "%(n)d credits", summary.credits_count) % {
            "n": summary.credits_count
        }
        games_label = ngettext("%(n)d game", "%(n)d games", summary.games_count) % {
            "n": summary.games_count
        }
        stats = " · ".join([credits_label, games_label, summary.years_label])
    return CardData(
        kind="profile",
        title=str(user.display_name),
        subtitle=latest or "",
        stats=stats,
        footer=user.location_display,
        badge=_("Open to work") if user.open_to_work else "",
    )


def game_card(game: Game) -> CardData:
    # profile_public filter: a private profile's credit must not make the
    # game's people-count observable through this public, unauthenticated
    # endpoint (docs/01-DESIGN.md §3.4 — invisible everywhere, unconditionally).
    people = (
        Contribution.objects.filter(
            game=game, status=Contribution.Status.ACTIVE, user__profile_public=True
        )
        .values("user_id")
        .distinct()
        .count()
    )
    stats = (
        ngettext("%(n)d person credited on Rollcall", "%(n)d people credited on Rollcall", people)
        % {"n": people}
        if people
        else _("Be the first to claim a credit")
    )
    # release_date is a `date` at runtime; the type checker sees the DateField.
    release: Any = game.release_date
    return CardData(
        kind="game",
        title=str(game.title),
        subtitle=_("Released %(year)d") % {"year": release.year} if release else "",
        stats=stats,
    )


def token(data: CardData) -> str:
    """Short, stable digest of what the card shows — a changed profile gets a
    new image URL, so networks that cache og:image for days refetch it."""
    return hashlib.sha256(repr(astuple(data)).encode()).hexdigest()[:10]


def card_url(request: HttpRequest, url_name: str, data: CardData, *args: Any) -> str:
    return request.build_absolute_uri(reverse(url_name, args=args)) + "?v=" + token(data)
