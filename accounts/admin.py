from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import QuerySet
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .forms import AdminUserChangeForm
from .http import AuthedHttpRequest
from .models import (
    GitHubSnapshot,
    GitHubYearlyContribution,
    ProfileImage,
    RecruiterApplication,
    User,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Not Django's default: the change form exposes `avatar`, and every stored
    # avatar must be a pipeline output whoever posted it (spec §2).
    form = AdminUserChangeForm
    ordering = ("email",)
    list_display = ("email", "display_name", "role", "email_verified_at", "is_staff")
    list_filter = ("role", "is_staff", "profile_public", "open_to_work")
    search_fields = ("email", "display_name")
    readonly_fields = ("slug", "created_at", "updated_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Profile"),
            {
                "fields": (
                    "display_name",
                    "slug",
                    "role",
                    "email_verified_at",
                    "profile_public",
                    "contactable",
                    "open_to_work",
                    "avatar",
                    "bio",
                    "location",
                    "country",
                    "github_login",
                )
            },
        ),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Dates"), {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "display_name", "password1", "password2"),
            },
        ),
    )


@admin.register(RecruiterApplication)
class RecruiterApplicationAdmin(admin.ModelAdmin):
    """Manual recruiter validation, one by one — each approval doubles as a
    user interview. Approving promotes the applicant to `recruiter`."""

    list_display = ("full_name", "company_name", "work_email", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("full_name", "company_name", "work_email")
    readonly_fields = ("user", "reviewed_by", "reviewed_at", "created_at", "updated_at")
    actions = ["approve_selected", "reject_selected"]

    @admin.action(description=_("Approve selected (promotes user to recruiter)"))
    def approve_selected(
        self, request: AuthedHttpRequest, queryset: QuerySet[RecruiterApplication]
    ) -> None:
        for application in queryset:
            application.approve(reviewer=request.user)
        self.message_user(request, _("Approved %(n)d application(s).") % {"n": queryset.count()})

    @admin.action(description=_("Reject selected"))
    def reject_selected(
        self, request: AuthedHttpRequest, queryset: QuerySet[RecruiterApplication]
    ) -> None:
        for application in queryset:
            application.reject(reviewer=request.user)
        self.message_user(request, _("Rejected %(n)d application(s).") % {"n": queryset.count()})


@admin.register(GitHubSnapshot)
class GitHubSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "login", "status", "public_repos", "profile_fetched_at")
    list_filter = ("status",)
    search_fields = ("login", "user__email")
    readonly_fields = ("profile_fetched_at",)


@admin.register(GitHubYearlyContribution)
class GitHubYearlyContributionAdmin(admin.ModelAdmin):
    list_display = ("user", "year", "total_commits", "private_count", "is_final", "fetched_at")
    list_filter = ("is_final", "year")
    search_fields = ("user__email",)
    readonly_fields = ("fetched_at",)


@admin.register(ProfileImage)
class ProfileImageAdmin(admin.ModelAdmin):
    """Thumbnails are listed (spec §4): a reported profile's images have to be
    judgeable from the changelist, without opening each row."""

    list_display = ["thumb", "user", "caption", "created_at"]
    list_select_related = ["user"]
    search_fields = ["user__display_name", "user__email", "caption"]

    @admin.display(description=_("thumbnail"))
    def thumb(self, obj: ProfileImage) -> str:
        # FieldFile at runtime; ty sees the ImageField (house bridge).
        thumbnail: Any = obj.thumbnail
        # Empty alt: the caption is its own column, so the image is decorative
        # here — and a caption is optional anyway.
        return format_html('<img src="{}" width="80" alt="">', thumbnail.url)
