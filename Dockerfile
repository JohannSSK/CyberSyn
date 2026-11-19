# CyberSyn — AI Security Gateway (Netcompany Hackathon Athens 2026)
#
# Two-stage build:
#   1. builder  — compiles/installs dependencies and bakes the zero-shot model
#                 into /opt/cybersyn/model-cache
#   2. runtime  — ships only the virtualenv, the baked model and the app code
#
# The scanners load the model with local_files_only=True, so pre-baking it means
# the container starts and scans correctly even with no internet access.

# ---------------------------------------------------------------------------
# Stage 1 — dependencies + model
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CYBERSYN_MODEL_CACHE=/opt/cybersyn/model-cache \
    TOKENIZERS_PARALLELISM=false

# build-essential stays in this stage only: it lets any dependency without a
# manylinux wheel compile, without inflating the final image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu "$(grep '^torch==' /tmp/requirements.txt)" \
 && pip install -r /tmp/requirements.txt \
 && pip check

# Use the production loader to verify NER and an actual DistilBART forward pass.
COPY includes /app/includes
COPY src/config.py /app/src/config.py
COPY src/MLscripts/model_cache.py /app/src/MLscripts/model_cache.py
RUN python /app/src/MLscripts/model_cache.py --download

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="CyberSyn" \
      org.opencontainers.image.description="AI Security Gateway — Shadow AI protection & Data Protection" \
      org.opencontainers.image.source="https://github.com/JohannSSK/CyberSyn"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CYBERSYN_MODEL_CACHE=/opt/cybersyn/model-cache \
    HF_HUB_OFFLINE=1 \
    TORCH_HOME=/opt/cybersyn/model-cache \
    TOKENIZERS_PARALLELISM=false \
    CYBERSYN_HOST=0.0.0.0 \
    CYBERSYN_PORT=5000 \
    CYBERSYN_SCANNER_FALLBACK=0 \
    CYBERSYN_KEY_FILE=/app/secrets/secret.key \
    CYBERSYN_DEBUG=0 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ell \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash cybersyn \
 && install -d -o cybersyn -g cybersyn -m 700 /app/src/backend /app/secrets

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=cybersyn:cybersyn /opt/cybersyn/model-cache /opt/cybersyn/model-cache

WORKDIR /app
COPY src /app/src
COPY includes /app/includes
COPY assets /app/assets

USER cybersyn
EXPOSE 5000
VOLUME ["/app/src/backend", "/app/secrets"]

HEALTHCHECK --interval=30s --timeout=15s --start-period=90s --retries=5 \
  CMD python -c "import os, urllib.request; \
urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('CYBERSYN_PORT', '5000') + '/', timeout=10).read()"

CMD ["gunicorn", "--config", "src/gunicorn_conf.py", "app:app"]
