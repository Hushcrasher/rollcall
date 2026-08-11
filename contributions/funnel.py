"""Session state for the declare funnel (spec docs/superpowers/specs/
2026-08-11-deferred-registration-funnel-design.md).

Steps 1–3 run before an account exists, so the draft has nowhere to live but the
session. That is deliberate and short-lived: one tab, minutes apart. From the
moment the account is created the credit is a database row instead, because the
verification mail is routinely opened on a different device.

Values are raw form strings, never cleaned data: Django's default session
serializer is JSON, and `date` objects are not JSON-serialisable. The draft is
re-validated through ContributionForm before it is saved.
"""

from django.contrib.sessions.backends.base import SessionBase

SESSION_KEY = "declare_credit"

# The ContributionForm fields the funnel carries, in Meta order.
CREDIT_FIELDS: tuple[str, ...] = (
    "game",
    "company",
    "discipline",
    "job_title",
    "start_date",
    "end_date",
)


def get_draft(session: SessionBase) -> dict[str, str]:
    draft = session.get(SESSION_KEY)
    return dict(draft) if isinstance(draft, dict) else {}


def set_draft(session: SessionBase, draft: dict[str, str]) -> None:
    session[SESSION_KEY] = draft


def clear_draft(session: SessionBase) -> None:
    session.pop(SESSION_KEY, None)
