"""Personal-data export (GDPR portability) — docs/04-DATABASE-SCHEMA.md §14.

Includes identity, settings, contributions, vouches emitted, contact
requests, and the portfolio. Reports are excluded (per the GDPR data map).

Related rows are fetched through their own models' managers (e.g.
`Contribution.objects.filter(user=…)`) rather than reverse accessors — same
result, and it keeps static typing precise.
"""

from typing import Any

from accounts.models import ProfileImage, User
from contact.models import ContactRequest
from contributions.models import Contribution, Vouch


def _iso(value: Any) -> str | None:
    # Bridge Django's date/datetime field descriptors (opaque to the type
    # checker) to an ISO string.
    return value.isoformat() if value is not None else None


def build_personal_data_export(user: User) -> dict[str, Any]:
    contributions = Contribution.objects.filter(user=user).select_related(
        "game", "company", "discipline"
    )
    return {
        "identity": {
            "email": user.email,
            "public_email": user.public_email,
            "display_name": user.display_name,
            "slug": user.slug,
            "role": user.role,
            "bio": user.bio,
            "location": user.location,
            "country": str(user.country),
            "github_login": user.github_login,
            "created_at": _iso(user.created_at),
            "email_verified_at": _iso(user.email_verified_at),
        },
        "settings": {
            "profile_public": user.profile_public,
            "contactable": user.contactable,
            "open_to_work": user.open_to_work,
        },
        "contributions": [
            {
                "game": c.game.title if c.game else None,
                "company": c.company.name if c.company else None,
                "discipline": c.discipline.name,
                "job_title": c.job_title,
                "start_date": _iso(c.start_date),
                "end_date": _iso(c.end_date),
                "country": c.country.code or None,
                "status": c.status,
            }
            for c in contributions
        ],
        "vouches_emitted": [
            {"contribution_id": v.contribution_id, "created_at": _iso(v.created_at)}
            for v in Vouch.objects.filter(voter=user)
        ],
        "contact_requests_sent": [
            {"subject": r.subject, "sent_at": _iso(r.sent_at)}
            for r in ContactRequest.objects.filter(sender=user)
        ],
        "contact_requests_received": [
            {"subject": r.subject, "sent_at": _iso(r.sent_at)}
            for r in ContactRequest.objects.filter(recipient=user)
        ],
        "portfolio": [
            {
                "caption": image.caption,
                "created_at": _iso(image.created_at),
                "file": image.image.name,
            }
            for image in ProfileImage.objects.filter(user=user)
        ],
    }
