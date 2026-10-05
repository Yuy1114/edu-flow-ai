"""Shared Pydantic schemas for the ML API."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    lightgbm_available: bool = False
    model_path: str | None = None
    ml_dir: str
