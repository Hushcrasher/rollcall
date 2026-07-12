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

# Static files are baked into the image and served by whitenoise.
RUN DJANGO_SECRET_KEY=build-only-not-a-secret python manage.py collectstatic --noinput

EXPOSE 8000

# Migrations run on deploy (PaaS release phase / compose command), not here.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
