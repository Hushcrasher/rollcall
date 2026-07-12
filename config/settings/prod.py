"""Production settings — Docker image on the PaaS (docs/02-ARCHITECTURE.md §5)."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False

SECRET_KEY = env("DJANGO_SECRET_KEY")  # required — crash early if missing

# Security hardening behind the PaaS TLS terminator.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # raise once DNS/TLS is stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --- Media: S3-compatible bucket (avatars only in POC) -----------------------

_s3_configured = env("S3_BUCKET_NAME", default=None)
if _s3_configured:
    STORAGES["default"] = {  # noqa: F405
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("S3_BUCKET_NAME"),
            "endpoint_url": env("S3_ENDPOINT_URL"),
            "access_key": env("S3_ACCESS_KEY_ID"),
            "secret_key": env("S3_SECRET_ACCESS_KEY"),
            "file_overwrite": False,
            "default_acl": "private",
        },
    }

# --- Email (Brevo) -----------------------------------------------------------
# Wired in the accounts phase: transactional API (never raw SMTP from the
# server — docs/03-TECH-STACK.md). EMAIL_API_KEY comes from the environment.

# --- Sentry ------------------------------------------------------------------

_sentry_dsn = env("SENTRY_DSN", default=None)
if _sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_sentry_dsn,
        send_default_pii=False,  # never ship personal data to Sentry
    )
