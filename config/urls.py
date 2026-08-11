"""Root URL configuration.

App URL modules are included here as their phases land (see ROADMAP.md).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.generic import TemplateView

from config.sitemaps import SITEMAPS, robots_txt
from search.views import PeopleSearchView

urlpatterns = [
    # The root IS the people search — not a redirect to it, so the URL name
    # `home` keeps resolving for the logo and every other link.
    path("", PeopleSearchView.as_view(), name="home"),
    path("admin/", admin.site.urls),
    path("robots.txt", robots_txt),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("terms/", TemplateView.as_view(template_name="legal/terms.html"), name="terms"),
    path("privacy/", TemplateView.as_view(template_name="legal/privacy.html"), name="privacy"),
    # Accounts own the root: /signup, /login, /account, /u/<slug>/ … (SEO for
    # "who worked on X" wants clean profile URLs). Later phases add /games etc.
    path("", include("accounts.urls")),
    path("", include("games.urls")),
    path("", include("contact.urls")),
    path("", include("contributions.urls")),
    path("search/", include("search.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
