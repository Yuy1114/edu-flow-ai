"""FastAPI application entry point."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import service, service_console, LOG_DIR

# Load .env
_dotenv_loaded = False
try:
    from dotenv import load_dotenv
    _env_candidates = [
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for _env_path in _env_candidates:
        if _env_path.exists():
            load_dotenv(_env_path, override=False)
            _dotenv_loaded = True
except ImportError:
    pass

from app.api.v1.router import router as v1_router
from app.api.v1.pipeline import initialize_pipeline_worker

ML_DIR = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ml_dir = ML_DIR
    recovered_jobs = initialize_pipeline_worker()
    service.info("ML service started, ml_dir=%s", ML_DIR)
    if recovered_jobs:
        service.warning("Marked %s interrupted pipeline job(s) as failed", recovered_jobs)
    service_console.info("ML service started, ml_dir=%s", ML_DIR)
    yield
    service.info("ML service shutting down")


app = FastAPI(
    title="Edu-Flow-AI ML Service",
    description="V3.5 scheduling pipeline: task patterns + phase templates + deterministic placement.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.time()
    response = await call_next(request)
    elapsed_ms = round((time.time() - started_at) * 1000, 1)
    service.info("%s %s → %s (%sms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


app.include_router(v1_router, prefix="/api/ml")
