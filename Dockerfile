# DealPilot AI Stage 1 public demo image (spec 014). Hosts: Render free (ephemeral store)
# or Fly.io (persistent volume). Synthetic seed 42 data only, generated at build time.

# ---- frontend build (public demo mode) ----
FROM node:24-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
ENV VITE_DEMO_MODE=public
RUN npm run build

# ---- runtime ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements-dev.lock backend/requirements-dev.lock
RUN pip install -r backend/requirements-dev.lock
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src backend/src
RUN pip install --no-deps -e backend
RUN python -m dealpilot.data.generate --out /app/data/raw
COPY --from=web /app/frontend/dist /app/frontend/dist

# Non-root user (spec 014 P-6); the access store folder is 0700 and owned by it.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /var/lib/dealpilot \
    && chown app:app /var/lib/dealpilot \
    && chmod 700 /var/lib/dealpilot
USER app

ENV DEALPILOT_DEMO_MODE=public \
    DEALPILOT_DATA_DIR=/app/data/raw \
    DEALPILOT_DEMO_STORE=/var/lib/dealpilot/access.sqlite \
    DEALPILOT_DEMO_STATIC_DIR=/app/frontend/dist
EXPOSE 10000
# Render sets PORT (default 10000). One process only (no --workers): the access store and
# the in-process checks assume a single instance.
CMD ["sh", "-c", "exec uvicorn dealpilot.api.main:app --host 0.0.0.0 --port ${PORT:-10000} --no-server-header"]
