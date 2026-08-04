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

# Carved out of the blanket `/search/` disallow below. `/search/for-recruiters/`
# is the public promise page — footer-linked sitewide, honest counts, and the CTA
# into the open people search: discovery by workers and recruiters is its entire
# job, so hiding it from crawlers defeats the point (same "major acquisition
# channel" reasoning as the profile/game pages above).
#
# `/search/recruiters/` itself stays disallowed: its combinatorial filter-URL
# space is a crawl trap, and the IP rate limit would just fight the crawler.
#
# Emitted BEFORE the disallows, and that order is load-bearing. RFC 9309 §2.2.2
# picks the longest match (so `Allow` would win here either way), but parsers
# with first-match semantics — Python's own `urllib.robotparser` among them —
# take whichever rule they read first. Allow-first is correct under both.
_ALLOW = ["/u/", "/g/", "/c/", "/search/for-recruiters/"]


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
