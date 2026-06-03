"""API routes — concept lookup, subsystem browsing, comparison views."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/concepts/{concept_id}")
async def get_concept(concept_id: str) -> dict:
    raise NotImplementedError


@router.get("/subsystems")
async def list_subsystems() -> list[dict]:
    raise NotImplementedError
