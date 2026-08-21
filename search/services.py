"""Search services — the ONLY place search logic lives (docs/02-ARCHITECTURE.md
§2.3), so Postgres pg_trgm can later be swapped for a dedicated engine without
touching callers.

Two unrelated kinds of search live here:

- Text lookup (`search_games` / `search_companies` / `search_people`): trigram
  similarity for typo tolerance ("hade" → "Hades"), OR a case-insensitive
  contains for autocomplete prefixes.
- `recruiter_search`: no text matching at all — a structured filter over the
  properties of the games people are credited on, assembled into result cards.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from django.contrib.postgres.search import TrigramSimilarity
from django.core.paginator import Paginator
from django.db.models import Count, Max, Min, Q, QuerySet
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from contributions.models import Contribution
from games.models import Company, Game

_SIMILARITY_THRESHOLD = 0.15

RESULTS_PER_PAGE = 20
MATCHING_CREDITS_SHOWN = 3
ENGINE_SHARES_SHOWN = 3

# Engine names are plain DB strings; the "other" bucket is a lazily-translated
# proxy. Templates render either transparently — this alias keeps the annotation
# honest rather than claiming every name is a `str`.
type EngineShareName = str | Promise


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


@dataclass(frozen=True)
class ProfileSummary:
    """Career-wide aggregate over ACTIVE credits — shared by the search cards
    and the OG cards so the two never disagree."""

    credits_count: int
    games_count: int
    first_year: int
    last_year: int | None  # None = an open end exists, i.e. "present"

    @property
    def years_label(self) -> str:
        return f"{self.first_year}–{self.last_year if self.last_year else _('present')}"


def profile_summaries(user_ids: list[int]) -> dict[int, ProfileSummary]:
    rows = (
        Contribution.objects.filter(status=Contribution.Status.ACTIVE, user_id__in=user_ids)
        .values("user_id")
        .annotate(
            credits_count=Count("id"),
            games_count=Count("game", distinct=True),
            first_start=Min("start_date"),
            last_end=Max("end_date"),
            open_count=Count("id", filter=Q(end_date__isnull=True)),
        )
    )
    summaries: dict[int, ProfileSummary] = {}
    for row in rows:
        # open_count > 0 is what "present" means. Max(end_date) can't answer it:
        # SQL MAX ignores NULLs, so an ongoing credit is invisible to it.
        still_active = row["open_count"] > 0
        summaries[row["user_id"]] = ProfileSummary(
            credits_count=row["credits_count"],
            games_count=row["games_count"],
            first_year=row["first_start"].year,
            # Not still_active ⇒ every credit has an end_date ⇒ last_end is set.
            last_year=None if still_active else row["last_end"].year,
        )
    return summaries


def profile_summary(user: User) -> ProfileSummary | None:
    return profile_summaries([user.pk]).get(user.pk)


@dataclass(frozen=True)
class PersonResult:
    """One fully-assembled recruiter-search result card (spec
    docs/superpowers/specs/2026-07-16-open-recruiter-search-design.md §4).
    Career stats are career-wide (all active credits), deliberately not
    filter-scoped; matching_credits are the filter-satisfying ones."""

    user: User
    matching_credits: list[Contribution]  # capped at MATCHING_CREDITS_SHOWN, recent first
    matching_credits_total: int
    credits_count: int
    games_count: int
    # Not `int | None`: a result exists only because it has >=1 active credit,
    # and start_date is NOT NULL — so there is always a first year.
    first_year: int
    last_year: int | None  # None = an open end exists, i.e. "present"
    engine_shares: list[tuple[EngineShareName, int]]  # [("Unreal Engine", 67), ..., ("other", 5)]

    @property
    def more_credits_count(self) -> int:
        return self.matching_credits_total - len(self.matching_credits)


@dataclass(frozen=True)
class ResultsPage:
    results: list[PersonResult]
    total: int
    page_number: int
    num_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page_number > 1

    @property
    def has_next(self) -> bool:
        return self.page_number < self.num_pages

    @property
    def previous_page_number(self) -> int | None:
        # None, not page_number - 1: an unguarded 0 fed back through get_page()
        # lands on the LAST page, so a "Previous" link on page 1 would jump to
        # the end. Templates render None as empty and treat it falsy.
        return self.page_number - 1 if self.has_previous else None

    @property
    def next_page_number(self) -> int | None:
        return self.page_number + 1 if self.has_next else None


def recruiter_search(
    *,
    discipline_id: int | None = None,
    engine_ids: Sequence[int] = (),
    genre_ids: Sequence[int] = (),
    countries: Sequence[str] = (),
    min_rating: float | None = None,
    open_to_work: bool | None = None,
    year_from: int | None = None,
    page: int | str | None = 1,  # raw GET value: get_page() coerces junk to 1
) -> ResultsPage:
    """The product promise (docs/01-DESIGN.md §3.6, docs/04 §8): public people
    filtered by properties of the games they worked on, crossed with their
    discipline. Credit-level filters apply to the SAME active contribution
    ("Unreal × Programming" means one credit is both); multi-value facets are
    OR within the facet, AND across facets; `countries` filters the person.
    Rating is a filter, never a sort — results order by display_name."""
    credits = _matching_credits(
        discipline_id=discipline_id,
        engine_ids=engine_ids,
        genre_ids=genre_ids,
        countries=countries,
        min_rating=min_rating,
        open_to_work=open_to_work,
        year_from=year_from,
    )
    users = User.objects.filter(id__in=credits.values("user_id")).order_by("display_name")
    paginator = Paginator(users, RESULTS_PER_PAGE)
    page_obj = paginator.get_page(page)
    return ResultsPage(
        results=_assemble_results(list(page_obj.object_list), credits),
        total=paginator.count,
        page_number=page_obj.number,
        num_pages=paginator.num_pages,
    )


def _matching_credits(
    *,
    discipline_id: int | None,
    engine_ids: Sequence[int],
    genre_ids: Sequence[int],
    countries: Sequence[str],
    min_rating: float | None,
    open_to_work: bool | None,
    year_from: int | None,
) -> QuerySet[Contribution]:
    # profile_public filter FIRST: private profiles are invisible to search,
    # everywhere, unconditionally (docs/01-DESIGN.md §3.4).
    credits = Contribution.objects.filter(
        status=Contribution.Status.ACTIVE,
        game__isnull=False,
        user__profile_public=True,
    )
    if discipline_id is not None:
        credits = credits.filter(discipline_id=discipline_id)
    if engine_ids:
        credits = credits.filter(game__engines__in=list(engine_ids))
    if genre_ids:
        credits = credits.filter(game__genres__in=list(genre_ids))
    if countries:
        credits = credits.filter(user__country__in=list(countries))
    if min_rating is not None:
        credits = credits.filter(
            Q(game__steam_positive_pct__gte=min_rating) | Q(game__igdb_rating__gte=min_rating)
        )
    if year_from is not None:
        credits = credits.filter(start_date__year__gte=year_from)
    if open_to_work:
        credits = credits.filter(user__open_to_work=True)
    return credits


def _assemble_results(users: list[User], credits: QuerySet[Contribution]) -> list[PersonResult]:
    """Assemble the page's cards in Python: three side-queries scoped to the
    page's users, so cost is bounded by page size rather than by result count."""
    if not users:
        return []
    user_ids = [user.pk for user in users]

    # The credits that satisfied the filters, for the page's users only.
    # An `__in` filter over an M2M (a game tagged with two selected engines)
    # yields one joined row per match → distinct, or the credit shows twice.
    by_user: dict[int, list[Contribution]] = defaultdict(list)
    page_credits = (
        credits.filter(user_id__in=user_ids)
        .select_related("game", "discipline")
        # A person's matching credits are unbounded (a veteran has hundreds) and
        # we keep 3. summary is the one text blob among them — dropping it also
        # keeps it out of the DISTINCT comparison below.
        .defer("game__summary")
        .order_by("-start_date", "-id")  # -id: stable order for same-month credits
        .distinct()
    )
    for credit in page_credits:
        by_user[credit.user_id].append(credit)

    # Career-wide aggregates: ALL active credits, not just the matching ones.
    summaries = profile_summaries(user_ids)

    # Engine repartition over distinct (game, engine) pairs, career-wide: three
    # credits on one Unreal game are one Unreal game, not three.
    engine_counts: dict[int, dict[str, int]] = defaultdict(dict)
    pairs = (
        Contribution.objects.filter(
            status=Contribution.Status.ACTIVE,
            user_id__in=user_ids,
            game__engines__isnull=False,
        )
        .values_list("user_id", "game_id", "game__engines__name")
        .distinct()
    )
    for user_id, _game_id, engine_name in pairs:
        counts = engine_counts[user_id]
        counts[engine_name] = counts.get(engine_name, 0) + 1

    results: list[PersonResult] = []
    for user in users:
        # Indexed, not .get(): `users` came from the active-credit queryset, so
        # every one of them has a summary. A miss is a bug, not a blank card.
        summary = summaries[user.pk]
        matching = by_user.get(user.pk, [])
        results.append(
            PersonResult(
                user=user,
                matching_credits=matching[:MATCHING_CREDITS_SHOWN],
                matching_credits_total=len(matching),
                credits_count=summary.credits_count,
                games_count=summary.games_count,
                first_year=summary.first_year,
                last_year=summary.last_year,
                engine_shares=_percentage_shares(engine_counts.get(user.pk, {})),
            )
        )
    return results


def _percentage_shares(
    counts: dict[str, int], top: int = ENGINE_SHARES_SHOWN
) -> list[tuple[EngineShareName, int]]:
    """Integer percentages, ranked descending, capped at `top` entries + an
    "other" bucket. Largest-remainder rounding, so a non-empty result sums to
    exactly 100 — a displayed repartition that adds up to 99 looks broken.
    Empty `counts` (no engine data) yields [], not a bucket of zeroes; shares
    rounding down to 0 are dropped rather than shown as "0%".

    Engine names come from the DB and are shown as-is; only the "other" bucket
    is ours to translate, so only it is lazy."""
    total = sum(counts.values())
    if not total:
        return []
    exact = {name: count * 100 / total for name, count in counts.items()}
    floors = {name: int(value) for name, value in exact.items()}
    remainder = 100 - sum(floors.values())
    # floors - exact == -fraction, so ascending == biggest fraction first; the
    # name breaks ties so equal shares don't reorder between requests.
    by_fraction = sorted(exact, key=lambda name: (floors[name] - exact[name], name))
    for name in by_fraction[:remainder]:
        floors[name] += 1
    ranked = sorted(floors.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) <= top:
        return [(name, pct) for name, pct in ranked if pct > 0]
    head: list[tuple[EngineShareName, int]] = [(name, pct) for name, pct in ranked[:top] if pct > 0]
    other = sum(pct for _name, pct in ranked[top:])
    if other > 0:
        # Lazy, not gettext(): resolved when the template renders it, under the
        # request's active locale. Raw "other" shipped as literal English in
        # every locale, mid-list among real engine names.
        head.append((_("other"), other))
    return head
