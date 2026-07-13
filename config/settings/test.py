"""Test settings — used by pytest (see [tool.pytest.ini_options] in pyproject.toml)."""

from .base import *  # noqa: F403
from .base import MIDDLEWARE

DEBUG = False

# WhiteNoise serves static files from STATIC_ROOT, which isn't collected in
# tests — drop it to keep test output free of "no directory" warnings.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]

SECRET_KEY = "test-only-insecure-key"

# Fast hashing: tests create many users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Rate limiting off by default in tests; the rate-limit test re-enables it.
RATELIMIT_ENABLE = False

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}
