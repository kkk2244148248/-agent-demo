"""厂商路由：供应商名录 CRUD 与 360° 关联。

路由顺序注意：`/api/products` 是历史兼容路径，必须保留，
否则早期前端页面会 404。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import current_user
from backend.api.schemas import VendorBody
from backend.services.store import get_store

router = APIRouter(tags=["vendors"])


@router.get("/api/products")
def products(_: dict = Depends(current_user)) -> list[dict]:
    """兼容旧路由：返回结构化厂商名录。"""
    return get_store().list_vendors()


@router.get("/api/vendors")
def vendors(active_only: bool = False, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_vendors(active_only=active_only)


@router.post("/api/vendors")
def vendor_upsert(body: VendorBody, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().upsert_vendor(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存厂商", item["id"], item.get("name", ""))
    return item


@router.get("/api/vendors/{vendor_id}")
def vendor_detail(vendor_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_vendor(vendor_id)
    if not item:
        raise HTTPException(404, "厂商不存在")
    return item


@router.delete("/api/vendors/{vendor_id}")
def vendor_delete(vendor_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_vendor(vendor_id)
    if not ok:
        raise HTTPException(404, "厂商不存在")
    get_store().add_audit(user["name"], "删除厂商", vendor_id)
    return {"ok": True}


@router.get("/api/vendors/{vendor_id}/related")
def vendor_related(vendor_id: str, _: dict = Depends(current_user)) -> dict:
    """厂商 360°：在这家厂打过的样、报过的价、下过的单。"""
    vend = get_store().get_vendor(vendor_id)
    if not vend:
        raise HTTPException(404, "厂商不存在")
    return get_store().related_for_vendor(vendor_id=vendor_id, vendor_name=vend.get("name", ""))
