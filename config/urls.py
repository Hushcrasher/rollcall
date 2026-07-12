"""Root URL configuration.

App URL modules are included here as their phases land (see ROADMAP.md).
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Phase 3 — accounts: path("", include("accounts.urls")),
    # Phase 4 — games & contributions: path("", include("games.urls")), ...
    # Phase 5 — search: path("search/", include("search.urls")),
    # Phase 6 — recruiters & contact relay: path("", include("contact.urls")),
]
