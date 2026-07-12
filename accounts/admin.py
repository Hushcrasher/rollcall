from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import RecruiterApplication, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
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
    user interview. The approval flow (set user.role='recruiter') lands in
    the recruiter phase; until then, review/approve by editing the status."""

    list_display = ("full_name", "company_name", "work_email", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("full_name", "company_name", "work_email")
    readonly_fields = ("user", "created_at", "updated_at")
