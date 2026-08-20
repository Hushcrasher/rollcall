"""Test settings — used by pytest (see [tool.pytest.ini_options] in pyproject.toml)."""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403
from .base import MIDDLEWARE

# Uploaded test files (avatars) go to a per-run temp dir, not the repo's
# media/ — tests must not leave cross-run state in the working tree.
MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="rollcall-test-media-"))

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

# Deterministic regardless of a developer's local .env (which may hold real
# IGDB creds). Tests that exercise IGDB set these explicitly.
IGDB_CLIENT_ID = ""
IGDB_CLIENT_SECRET = ""
# GitHub client is always stubbed in tests; keep it unconfigured so nothing
# can hit the network by accident.
GITHUB_TOKEN = ""

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}
