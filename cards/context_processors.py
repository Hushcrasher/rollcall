"""Open Graph defaults for every page; profile and game views override them
(spec §1). og:url drops the query string — the canonical page, not a filter set."""

from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext as _

from cards.data import card_url, default_card


def og_defaults(request: HttpRequest) -> dict[str, Any]:
    return {
        "og_title": "Rollcall",
        "meta_description": _(
            "Find people by what they've worked on — a public credits register for the "
            "game industry."
        ),
        "og_type": "website",
        "og_url": request.build_absolute_uri(request.path),
        "og_image": card_url(request, "cards:default", default_card()),
    }
