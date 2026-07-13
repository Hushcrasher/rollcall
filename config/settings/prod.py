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

# --- Email (Brevo transactional relay) ---------------------------------------
# Send through Brevo's SMTP relay (their infrastructure — not a mail daemon on
# our own server). Falls back to console output if unconfigured, so a fresh
# deploy never crashes on email.
_brevo_key = env("EMAIL_HOST_PASSWORD", default=None)
if _brevo_key:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST", default="smtp-relay.brevo.com")
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = env("EMAIL_HOST_USER")  # Brevo SMTP login
    EMAIL_HOST_PASSWORD = _brevo_key  # Brevo SMTP key
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --- Sentry ------------------------------------------------------------------

_sentry_dsn = env("SENTRY_DSN", default=None)
if _sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_sentry_dsn,
        send_default_pii=False,  # never ship personal data to Sentry
    )
