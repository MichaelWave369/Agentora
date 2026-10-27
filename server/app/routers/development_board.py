"""Status-only Development Board R0 API. No tools, agents or repo mutations."""
from typing import Any

from fastapi import APIRouter

from app.services.development_board.contract import demo_board, evaluate_receipt, load_catalog

router = APIRouter(prefix="/api/development-board", tags=["development-board"])


@router.get("/skills")
def skills() -> dict[str, Any]:
    return {"mode": "CATALOG_ONLY", **load_catalog()}


@router.get("/demo")
def demo() -> dict[str, Any]:
    return demo_board()


@router.post("/evaluate")
def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    # Analysis only. Neither a PASS nor an operator approval is authenticated by R0.
    return evaluate_receipt(payload)
