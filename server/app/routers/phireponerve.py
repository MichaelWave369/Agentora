"""Explicit opt-in, public-only local observer bridge (no dispatch or writes)."""
import os

from fastapi import APIRouter, HTTPException

from app.integrations.phireponerve_client import (
    RepoNerveUnavailable, collect_public_observations,
)

router = APIRouter(tags=["integrations"])


@router.get("/api/integrations/phireponerve/public-observations")
def public_observations():
    if os.environ.get("AGENTORA_REPONERVE_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="RepoNerve adapter disabled")
    try:
        return collect_public_observations()
    except RepoNerveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
