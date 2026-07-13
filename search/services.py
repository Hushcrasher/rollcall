"""Search services — the ONLY place search logic lives (docs/02-ARCHITECTURE.md
§2.3), so Postgres pg_trgm can later be swapped for a dedicated engine without
touching callers.

Combines trigram similarity (typo tolerance: "hade" → "Hades") with a
case-insensitive contains (prefix matches for autocomplete).
"""

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q, QuerySet

from accounts.models import User
from contributions.models import Contribution
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


def search_people(query: str, limit: int = 20) -> QuerySet[User]:
    # profile_public filter FIRST: private profiles are invisible to search,
    # everywhere, unconditionally (docs/01-DESIGN.md §3.4).
    stripped = query.strip()
    if not stripped:
        return User.objects.none()
    return (
        User.objects.filter(profile_public=True)
        .annotate(similarity=TrigramSimilarity("display_name", stripped))
        .filter(Q(similarity__gt=_SIMILARITY_THRESHOLD) | Q(display_name__icontains=stripped))
        .order_by("-similarity", "display_name")[:limit]
    )


def recruiter_search(
    *,
    discipline_id: int | None = None,
    engine_id: int | None = None,
    genre_id: int | None = None,
    min_rating: float | None = None,
    open_to_work: bool | None = None,
    year_from: int | None = None,
) -> QuerySet[User]:
    """The product promise (docs/01-DESIGN.md §3.6, docs/04 §8): public people
    filtered by properties of the games they worked on, crossed with their
    discipline. Every filter applies to the SAME active contribution, so
    "Unreal × Programming" means one credit is both. Rating is a filter,
    never a sort — results order by display_name."""
    credits = Contribution.objects.filter(
        status=Contribution.Status.ACTIVE,
        game__isnull=False,
        user__profile_public=True,
    )
    if discipline_id is not None:
        credits = credits.filter(discipline_id=discipline_id)
    if engine_id is not None:
        credits = credits.filter(game__engines__id=engine_id)
    if genre_id is not None:
        credits = credits.filter(game__genres__id=genre_id)
    if min_rating is not None:
        credits = credits.filter(
            Q(game__steam_positive_pct__gte=min_rating) | Q(game__igdb_rating__gte=min_rating)
        )
    if year_from is not None:
        credits = credits.filter(start_date__year__gte=year_from)
    if open_to_work:
        credits = credits.filter(user__open_to_work=True)

    user_ids = credits.values_list("user_id", flat=True).distinct()
    return User.objects.filter(id__in=user_ids).order_by("display_name")
