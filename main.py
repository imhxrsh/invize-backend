import os
import time
import uuid
import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from agents.hello_agent import get_hello_agent
from agents.document_intelligence import router as doc_intel_router
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

    yield

    # Shutdown: cleanup (nothing persistent yet)
    logger.info("Shutting down %s", app.state.service_name)


app = FastAPI(
    title="Invize Backend",
    description="FastAPI backend with Document Intelligence Agent",
    version=os.getenv("SERVICE_VERSION", "0.1.0"),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Register routers
app.include_router(doc_intel_router)


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