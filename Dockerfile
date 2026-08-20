# Production image — same image runs on any PaaS or a VPS (anti-lock-in,
# docs/02-ARCHITECTURE.md §5). Local dev uses compose.yml with this base.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies first (cached layer), project code after.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

# Static files are baked into the image and served by whitenoise. The two env
# vars are build-only placeholders: prod settings crash at import without them
# (deliberately — see config/settings/prod.py), but collectstatic touches
# neither the secret nor the cache, and the real values arrive at runtime.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret \
    REDIS_URL=redis://collectstatic-placeholder:6379/0 \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Bind to $PORT when the platform sets one (Railway), else 8000. Migrations
# run on deploy via the release command (see railway.json / DEPLOY.md).
CMD ["sh", "-c", "gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2"]
