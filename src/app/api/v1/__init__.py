"""API version 1.

Versioning is done by URL prefix. When a breaking change is needed, add ``api/v2`` with
its own router and mount both -- routes can be shared or re-implemented per version, and
the module services underneath stay untouched.
"""

from fastapi import APIRouter

from app.modules.pets.router import router as pets_router

api_router = APIRouter()
api_router.include_router(pets_router)

__all__ = ["api_router"]
