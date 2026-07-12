"""Email-verification token generator.

Subclasses Django's password-reset token machinery but folds
`email_verified_at` into the hash, so a link stops working the moment the
email is verified (single-use / replay protection).
"""

from typing import Any

from django.contrib.auth.tokens import PasswordResetTokenGenerator

from accounts.models import User


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user: User, timestamp: int) -> str:
        # `email_verified_at` is a datetime field descriptor to the type checker.
        verified_at: Any = user.email_verified_at
        verified = "" if verified_at is None else verified_at.isoformat()
        return f"{user.pk}{user.email}{timestamp}{verified}"


email_verification_token = EmailVerificationTokenGenerator()
