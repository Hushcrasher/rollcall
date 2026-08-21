"""SEO surface — sitemap of public pages + robots.txt.

Public profile and game pages are a major acquisition channel ("who worked on
X"), so we let crawlers index them; private profiles are excluded, and
account/moderation areas are disallowed.
"""

from django.contrib.sitemaps import Sitemap
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from accounts.models import User
from games.models import Company, Game

_DISALLOW = [
    "/admin/",
    "/account/",
    "/profile/",
    "/credits/",
    "/declare/",
    "/contact/",
    "/report/",
    "/search/",
    # The people search is the home page, so its combinatorial filter-URL space
    # (`/?discipline=3&engines=5&page=2`) cannot be closed with a path prefix —
    # `Disallow: /` would delist the whole site. Closed by query string instead:
    # `/` carries none and stays crawlable, as a home page must, and `/u/`,
    # `/g/`, `/c/` are clean-path URLs, so nothing indexable is lost.
    #
    # Coverage is PARTIAL and deliberately so. RFC 9309 §2.2.3 defines `*` in a
    # path and Google and Bing implement it, but `urllib.robotparser` ignores
    # wildcards and reads this as a literal prefix matching nothing. The trap is
    # shut for the crawlers that would actually burn budget on it. The root
    # template's rel=canonical is the second layer for anything that gets past.
    "/*?",
]

# Emitted BEFORE the disallows. RFC 9309 §2.2.2 picks the longest match while
# parsers with first-match semantics (Python's own `urllib.robotparser` among
# them) take whichever rule they read first, so Allow-first is kept as the safe
# default under both kinds of parser.
#
# Public profile, game and company pages are a major acquisition channel ("who
# worked on X"), so they are listed explicitly rather than left to whatever a
# crawler infers from the disallows below.
#
# The `card.png` entries are load-bearing, not decorative: every `og:image` URL
# carries a `?v=` token (cards/data.py `card_url`), so `Disallow: /*?` below
# matches all three of them for a wildcard-aware crawler. They must be allowed
# explicitly and their patterns must stay LONGER than `/*?` to win the longest-
# match rule — `/u/` alone would only tie-break against it by length, and
# `/card.png?v=…` would have no matching Allow at all. Networks fetching
# og:image mostly ignore robots.txt, but a blocked card is a silently broken
# link preview, so the rule is written for the ones that do honour it.
_ALLOW = ["/u/", "/g/", "/c/", "/card.png", "/u/*/card.png", "/g/*/card.png"]


class ProfileSitemap(Sitemap):
    changefreq = "weekly"

    def items(self) -> QuerySet[User]:
        return User.objects.filter(profile_public=True).order_by("id")  # private excluded


class GameSitemap(Sitemap):
    changefreq = "weekly"

    def items(self) -> QuerySet[Game]:
        return Game.objects.order_by("id")


class CompanySitemap(Sitemap):
    changefreq = "weekly"

    def items(self) -> QuerySet[Company]:
        return Company.objects.order_by("id")


SITEMAPS = {
    "profiles": ProfileSitemap,
    "games": GameSitemap,
    "companies": CompanySitemap,
}


def robots_txt(request: HttpRequest) -> HttpResponse:
    sitemap_url = request.build_absolute_uri(reverse("sitemap"))
    lines = ["User-agent: *"]
    lines += [f"Allow: {path}" for path in _ALLOW]
    lines += [f"Disallow: {path}" for path in _DISALLOW]
    lines.append(f"Sitemap: {sitemap_url}")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")
