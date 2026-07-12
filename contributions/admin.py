from django.contrib import admin

from .models import Contribution, Discipline, Vouch


@admin.register(Discipline)
class DisciplineAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order")
    ordering = ("sort_order",)


@admin.register(Contribution)
class ContributionAdmin(admin.ModelAdmin):
    list_display = ("user", "game", "company", "discipline", "job_title", "start_date", "status")
    list_filter = ("status", "discipline")
    search_fields = ("user__display_name", "game__title", "job_title")
    autocomplete_fields = ("user", "game", "company")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Vouch)
class VouchAdmin(admin.ModelAdmin):
    # Dormant table — visible for moderation/debug, rows are app-created only.
    list_display = ("contribution", "voter", "created_at")
    readonly_fields = ("contribution", "voter", "created_at")
