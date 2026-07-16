"""Base settings shared by all environments.

Environment-specific settings live in dev.py / prod.py / test.py.
All secrets and infrastructure endpoints come from environment variables
(see .env.example) — never from code or git history.
"""

from pathlib import Path
from typing import Any

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Read a local .env file if present (dev convenience; absent in prod/PaaS).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default=None)

DEBUG: bool = False

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# --- Applications -----------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "django.contrib.postgres",  # pg_trgm search features
    # Third-party
    "django_htmx",
    "django_countries",
    # Rollcall apps (see docs/02-ARCHITECTURE.md §2.3)
    "accounts",
    "games",
    "contributions",
    "search",
    "contact",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://rollcall:rollcall@localhost:5432/rollcall",
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -------------------------------------------------------------------

# Custom user model: email as login identifier. Decided at project start,
# cannot change later (docs/04-DATABASE-SCHEMA.md §1).
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:settings"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n (English only shipped in POC, but every string goes through i18n) --

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True

TIME_ZONE = "UTC"
USE_TZ = True

# --- Static & media ---------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES: dict[str, dict[str, Any]] = {
    # Media (avatars only in POC) goes to an S3 bucket in prod; local in dev.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- Email ------------------------------------------------------------------

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@rollcall.example")

# --- Seed pipeline (docs/02-ARCHITECTURE.md §3) -----------------------------

# Remote parquet the seed reads (private; a fork plugs its own source here).
PARQUET_SOURCE_URL = env("PARQUET_SOURCE_URL", default="")

# IGDB API (via Twitch OAuth) — live fallback for games missing from the seed.
IGDB_CLIENT_ID = env("IGDB_CLIENT_ID", default="")
IGDB_CLIENT_SECRET = env("IGDB_CLIENT_SECRET", default="")
# GitHub API — public "side projects" block on member profiles. Single
# server-side classic PAT (read:user scope is enough). Never client-side.
GITHUB_TOKEN = env("GITHUB_TOKEN", default="")
# Optional address alerted when a scheduled seed run fails.
SEED_ALERT_EMAIL = env("SEED_ALERT_EMAIL", default="")

# --- Contact relay ----------------------------------------------------------

# Max relay messages one sender may send per rolling 24h (anti-spam, §3.6).
CONTACT_RATE_LIMIT_PER_DAY = env.int("CONTACT_RATE_LIMIT_PER_DAY", default=20)

# --- Rate limiting (anti-scraping on public pages) --------------------------
# Per-IP limits; tune via env. NB: the default cache is per-process — add a
# shared cache (Redis) in prod for limits that hold across workers.
PROFILE_RATELIMIT = env("PROFILE_RATELIMIT", default="120/m")
SEARCH_RATELIMIT = env("SEARCH_RATELIMIT", default="60/m")
