# PYTHIA Monitor — engine image.
# Pinned digest-free but version-explicit; non-root; no build tools in the runtime layer.
FROM python:3.13-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is used by the container HEALTHCHECK only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so code edits do not bust the layer cache.
COPY pyproject.toml ./
RUN pip install \
      "fastapi>=0.115" \
      "uvicorn[standard]>=0.30" \
      "httpx>=0.27" \
      "python-dotenv>=1.0" \
      "pydantic>=2.7"

COPY engine/ ./engine/

# Non-root. /data is the persistent volume (SQLite lands here in Phase 1).
RUN useradd --system --uid 10001 --create-home pythia \
 && mkdir -p /data /app/runs \
 && chown -R pythia:pythia /data /app
USER pythia

ENV PYTHIA_MODE=monitor \
    PYTHIA_DATA_DIR=/data \
    ENGINE_HOST=0.0.0.0 \
    ENGINE_PORT=8088

EXPOSE 8088
VOLUME ["/data"]

# readyz is 503 until the first sensing pass lands, so the container is only
# "healthy" once it has actually seen the world.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8088/readyz || exit 1

STOPSIGNAL SIGTERM
CMD ["python", "-m", "engine.run"]
