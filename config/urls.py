"""Root URL configuration.

App URL modules are included here as their phases land (see ROADMAP.md).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Accounts own the root: /signup, /login, /settings, /u/<slug>/ … (SEO for
    # "who worked on X" wants clean profile URLs). Later phases add /games etc.
    path("", include("accounts.urls")),
    path("", include("games.urls")),
    path("credits/", include("contributions.urls")),
    path("search/", include("search.urls")),
    # Phase 6 — recruiters & contact relay: path("", include("contact.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
