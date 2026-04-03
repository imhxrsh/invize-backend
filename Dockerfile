# Invize backend — FastAPI + Prisma (MongoDB) + OCR stack for Dokploy / generic Docker.
# Build:  docker build -t invize-backend .
# Run:    docker run --env-file .env -p 8000:8000 invize-backend
#
# XDG_CACHE_HOME=/app/.cache: prisma-python downloads the query engine here during `prisma generate`.
# Without it, binaries land in /root/.cache and the non-root runtime user gets Permission denied.
#
# Required env at runtime: MONGO_URI, JWT_SECRET (see .env.example).
# MongoDB must be a replica set for Prisma transactions (e.g. ?replicaSet=rs0).
# For persistent uploads, mount a volume on /app/agent_workspace/uploads

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    XDG_CACHE_HOME=/app/.cache

# OCR / PDF + OpenCV runtime libs + C++ toolchain (imagededup builds a Cython extension via g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
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

# 1. Create the cache directory and set permissions BEFORE running generate
RUN mkdir -p /app/.cache && chmod -R 777 /app/.cache

# 2. Explicitly pass the cache home to the generate command
RUN XDG_CACHE_HOME=/app/.cache prisma generate

# 3. Create workspace folders
RUN mkdir -p agent_workspace/uploads agent_workspace/temp

# 4. Ensure appuser owns everything in /app
RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# $$PORT → $PORT at runtime so health follows the same port as uvicorn
HEALTHCHECK --interval=30s --timeout=8s --start-period=120s --retries=3 \
    CMD sh -c "curl -fsS http://127.0.0.1:$${PORT}/health || exit 1"

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers"]
