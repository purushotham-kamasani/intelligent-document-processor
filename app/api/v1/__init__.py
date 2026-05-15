"""Aggregate router for v1 endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import batches, documents

api_router = APIRouter()
api_router.include_router(documents.router)
api_router.include_router(batches.router)
