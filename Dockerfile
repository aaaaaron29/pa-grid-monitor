# Ingestion services image: EIA poller + consumer, PJM LMP poller + consumer, and PJM load
# poller + consumer all share this one image, selected at runtime via CMD (see
# docker-compose.yml). linux/arm64 for the Oracle
# Ampere A1 target, built via buildx (Architecture.md Section 7); also builds fine as
# linux/amd64 for local dev.
FROM python:3.12-slim AS base

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY common ./common
COPY ingestion ./ingestion
COPY scripts ./scripts
COPY infra ./infra

RUN pip install --no-cache-dir .

# No PyTorch here, ever (Architecture.md Section 7) — this image only ever needs what
# pyproject.toml's base dependencies list, which is deliberately torch-free.

ENTRYPOINT ["python", "-m"]
CMD ["ingestion.eia_poller"]
