"""Contact relay & moderation — docs/04-DATABASE-SCHEMA.md §10–11.

The relay email is sent with Reply-To = sender's address; the recipient's
email NEVER appears in any page or response. Both tables keep nullable
SET NULL user FKs: GDPR anonymization while preserving the abuse trail.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ContactRequest(models.Model):
    """§10 — every relay contact. Doubles as the rate-limit backend
    (count rows per sender per 24h) and the abuse audit trail."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contact_requests_sent",
    )
    recipient = models.ForeignKey(  # must have contactable=True at send time
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contact_requests_received",
    )
    subject = models.CharField(_("subject"), max_length=255)
    message = models.TextField(_("message"))

    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["sender", "sent_at"], name="contact_sender_sent_at"),
        ]

    def __str__(self):
        return f"{self.sender or 'anonymized'} → {self.recipient or 'anonymized'}: {self.subject}"


class Report(models.Model):
    """§11 — signal-anything endpoint (host-status / DSA diligence).
    Triage happens in Django admin. No public accusatory content anywhere."""

    class TargetType(models.TextChoices):
        CONTRIBUTION = "contribution", _("Contribution")
        USER = "user", _("User")
        COMPANY = "company", _("Company")
        GAME = "game", _("Game")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        RESOLVED = "resolved", _("Resolved")
        DISMISSED = "dismissed", _("Dismissed")

    reporter = models.ForeignKey(  # logged-in only in POC
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="reports_filed",
    )
    target_type = models.CharField(_("target type"), max_length=20, choices=TargetType.choices)
    target_id = models.BigIntegerField(_("target id"), null=True, blank=True)  # soft reference
    reason = models.TextField(_("reason"))
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.OPEN
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports_handled",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.status}] {self.target_type} #{self.target_id}"
