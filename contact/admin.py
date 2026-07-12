"""Report triage — the Django admin is the POC back-office."""

from django.contrib import admin

from .models import ContactRequest, Report


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    # Abuse audit trail — read-only: rows are created by the relay only.
    list_display = ("sender", "recipient", "subject", "sent_at")
    search_fields = ("subject", "sender__display_name", "recipient__display_name")
    readonly_fields = ("sender", "recipient", "subject", "message", "sent_at")

    def has_add_permission(self, request):
        return False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("target_type", "target_id", "reporter", "status", "created_at")
    list_filter = ("status", "target_type")
    readonly_fields = ("reporter", "target_type", "target_id", "reason", "created_at")

    def has_add_permission(self, request):
        return False
