"""The card endpoints: cached, rate-limited PNGs. Only public profiles have a
card — crawlers fetch without a session, so the owner exemption of the profile
page does not apply here."""

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_safe
from django_ratelimit.decorators import ratelimit

from accounts.models import User
from cards.data import default_card, game_card, profile_card, token
from cards.render import CardData, render
from games.models import Game

CACHE_SECONDS = 3600
# Named group, house rule: an unnamed decorator derives its group from the
# view's qualname, so a rename would silently move the counter.
_RATELIMIT_GROUP = "card"
# django_ratelimit.decorators monkey-patches `.ALL` onto the function at import
# time; ty's static analysis can't see that assignment, hence the ignore.
_ALL_METHODS = ratelimit.ALL  # ty: ignore[unresolved-attribute]


def _card_rate(group: str, request: HttpRequest) -> str:
    return settings.PROFILE_RATELIMIT


def _png_response(key: str, data: CardData) -> HttpResponse:
    def _render() -> bytes:
        return render(data)

    png = cache.get_or_set(f"card:{data.kind}:{key}:{token(data)}", _render, CACHE_SECONDS)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# require_safe above ratelimit: a GET/HEAD-only gate, checked BEFORE the
# limiter runs, so POST/PUT get a plain 405 without spending any quota.
# method=_ALL_METHODS (not "GET"): GET and HEAD must land in the same
# counter, or a client alternating verbs gets double the effective quota —
# contributions/views.py's DeclareGameView documents the same reasoning for
# is_ratelimited().
@require_safe
@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method=_ALL_METHODS, block=True)
def profile_card_view(request: HttpRequest, slug: str) -> HttpResponse:
    # profile_public=True in the lookup itself, not a post-fetch check: a
    # private profile 404s exactly like a nonexistent one, for the owner too
    # (spec — crawlers never carry a session, so there is no owner exemption).
    user = get_object_or_404(User, slug=slug, profile_public=True)
    return _png_response(slug, profile_card(user))


@require_safe
@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method=_ALL_METHODS, block=True)
def game_card_view(request: HttpRequest, slug: str) -> HttpResponse:
    game = get_object_or_404(Game, slug=slug)
    return _png_response(slug, game_card(game))


@require_safe
@ratelimit(group=_RATELIMIT_GROUP, key="ip", rate=_card_rate, method=_ALL_METHODS, block=True)
def default_card_view(request: HttpRequest) -> HttpResponse:
    return _png_response("site", default_card())
