# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — build the React SPA into frontend/dist
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build/frontend

# Install deps first (better layer caching), then build.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — Python runtime serving the API + the compiled SPA
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    COOKIE_SECURE=true

WORKDIR /app

# Python dependencies. Copy the project metadata and install the package so
# the pinned deps in pyproject.toml are resolved once, cached by Docker.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

# Alembic migrations + config, and the CLI scripts (used to seed users/demo).
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts

# The fake demo seed (only this one file; the rest of data/ is git-ignored).
# The entrypoint copies it to data/master_data.toml and loads it on an empty DB.
COPY data/master_data.example.toml ./data/master_data.example.toml

# The SPA build from stage 1.
COPY --from=frontend /build/frontend/dist ./frontend/dist

COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Render (and most PaaS) inject the port to bind on via $PORT.
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]