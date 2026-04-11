# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.connectlabs

# System dependencies: postgres client libs for psycopg, curl for healthchecks,
# Node.js + the Claude CLI (the chat backend spawns `claude -p` as a subprocess).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/* \
    && claude --version

# Install uv for fast, reproducible dep installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dep manifests first so Docker layer caching works.
COPY pyproject.toml uv.lock* ./

# Install deps from the lock file only (no source yet, no dev extras).
RUN uv export --frozen --no-dev --no-emit-project 2>/dev/null > /tmp/requirements.txt || \
    uv pip compile pyproject.toml -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

# Copy the rest of the project.
COPY . .

# Install the project itself (fast — deps already installed).
RUN uv pip install --system --no-deps -e .

# Run collectstatic at build time so the image ships with the static
# manifest. Use placeholders for env vars that settings.base would otherwise
# require — the values don't affect collectstatic output.
RUN DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=build-time-placeholder \
    DATABASE_URL=sqlite:///tmp/build.db \
    DJANGO_SETTINGS_MODULE=config.settings.base \
    python manage.py collectstatic --noinput --clear

# Non-root user. Create the Claude CLI home dir so the token loader can
# write the OAuth token to it without permission errors.
RUN useradd -m -u 1000 app \
    && mkdir -p /app/.ace-claude-home \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Production command — uvicorn ASGI server.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
