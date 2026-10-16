"""Сборка роутеров v1."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import mis

api_router = APIRouter()
api_router.include_router(mis.router)
