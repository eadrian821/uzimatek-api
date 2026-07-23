"""
Uzimatek production entrypoint — SHA claims pipeline + EHR API only.
No JARVIS brain, no Telegram, no Qdrant, no Redis.
Requires: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Uzimatek API starting — SHA claims pipeline ready")
    yield
    logger.info("Uzimatek API shutdown complete")


app = FastAPI(
    title="Uzimatek API",
    description="SHA Claims Intelligence Platform — Uzimatek Health",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount only the claim pipeline and EHR routes
from app.sha_claims.router import router as sha_router
from app.ehr.router import router as ehr_router

app.include_router(sha_router, prefix="/api")
app.include_router(ehr_router, prefix="/api")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "uzimatek-api",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
    }


@app.get("/")
async def root():
    return {"service": "Uzimatek API", "status": "online", "docs": "/docs"}


@app.exception_handler(Exception)
async def global_exc(request, exc):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc) if settings.debug else "Internal server error"},
    )
