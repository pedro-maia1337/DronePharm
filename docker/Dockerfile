# =============================================================================
# Dockerfile — DronePharm v2.0
# Multi-stage build: builder instala dependências, runner executa o servidor
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — builder
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libpq-dev \
        libgeos-dev \
        libproj-dev \
        libgdal-dev \
        gdal-bin \
        libgdal-dev \
        python3-dev \
        pkg-config \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .

# Instala as dependências — numpy/scipy/shapely primeiro para evitar conflitos
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir numpy==1.26.4 && \
    pip install --no-cache-dir scipy==1.13.0 && \
    pip install --no-cache-dir shapely==2.0.4 && \
    pip install --no-cache-dir -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — runner
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runner

LABEL maintainer="DronePharm"
LABEL description="Sistema de roteirização inteligente para entrega de medicamentos via drones"
LABEL version="2.0.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgeos-dev \
        libproj-dev \
        curl \
        wait-for-it \
    && rm -rf /var/lib/apt/lists/*

# Copia site-packages do builder
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

RUN useradd -m -u 1000 -s /bin/bash dronepharm
WORKDIR /app

COPY --chown=dronepharm:dronepharm . .

RUN mkdir -p /app/output && chown dronepharm:dronepharm /app/output

USER dronepharm

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", \
     "wait-for-it ${AZURE_PG_HOST:-db}:${AZURE_PG_PORT:-5432} --timeout=60 --strict -- \
      uvicorn server.app:app \
        --host ${SERVER_HOST:-0.0.0.0} \
        --port ${SERVER_PORT:-8000} \
        --workers 1 \
        --log-level info"]