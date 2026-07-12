"""Back-office for games/companies. [source] columns are read-only: they are
owned by the seed and overwritten on every weekly refresh — editing them here
would silently be undone (docs/02-ARCHITECTURE.md §2.4)."""

from django.contrib import admin
from django.http import HttpRequest

from .models import (
    Company,
    CompanyAlias,
    Engine,
    Game,
    GameCompany,
    GameEngine,
    GameGenre,
    Genre,
)

GAME_SOURCE_FIELDS = (
    "title",
    "release_date",
    "summary",
    "cover_url",
    "igdb_rating",
    "igdb_aggregated_rating",
    "steam_positive_pct",
    "steam_review_count",
)

COMPANY_SOURCE_FIELDS = ("name", "parent_company", "logo_url")


class GameGenreInline(admin.TabularInline):
    model = GameGenre
    extra = 0


class GameEngineInline(admin.TabularInline):
    model = GameEngine
    extra = 0


class GameCompanyInline(admin.TabularInline):
    model = GameCompany
    extra = 0


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("title", "release_date", "steam_positive_pct", "source", "last_synced_at")
    list_filter = ("source",)
    search_fields = ("title",)
    readonly_fields = ("slug", "last_synced_at", "created_at", "updated_at")
    inlines = [GameGenreInline, GameEngineInline, GameCompanyInline]

    def get_readonly_fields(self, request: HttpRequest, obj: Game | None = None) -> list[str]:
        # Manually-created games are fully editable; seeded ones lock [source].
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.source != Game.Source.MANUAL:
            readonly.extend(GAME_SOURCE_FIELDS)
        return readonly


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "parent_company", "source")
    list_filter = ("source",)
    search_fields = ("name",)
    readonly_fields = ("slug", "claimed_by", "created_at", "updated_at")

    def get_readonly_fields(self, request: HttpRequest, obj: Company | None = None) -> list[str]:
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.source != Company.Source.MANUAL:
            readonly.extend(COMPANY_SOURCE_FIELDS)
        return readonly


@admin.register(CompanyAlias)
class CompanyAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "company")
    search_fields = ("alias", "company__name")
    autocomplete_fields = ("company",)


@admin.register(Engine)
class EngineAdmin(admin.ModelAdmin):
    list_display = ("name", "igdb_id")
    search_fields = ("name",)


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "igdb_id")
    search_fields = ("name",)
