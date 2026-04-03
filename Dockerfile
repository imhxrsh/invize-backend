# Invize backend — FastAPI + Prisma (MongoDB) + OCR stack for Dokploy / generic Docker.
# Build:  docker build -t invize-backend .
# Run:    docker run --env-file .env -p 8000:8000 invize-backend
#
# Required env at runtime: MONGO_URI, JWT_SECRET (see .env.example).
# MongoDB must be a replica set for Prisma transactions (e.g. ?replicaSet=rs0).
# For persistent uploads, mount a volume on /app/agent_workspace/uploads

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# OCR / PDF + minimal libs for OpenCV wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN prisma generate && \
    mkdir -p agent_workspace/uploads agent_workspace/temp

# Non-root (adjust UID if your volume mount requires it)
RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# $$PORT → $PORT at runtime so health follows the same port as uvicorn
HEALTHCHECK --interval=30s --timeout=8s --start-period=120s --retries=3 \
    CMD sh -c "curl -fsS http://127.0.0.1:$${PORT}/health || exit 1"

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers"]
