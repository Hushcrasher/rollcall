"""Test settings — used by pytest (see [tool.pytest.ini_options] in pyproject.toml)."""

from .base import *  # noqa: F403

DEBUG = False

SECRET_KEY = "test-only-insecure-key"

# Fast hashing: tests create many users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}
