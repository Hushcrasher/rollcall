"""Development settings — used by manage.py and docker compose."""

from .base import *  # noqa: F403
from .base import env

DEBUG = True

# `or`, not just a default: .env.example ships `DJANGO_SECRET_KEY=` and a
# verbatim `cp .env.example .env` makes env() return "" (present-but-empty
# bypasses the default) — which would 500 every page instead of falling back.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="") or "dev-only-insecure-key"

ALLOWED_HOSTS = ["*"]

# Emails printed to the console in dev, with a clean copy-friendly body
# (no quoted-printable line wrapping in links).
EMAIL_BACKEND = "config.email.EmailBackend"

# Plain static serving in dev (no manifest requirement).
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
}
