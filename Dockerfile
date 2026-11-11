# NOTE: This image has NOT been built or run on the development host (no Docker daemon).
# The compose setup is provided as-is; validate with `docker compose build && docker compose up`
# on a host with a working daemon. See docs/limitations.md.
#
# No model weights are baked into this image: inference endpoints (local or hosted) are
# configured at runtime via the registry / env, keeping the image small and generic.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Container-internal binds must be 0.0.0.0; published ports are loopback-bound in
# docker-compose.yml. Data lives on a named volume mounted at /data.
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8310 \
    APP_DATA_DIR=/data \
    APP_FRONTEND_ORIGIN=http://127.0.0.1:8501

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY frontend ./frontend
COPY datasets ./datasets

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 8310 8501

# Default target is the API; the streamlit service in docker-compose.yml overrides
# both command and healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8310/api/health', timeout=4); sys.exit(0 if r.status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8310"]
