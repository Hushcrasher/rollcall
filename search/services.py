"""Search services — the ONLY place search logic lives (docs/02-ARCHITECTURE.md
§2.3), so Postgres pg_trgm can later be swapped for a dedicated engine without
touching callers.

Combines trigram similarity (typo tolerance: "hade" → "Hades") with a
case-insensitive contains (prefix matches for autocomplete).
"""

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q, QuerySet

from games.models import Company, Game

_SIMILARITY_THRESHOLD = 0.15


def search_games(query: str, limit: int = 10) -> QuerySet[Game]:
    stripped = query.strip()
    if not stripped:
        return Game.objects.none()
    return (
        Game.objects.annotate(similarity=TrigramSimilarity("title", stripped))
        .filter(Q(similarity__gt=_SIMILARITY_THRESHOLD) | Q(title__icontains=stripped))
        .order_by("-similarity", "title")[:limit]
    )


def search_companies(query: str, limit: int = 10) -> QuerySet[Company]:
    stripped = query.strip()
    if not stripped:
        return Company.objects.none()
    return (
        Company.objects.annotate(similarity=TrigramSimilarity("name", stripped))
        .filter(Q(similarity__gt=_SIMILARITY_THRESHOLD) | Q(name__icontains=stripped))
        .order_by("-similarity", "name")[:limit]
    )
