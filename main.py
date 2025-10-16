import os
import time
import uuid
import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agents.hello_agent import get_hello_agent
from agents.document_intelligence import router as doc_intel_router
from auth.router import router as auth_router
from profile.router import router as profile_router
from users.router import router as users_router
from db.prisma import prisma
from db.mongo import ensure_ttl_indexes
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()

# Configure logging using environment variable
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("invize-backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler for startup/shutdown.

    - Loads env, initializes Swarms AI availability flags.
    - Cleans up any state on shutdown.
    """
    # Startup: check Swarms availability
    try:
        swarms_module = importlib.import_module("swarms")
        app.state.swarms_ok = True
        app.state.swarms_version = getattr(swarms_module, "__version__", "unknown")
        logger.info("Swarms AI detected (version=%s)", app.state.swarms_version)
    except Exception as e:
        app.state.swarms_ok = False
        app.state.swarms_error = str(e)
        logger.warning("Swarms AI not available: %s", e)

    # Expose basic config values on app.state for health endpoints
    app.state.service_name = "Invize Backend"
    app.state.service_version = os.getenv("SERVICE_VERSION", "0.1.0")
    app.state.env = os.getenv("APP_ENV", "development")

    # Initialize Prisma and ensure DB indexes
    try:
        await prisma.connect()
        await ensure_ttl_indexes()
        app.state.db_ready = True
        logger.info("Prisma connected and TTL indexes ensured")
    except Exception as e:
        app.state.db_ready = False
        logger.exception("Database initialization failed: %s", e)

    yield

    # Shutdown: cleanup (nothing persistent yet)
    try:
        await prisma.disconnect()
        logger.info("Prisma disconnected")
    except Exception:
        pass
    logger.info("Shutting down %s", app.state.service_name)


app = FastAPI(
    title="Invize Backend",
    description="FastAPI backend with Document Intelligence Agent",
    version=os.getenv("SERVICE_VERSION", "0.1.0"),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration for frontend integration
_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "")
allow_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Refresh-Token"],
)

# Register routers
app.include_router(doc_intel_router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(users_router)

# Static mount for uploads (avatars, etc.)
uploads_dir = os.path.join(os.getcwd(), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


# Simple request ID middleware for tracking
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration:.4f}"
    logger.info("%s %s rid=%s duration=%.4fs", request.method, request.url.path, request_id, duration)
    return response


class HelloResponse(BaseModel):
    message: str
    service: str
    version: str
    swarms_ok: bool


@app.get("/", response_model=HelloResponse)
async def root() -> HelloResponse:
    """Hello world endpoint with basic service metadata."""
    return HelloResponse(
        message="Hello, world from invize-backend!",
        service=app.state.service_name,
        version=app.state.service_version,
        swarms_ok=bool(getattr(app.state, "swarms_ok", False)),
    )


@app.get("/health")
async def health():
    """Basic health check."""
    return {
        "status": "healthy",
        "service": app.state.service_name,
        "version": app.state.service_version,
        "env": app.state.env,
    }


@app.get("/health/swarms")
async def health_swarms():
    """Check Swarms AI availability and version."""
    return {
        "swarms_ok": bool(getattr(app.state, "swarms_ok", False)),
        "version": getattr(app.state, "swarms_version", None),
        "error": getattr(app.state, "swarms_error", None),
    }




@app.get("/agent/hello")
async def agent_hello():
    """Invoke the single hello agent to return a Hello World message."""
    if not getattr(app.state, "swarms_ok", False):
        raise HTTPException(status_code=503, detail=f"Swarms AI unavailable: {getattr(app.state, 'swarms_error', 'unknown')}")

    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing GROQ_API_KEY in environment")

    try:
        start = time.time()
        agent = get_hello_agent()
        result = agent.run(task="Say 'Hello World'.")
        duration = time.time() - start
        return {
            "success": True,
            "message": str(result),
            "model": os.getenv("AGENT_MODEL_NAME", "openai/gpt-oss-20b"),
            "swarms_version": getattr(app.state, "swarms_version", "unknown"),
            "execution_time": duration,
        }
    except Exception as e:
        logger.exception("Hello agent failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Hello agent failed: {e}")


def get_app() -> FastAPI:
    """For ASGI servers that need an application factory."""
    return app


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)