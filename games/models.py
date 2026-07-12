"""Games, companies and their reference tables — docs/04-DATABASE-SCHEMA.md §3–6.

Rules that shape these models:
- Internal IDs are the pivot; igdb_id / steam_appid / igdb_company_id are
  nullable + unique.
- [source] columns are written ONLY by the seed command (games/management/
  commands/seed_games.py) and are read-only in the app (enforced in admin;
  the seed's write-surface is listed in docs/04-DATABASE-SCHEMA.md §13).
- Cover/logo images are never stored by us — URLs to IGDB/Steam CDNs only.
"""

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


def generate_unique_slug(model, text, pk=None):
    """Platform-generated stable slug: slugified text + numeric suffix on collision."""
    base = slugify(text)[:200] or model._meta.model_name
    slug = base
    suffix = 2
    qs = model.objects.exclude(pk=pk) if pk is not None else model.objects.all()
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


class Genre(models.Model):
    """Reference table populated by the seed from IGDB taxonomies (§4)."""

    igdb_id = models.IntegerField(null=True, blank=True, unique=True)
    name = models.CharField(_("name"), max_length=100, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Engine(models.Model):
    """Reference table populated by the seed from IGDB taxonomies (§4)."""

    igdb_id = models.IntegerField(null=True, blank=True, unique=True)
    name = models.CharField(_("name"), max_length=100, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Company(models.Model):
    """§5 — flat entity + one-level parent + aliases. The company page is an
    aggregation, never an editable wiki."""

    class Source(models.TextChoices):
        SEED = "seed", _("Seed")
        MANUAL = "manual", _("Manual")

    igdb_company_id = models.IntegerField(null=True, blank=True, unique=True)
    name = models.CharField(_("name"), max_length=300)  # [source] when seeded
    slug = models.SlugField(_("slug"), max_length=320, unique=True, blank=True)
    parent_company = models.ForeignKey(  # [source]
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subsidiaries",
    )
    logo_url = models.URLField(_("logo URL"), max_length=500, blank=True, default="")  # [source]
    description = models.TextField(  # future claim-editable showcase field
        _("description"), blank=True, default=""
    )
    claimed_by = models.ForeignKey(  # dormant — future company claim
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="claimed_companies",
    )
    source = models.CharField(
        _("source"), max_length=20, choices=Source.choices, default=Source.SEED
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = _("companies")
        indexes = [
            GinIndex(fields=["name"], name="company_name_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(type(self), self.name, pk=self.pk)
        super().save(*args, **kwargs)


class CompanyAlias(models.Model):
    """Dormant (§5) — alternate names for search ("Square" finds "Square Enix")."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(_("alias"), max_length=300)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = _("company aliases")
        constraints = [
            models.UniqueConstraint(fields=["company", "alias"], name="unique_company_alias"),
        ]
        indexes = [
            GinIndex(fields=["alias"], name="company_alias_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self):
        return f"{self.alias} → {self.company}"


class Game(models.Model):
    """§3 — one record per canonical game. Source of truth: the parquet seed."""

    class Source(models.TextChoices):
        SEED = "seed", _("Seed")
        IGDB_LIVE = "igdb_live", _("IGDB live")
        MANUAL = "manual", _("Manual")

    # External IDs — nullable + unique; the internal id is the pivot.
    igdb_id = models.IntegerField(null=True, blank=True, unique=True)
    steam_appid = models.IntegerField(null=True, blank=True, unique=True)

    # [source] columns — written only by the seed, read-only in the app.
    title = models.CharField(_("title"), max_length=500)
    release_date = models.DateField(_("release date"), null=True, blank=True)
    summary = models.TextField(_("summary"), blank=True, default="")
    cover_url = models.URLField(  # full URL on IGDB/Steam CDN — never stored by us
        _("cover URL"), max_length=500, blank=True, default=""
    )
    igdb_rating = models.DecimalField(
        _("IGDB user rating"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    igdb_aggregated_rating = models.DecimalField(
        _("IGDB critics rating"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    steam_positive_pct = models.DecimalField(
        _("Steam positive %"), max_digits=5, decimal_places=2, null=True, blank=True
    )
    steam_review_count = models.IntegerField(  # noise floor for the rating filter
        _("Steam review count"), null=True, blank=True
    )

    # Platform-owned columns — never touched by the seed.
    slug = models.SlugField(_("slug"), max_length=520, unique=True, blank=True)
    parent_game = models.ForeignKey(  # dormant — remaster/edition/DLC link
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="child_games",
    )
    source = models.CharField(
        _("source"), max_length=20, choices=Source.choices, default=Source.SEED
    )
    last_synced_at = models.DateTimeField(_("last synced at"), null=True, blank=True)

    genres = models.ManyToManyField(Genre, through="GameGenre", related_name="games")
    engines = models.ManyToManyField(Engine, through="GameEngine", related_name="games")
    companies = models.ManyToManyField(Company, through="GameCompany", related_name="games")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            GinIndex(fields=["title"], name="game_title_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["release_date"]),
            models.Index(fields=["steam_positive_pct"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(type(self), self.title, pk=self.pk)
        super().save(*args, **kwargs)


class GameGenre(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "genre"], name="unique_game_genre"),
        ]
        indexes = [
            models.Index(fields=["genre", "game"], name="gamegenre_genre_game"),
        ]

    def __str__(self):
        return f"{self.game} · {self.genre}"


class GameEngine(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    engine = models.ForeignKey(Engine, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["game", "engine"], name="unique_game_engine"),
        ]
        indexes = [
            models.Index(fields=["engine", "game"], name="gameengine_engine_game"),
        ]

    def __str__(self):
        return f"{self.game} · {self.engine}"


class GameCompany(models.Model):
    """§6 — the game's official developer/publisher, from IGDB facts.
    NEVER conflated with the employer on a contribution (user-declared)."""

    class Role(models.TextChoices):
        DEVELOPER = "developer", _("Developer")
        PUBLISHER = "publisher", _("Publisher")
        PORTING = "porting", _("Porting")
        SUPPORTING = "supporting", _("Supporting")

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="company_links")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="game_links")
    role = models.CharField(_("role"), max_length=20, choices=Role.choices)

    class Meta:
        verbose_name_plural = _("game companies")
        constraints = [
            models.UniqueConstraint(
                fields=["game", "company", "role"], name="unique_game_company_role"
            ),
        ]

    def __str__(self):
        return f"{self.game} · {self.company} ({self.role})"
