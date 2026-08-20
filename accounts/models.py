"""Users & recruiter applications — docs/04-DATABASE-SCHEMA.md §1–2.

Custom user with email as the login identifier, decided at project start
(cannot change after the first migration). The email is NEVER displayed
anywhere on the platform; contact goes through the relay only.
"""

from typing import Any, ClassVar

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext
from django_countries.fields import CountryField

# GitHub's own login rule: 1-39 chars, alnum or single internal hyphens.
# Single source of truth — accounts/github.py's parser reuses this pattern.
GITHUB_LOGIN_RE = r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$"


class UserManager(BaseUserManager):
    """Manager for a user model without a username field."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> "User":
        if not email:
            raise ValueError("An email address is required")
        # Full lowercase, not just normalize_email's domain-lowering: emails
        # are stored case-folded everywhere (see SignupForm.clean_email).
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        MEMBER = "member", _("Member")
        RECRUITER = "recruiter", _("Recruiter")
        ADMIN = "admin", _("Admin")

    username = None  # email is the login identifier
    first_name = None
    last_name = None

    email = models.EmailField(_("email address"), unique=True)
    display_name = models.CharField(
        _("display name"),
        max_length=100,
        help_text=_("Real name or pseudonym — real identity is never required."),
    )
    slug = models.SlugField(_("slug"), max_length=120, unique=True, blank=True)
    role = models.CharField(_("role"), max_length=20, choices=Role.choices, default=Role.MEMBER)
    email_verified_at = models.DateTimeField(
        _("email verified at"),
        null=True,
        blank=True,
        help_text=_("Gate: must be set before the user can create contributions."),
    )
    profile_public = models.BooleanField(
        _("public profile"),
        default=True,
        help_text=_("False makes the profile invisible everywhere (safety valve)."),
    )
    contactable = models.BooleanField(
        _("contactable"),
        default=True,
        help_text=_("Allow contact via the relay. The email itself is never exposed."),
    )
    open_to_work = models.BooleanField(
        _("open to work"),
        default=False,
        help_text=_("Badge + recruiter search filter. Independent from contactable."),
    )
    avatar = models.ImageField(
        _("avatar"),
        upload_to="avatars/",
        max_length=500,
        blank=True,
        default="",
        help_text=_("Stored in the S3 bucket (object key). Deleted on account deletion."),
    )
    bio = models.TextField(_("bio"), blank=True, default="")
    location = models.CharField(_("city / region"), max_length=150, blank=True, default="")
    country = CountryField(
        _("country"),
        blank=True,
        default="",
        help_text=_("Predefined list — powers the people-search country filter."),
    )
    github_login = models.CharField(
        _("GitHub login"),
        max_length=39,
        blank=True,
        default="",
        help_text=_("Declared GitHub handle — not verified (same trust model as a LinkedIn link)."),
        validators=[RegexValidator(GITHUB_LOGIN_RE, _("Enter a valid GitHub username."))],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            # Backstop for the case-folding done in SignupForm / UserManager /
            # the login form: two case-variants of one address can never
            # become two accounts, whatever code path writes the row.
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]
        indexes = [
            # People search (typo-tolerant) — docs/04-DATABASE-SCHEMA.md §1.
            GinIndex(
                fields=["display_name"],
                name="user_display_name_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def __str__(self) -> str:
        return str(self.display_name)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.slug:
            # ty can't see Django's descriptor magic (a str lives in the field attr).
            self.slug = self._generate_unique_slug()  # ty: ignore[invalid-assignment]
        super().save(*args, **kwargs)

    def _generate_unique_slug(self) -> str:
        base = slugify(self.display_name) or "user"
        slug = base
        suffix = 2
        qs = type(self).objects.exclude(pk=self.pk)
        while qs.filter(slug=slug).exists():
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def get_absolute_url(self) -> str:
        return reverse("accounts:profile", kwargs={"slug": self.slug})

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_recruiter(self) -> bool:
        return self.role == self.Role.RECRUITER or bool(self.is_superuser)

    @property
    def location_display(self) -> str:
        """ "City · Country" for the profile and the search cards — omitting
        either part when unset. Guards on `country.name`, not `country`: an
        invalid stored code is truthy but renders empty."""
        separator = pgettext("between city and country", " · ")
        return separator.join(part for part in (self.location, self.country.name) if part)


class RecruiterApplication(models.Model):
    """§2 — "do things that don't scale": manual validation, one by one,
    through Django admin. On approval, set user.role = 'recruiter'."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    objects: ClassVar[models.Manager["RecruiterApplication"]] = models.Manager()

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recruiter_applications")
    full_name = models.CharField(_("full name"), max_length=200)
    company_name = models.CharField(  # free text — may not exist in `companies`
        _("company name"), max_length=200
    )
    work_email = models.EmailField(_("work email"))  # for manual verification
    linkedin_url = models.URLField(_("LinkedIn URL"), blank=True, default="")
    message = models.TextField(_("message"), blank=True, default="")
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_recruiter_applications",
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="one_pending_application_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.full_name} ({self.company_name})"

    def approve(self, reviewer: "User") -> None:
        """Approve and promote the applicant to recruiter (docs §3.6)."""
        self._review(self.Status.APPROVED, reviewer)
        user: Any = self.user  # FK descriptor is opaque to the type checker
        user.role = User.Role.RECRUITER
        user.save(update_fields=["role", "updated_at"])

    def reject(self, reviewer: "User") -> None:
        self._review(self.Status.REJECTED, reviewer)

    def _review(self, status: str, reviewer: "User") -> None:
        obj: Any = self  # model field descriptors are opaque to the type checker
        obj.status = status
        obj.reviewed_by = reviewer
        obj.reviewed_at = timezone.now()
        self.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])


class GitHubSnapshot(models.Model):
    """Profile-level GitHub cache (one per user). 24h TTL via profile_fetched_at."""

    class Status(models.TextChoices):
        NEVER_FETCHED = "never_fetched", _("Never fetched")
        OK = "ok", _("OK")
        NOT_FOUND = "not_found", _("Not found")
        ERROR = "error", _("Error")

    objects: ClassVar[models.Manager["GitHubSnapshot"]] = models.Manager()

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="github_snapshot")
    login = models.CharField(max_length=39, blank=True, default="")
    avatar_url = models.URLField(max_length=500, blank=True, default="")
    public_repos = models.PositiveIntegerField(null=True, blank=True)
    followers = models.PositiveIntegerField(null=True, blank=True)
    account_created_at = models.DateTimeField(null=True, blank=True)
    profile_fetched_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEVER_FETCHED)
    last_error = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"github:{self.login} [{self.status}]"


class GitHubYearlyContribution(models.Model):
    """One row per (user, year). Past years are immutable (is_final=True)."""

    objects: ClassVar[models.Manager["GitHubYearlyContribution"]] = models.Manager()

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="github_yearly_contributions"
    )
    year = models.PositiveIntegerField()
    total_commits = models.PositiveIntegerField(default=0)
    total_contributions = models.PositiveIntegerField(default=0)
    private_count = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField()
    is_final = models.BooleanField(default=False)

    class Meta:
        ordering = ["-year"]
        constraints = [
            models.UniqueConstraint(fields=["user", "year"], name="one_row_per_user_year"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.year}: {self.total_commits} commits"  # ty: ignore[unresolved-attribute]
