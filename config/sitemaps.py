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

_DISALLOW = ["/admin/", "/account/", "/profile/", "/credits/", "/contact/", "/report/", "/search/"]

# Emitted BEFORE the disallows, and that order is load-bearing. RFC 9309 §2.2.2
# picks the longest match, but parsers with first-match semantics — Python's own
# `urllib.robotparser` among them — take whichever rule they read first.
# Allow-first is correct under both.
#
# Public profile, game and company pages are a major acquisition channel ("who
# worked on X"), so they are explicitly opened despite the disallows below.
_ALLOW = ["/u/", "/g/", "/c/"]


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
