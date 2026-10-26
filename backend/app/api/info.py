"""Public capability/feature-flag endpoint.

Tells the frontend which optional features are enabled so it can hide
nav items, routes, etc. Lightweight — no auth required.
"""
from fastapi import APIRouter

from app.core.feature_flags import branding, feature_flag

router = APIRouter(prefix="/api", tags=["info"])


@router.get("/info")
async def get_app_info():
    return {
        "features": {
            "agents": feature_flag("AGENTS_ENABLED"),
            "tesouro_direto": feature_flag("TESOURO_DIRETO_ENABLED"),
        },
        # White label (issue #1045): nulls mean "deployment set nothing",
        # so the frontend falls back to the built-in name and mark.
        "branding": branding(),
    }
