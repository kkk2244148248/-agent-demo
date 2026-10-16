"""样品路由：打样进度台账。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import current_user
from backend.api.schemas import SampleBody
from backend.services.store import get_store

router = APIRouter(tags=["samples"])


@router.get("/api/samples")
def samples(status: str | None = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_samples(status=status)


@router.post("/api/samples")
def save_sample(body: SampleBody, user: dict = Depends(current_user)) -> dict:
    item = get_store().upsert_sample(body.model_dump())
    get_store().add_audit(user["name"], "更新样品进度", item["id"], item.get("status", ""))
    return item
