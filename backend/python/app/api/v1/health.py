from __future__ import annotations

from fastapi import APIRouter, Request
from app.core.logging import service

from app.models.scheduling import HealthResponse
from scheduler.placement_single_model import MODEL_PATH, OUTPUT_DIR, V35SinglePlacementModel

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    ml_dir = request.app.state.ml_dir
    model_error = None
    try:
        V35SinglePlacementModel.load(OUTPUT_DIR)
        available = True
    except Exception as exc:
        available = False
        model_error = str(exc)
    service.debug(
        "Health check: V3.5 model=%s available=%s reason=%s",
        MODEL_PATH,
        available,
        model_error,
    )
    return HealthResponse(
        status="ok",
        lightgbm_available=available,
        model_path=str(MODEL_PATH) if available else None,
        ml_dir=str(ml_dir),
    )
