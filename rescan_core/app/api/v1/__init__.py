"""Сборка роутеров v1."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import crm, doctor, mis, patient

api_router = APIRouter()
api_router.include_router(mis.router)
api_router.include_router(doctor.router)
api_router.include_router(patient.router)
api_router.include_router(crm.router)
