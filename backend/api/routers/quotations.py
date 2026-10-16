"""报价路由：报价 CRUD、从询盘生成、改版、底价特批、丢单复盘。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import approver_user, current_user
from backend.api.schemas import (
    QuotationBody,
    QuotationLostBody,
    QuotationStatusBody,
    QuotationVersionBody,
)
from backend.services.store import get_store

router = APIRouter(tags=["quotations"])


@router.get("/api/quotations")
def quotations(
    inquiry_id: str | None = None,
    status: str | None = None,
    _: dict = Depends(current_user),
) -> list[dict]:
    return get_store().list_quotations(inquiry_id=inquiry_id, status=status)


@router.post("/api/quotations")
def quotation_upsert(body: QuotationBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    payload["lines"] = [x if isinstance(x, dict) else x.model_dump() for x in (body.lines or [])]
    payload["updated_by"] = (payload.get("updated_by") or "").strip() or user["name"]
    item = get_store().upsert_quotation(payload)
    get_store().add_audit(
        user["name"],
        "保存报价",
        item["id"],
        f"v{item.get('version')} {item.get('customer_name','')}",
    )
    return item


@router.post("/api/quotations/from-inquiry/{inquiry_id}")
def quotation_from_inquiry(inquiry_id: str, user: dict = Depends(current_user)) -> dict:
    """从询盘比价结果一键生成草稿报价，省掉手工抄写单价/MOQ/交期。"""
    store = get_store()
    inquiry = store.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "询盘不存在")
    pipe = inquiry.get("pipeline") or {}
    compare = pipe.get("compare") or pipe.get("quote_draft") or {}
    options = compare.get("options") or []
    vendors = (pipe.get("vendor_match") or {}).get("matched_vendors") or []
    top = options[0] if options else (vendors[0] if vendors else {})
    lines = [
        {
            "product": inquiry.get("product_name")
            or (pipe.get("requirement") or {}).get("product_summary")
            or inquiry.get("subject")
            or "",
            "color": inquiry.get("color") or "",
            "material": inquiry.get("material") or "",
            "qty": str(
                inquiry.get("qty") or (pipe.get("requirement") or {}).get("quantity") or ""
            ),
            "unit_price": str(
                top.get("ref_unit_price_foreign") or top.get("ref_unit_price_cny") or ""
            ),
            "moq": str(top.get("moq") or ""),
            "lead_days": str(top.get("lead_time_days") or top.get("lead_days") or ""),
            "notes": top.get("recommend_level") or top.get("fit_reason") or "",
        }
    ]
    item = store.upsert_quotation(
        {
            "inquiry_id": inquiry_id,
            "customer_id": inquiry.get("customer_id") or "",
            "customer_name": inquiry.get("customer_name") or "",
            "vendor_id": top.get("vendor_id") or "",
            "vendor_name": top.get("vendor_name") or "",
            "currency": inquiry.get("currency") or top.get("foreign_currency") or "USD",
            "incoterms": inquiry.get("incoterms") or "FOB",
            "status": "draft",
            "notes": "由比价结果自动生成",
            "lines": lines,
        }
    )
    store.add_audit(user["name"], "从询盘生成报价", item["id"], inquiry_id)
    return item


@router.get("/api/quotations/{quotation_id}/versions")
def quotation_versions(quotation_id: str, _: dict = Depends(current_user)) -> dict:
    """版本时间线：看出每一版改了什么价、为什么没成。"""
    data = get_store().quotation_versions(quotation_id)
    if not data:
        raise HTTPException(404, "报价不存在")
    return data


@router.post("/api/quotations/{quotation_id}/status")
def quotation_status(
    quotation_id: str, body: QuotationStatusBody, user: dict = Depends(current_user)
) -> dict:
    store = get_store()
    existing = store.get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["status"] = body.status
    item = store.upsert_quotation(existing)
    store.add_audit(user["name"], "更新报价状态", quotation_id, body.status)
    return item


@router.post("/api/quotations/{quotation_id}/new-version")
def quotation_new_version(
    quotation_id: str, body: QuotationVersionBody, user: dict = Depends(current_user)
) -> dict:
    """基于当前报价生成下一版（历史自动归档）。"""
    lines = [x if isinstance(x, dict) else x.model_dump() for x in (body.lines or [])]
    item = get_store().new_quotation_version(quotation_id, lines, user["name"], body.note)
    if not item:
        raise HTTPException(404, "报价不存在")
    get_store().add_audit(user["name"], "报价改版", quotation_id, f"升至 v{item.get('version')}")
    return item


@router.post("/api/quotations/{quotation_id}/approve-below-floor")
def quotation_approve_below_floor(quotation_id: str, user: dict = Depends(approver_user)) -> dict:
    """低于底价需老板特批；改价后该标记会自动失效，必须重新审批。"""
    store = get_store()
    existing = store.get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["approve_below_floor"] = True
    existing["updated_by"] = user["name"]
    item = store.upsert_quotation(existing)
    store.add_audit(
        user["name"], "特批低价报价", quotation_id, f"底价 {existing.get('floor_price')}"
    )
    return item


@router.post("/api/quotations/{quotation_id}/lost")
def quotation_lost(
    quotation_id: str, body: QuotationLostBody, user: dict = Depends(current_user)
) -> dict:
    """记录丢单原因，用于后续复盘。"""
    store = get_store()
    existing = store.get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["status"] = "rejected"
    existing["lost_reason"] = body.reason
    item = store.upsert_quotation(existing)
    store.add_audit(user["name"], "记录丢单", quotation_id, body.reason)
    return item


@router.delete("/api/quotations/{quotation_id}")
def quotation_delete(quotation_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_quotation(quotation_id)
    if not ok:
        raise HTTPException(404, "报价不存在")
    get_store().add_audit(user["name"], "删除报价", quotation_id)
    return {"ok": True}
