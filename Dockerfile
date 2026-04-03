# Invize backend — FastAPI + Prisma (MongoDB) + OCR.
#
# Build:  docker build -t invize-backend .
# Run:    docker run --env-file .env -p 8000:8000 invize-backend
#
# Prisma: `Path.home()` defaults to /root during build — use PRISMA_HOME_DIR=/app so engines + CLI
# cache live under /app and appuser can read them. System `nodejs` + `npm` from apt satisfy Prisma’s
# `npm install prisma@…` step without embedded nodeenv (fewer failure modes in slim images).
#
# Dokploy / reverse proxy: container listens on 0.0.0.0:$PORT (default 8000). Map that port; 502
# usually means nothing listening, wrong published port, or the process crashed on import/startup.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    PRISMA_HOME_DIR=/app \
    XDG_CACHE_HOME=/app/.cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    nodejs \
    npm \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && node --version \
    && npm --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN prisma generate \
    && mkdir -p agent_workspace/uploads agent_workspace/temp \
    && rm -rf /root/.cache/prisma-python 2>/dev/null || true

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=3 \
    CMD sh -c "curl -fsS http://127.0.0.1:$${PORT}/health || exit 1"

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers --forwarded-allow-ips='*'"]
