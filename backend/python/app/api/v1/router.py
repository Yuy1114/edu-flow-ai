"""V1 API router — aggregates all v1 route modules."""
from fastapi import APIRouter
from app.api.v1 import health, pipeline, simulation

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(pipeline.router)
router.include_router(simulation.router, tags=["simulation"])
