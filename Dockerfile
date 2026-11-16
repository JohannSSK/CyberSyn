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
    HF_HOME=/opt/cybersyn/model-cache \
    TRANSFORMERS_CACHE=/opt/cybersyn/model-cache \
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
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements.txt

# Bake the classification model used by the context and prompt-injection checks.
RUN python -c "from transformers import pipeline; \
pipeline('zero-shot-classification', model='valhalla/distilbart-mnli-12-1'); \
print('CyberSyn: model cached')"

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="CyberSyn" \
      org.opencontainers.image.description="AI Security Gateway — Shadow AI protection & Data Protection" \
      org.opencontainers.image.source="https://github.com/JohannSSK/CyberSyn"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/cybersyn/model-cache \
    TRANSFORMERS_CACHE=/opt/cybersyn/model-cache \
    TORCH_HOME=/opt/cybersyn/model-cache \
    TOKENIZERS_PARALLELISM=false \
    CYBERSYN_HOST=0.0.0.0 \
    CYBERSYN_PORT=5000 \
    CYBERSYN_DEBUG=0 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/cybersyn/model-cache /opt/cybersyn/model-cache

# Run as a non-root user. /app/src/backend holds the SQLite database and the
# generated Fernet key, so it must be writable by that user before the code is
# copied in (a named volume mounted there inherits the image's ownership).
RUN useradd --create-home --shell /bin/bash cybersyn \
 && mkdir -p /app/src/backend \
 && chown -R cybersyn:cybersyn /app /opt/cybersyn

WORKDIR /app
COPY --chown=cybersyn:cybersyn . /app

USER cybersyn
EXPOSE 5000
VOLUME ["/app/src/backend"]

HEALTHCHECK --interval=30s --timeout=15s --start-period=90s --retries=5 \
  CMD python -c "import os, urllib.request; \
urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('CYBERSYN_PORT', '5000') + '/', timeout=10).read()"

CMD ["python", "src/app.py"]
