"""Contributions — the core of the model — docs/04-DATABASE-SCHEMA.md §7–9.

One contribution = "person X worked on game G, [as an employee of company C],
as [job title] ([discipline]), from A to B".
"""

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Discipline(models.Model):
    """§7 — fixed reference list (~11 rows), seeded by a data migration.
    Future sub-disciplines = nullable parent FK, trivial migration."""

    objects: ClassVar[models.Manager["Discipline"]] = models.Manager()

    name = models.CharField(_("name"), max_length=100, unique=True)
    sort_order = models.IntegerField(_("sort order"))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return str(self.name)


class Contribution(models.Model):
    """§8 — the core table. No unique constraint on (user, game): multiple
    roles/periods per game are a feature. Dates are month/year precision,
    stored as DATE with day=01."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DISPUTED = "disputed", _("Disputed")  # dormant — never shown publicly
        REMOVED = "removed", _("Removed")  # dormant

    objects: ClassVar[models.Manager["Contribution"]] = models.Manager()

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,  # GDPR: contributions die with the account
        related_name="contributions",
    )
    game = models.ForeignKey(
        "games.Game",
        null=True,  # nullable in schema (future company-only contributions),
        on_delete=models.PROTECT,  # required in POC forms
        related_name="contributions",
    )
    company = models.ForeignKey(
        "games.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contributions",
        help_text=_("The person's employer for this work (outsourcing/freelance)."),
    )
    discipline = models.ForeignKey(
        Discipline,
        on_delete=models.PROTECT,
        related_name="contributions",
    )
    job_title = models.CharField(
        _("job title"),
        max_length=150,
        help_text=_("Free text, displayed verbatim."),
    )
    start_date = models.DateField(_("start date"))  # month/year — day forced to 01
    end_date = models.DateField(  # null = "still working on it"
        _("end date"), null=True, blank=True
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,  # dormant — only `active` rows are displayed/searchable
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="contribution_end_after_start",
            ),
            # Both game and company null is forbidden, even post-POC.
            models.CheckConstraint(
                condition=models.Q(game__isnull=False) | models.Q(company__isnull=False),
                name="contribution_game_or_company",
            ),
        ]
        indexes = [
            # Recruiter search — the composite that carries the product promise.
            models.Index(fields=["discipline", "game"], name="contrib_discipline_game"),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.game or self.company} · {self.job_title}"


class Vouch(models.Model):
    """§9 — dormant, ships empty. Peer confirmation of a contribution.
    Positive-only: negative feedback goes through reports, never votes."""

    objects: ClassVar[models.Manager["Vouch"]] = models.Manager()

    contribution = models.ForeignKey(Contribution, on_delete=models.CASCADE, related_name="vouches")
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,  # anonymization on voter's account deletion —
        blank=True,  # preserves the trust graph of third parties
        on_delete=models.SET_NULL,
        related_name="vouches_given",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = _("vouches")
        constraints = [
            models.UniqueConstraint(
                fields=["contribution", "voter"],
                condition=models.Q(voter__isnull=False),
                name="unique_vouch_per_voter",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.voter or 'anonymized'} vouches {self.contribution}"
