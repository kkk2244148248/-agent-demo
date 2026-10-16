"""订单路由：订单 CRUD、从报价/样品转单、收款登记、生产节点推进。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import current_user
from backend.api.schemas import MilestoneBody, OrderBody, OrderMetaBody, PaymentBody
from backend.services.store import get_store

router = APIRouter(tags=["orders"])


@router.get("/api/orders")
def orders(status: str | None = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_orders(status=status)


@router.post("/api/orders")
def order_upsert(body: OrderBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    if not (payload.get("owner") or "").strip():
        payload["owner"] = user["name"]
    try:
        item = get_store().upsert_order(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存订单", item["id"], item.get("product", ""))
    return item


@router.post("/api/orders/from-quotation/{quotation_id}")
def order_from_quotation(quotation_id: str, user: dict = Depends(current_user)) -> dict:
    """报价转订单：客户接受后一键转单，定金比例默认 30%。"""
    store = get_store()
    qt = store.get_quotation(quotation_id)
    if not qt:
        raise HTTPException(404, "报价不存在")
    line = (qt.get("lines") or [{}])[0]
    item = store.upsert_order(
        {
            "inquiry_id": qt.get("inquiry_id") or "",
            "quotation_id": quotation_id,
            "customer_id": qt.get("customer_id") or "",
            "customer_name": qt.get("customer_name") or "",
            "vendor_id": qt.get("vendor_id") or "",
            "vendor_name": qt.get("vendor_name") or "",
            "product": line.get("product") or "",
            "color": line.get("color") or "",
            "material": line.get("material") or "",
            "qty": line.get("qty") or "",
            "unit_price": line.get("unit_price") or "",
            "currency": qt.get("currency") or "USD",
            "deposit": "30%",
            "status": "待定金",
            "notes": f"由报价 {quotation_id} 生成",
        }
    )
    if qt.get("status") != "accepted":
        qt["status"] = "accepted"
        store.upsert_quotation(qt)
    store.add_audit(user["name"], "从报价生成订单", item["id"], quotation_id)
    return item


@router.post("/api/orders/from-sample/{sample_id}")
def order_from_sample(sample_id: str, user: dict = Depends(current_user)) -> dict:
    """样品确认后直接转大货订单。"""
    store = get_store()
    sample = store.get_sample(sample_id)
    if not sample:
        raise HTTPException(404, "样品不存在")
    item = store.upsert_order(
        {
            "inquiry_id": sample.get("inquiry_id") or "",
            "customer_name": sample.get("customer_name") or "",
            "vendor_id": sample.get("vendor_id") or "",
            "vendor_name": sample.get("vendor_name") or "",
            "product": sample.get("product") or "",
            "color": sample.get("color") or "",
            "material": sample.get("material") or "",
            "qty": sample.get("sample_qty") or "",
            "status": "待定金",
            "notes": f"由样品 {sample_id} 生成",
        }
    )
    store.add_audit(user["name"], "从样品生成订单", item["id"], sample_id)
    return item


@router.post("/api/orders/{order_id}/record-payment")
def order_record_payment(
    order_id: str, body: PaymentBody, user: dict = Depends(current_user)
) -> dict:
    """登记一笔收款（定金/尾款），自动刷新应收与首个节点。"""
    item = get_store().record_payment(
        order_id,
        body.payment_id,
        amount=float(body.amount or 0),
        method=body.method,
        note=body.note,
        employee=user["name"],
    )
    if not item:
        raise HTTPException(404, "订单或收款期不存在")
    get_store().add_audit(user["name"], "登记收款", order_id, f"{body.payment_id} {body.amount}")
    return item


@router.post("/api/orders/{order_id}/milestones/advance")
def order_advance_milestone(
    order_id: str, body: MilestoneBody, user: dict = Depends(current_user)
) -> dict:
    """推进生产节点（定金到账→排产→中期→验货→报关→签收）。"""
    item = get_store().advance_milestone(
        order_id,
        body.key,
        employee=user["name"],
        actual_date=body.actual_date,
        note=body.note,
        status=body.status,
    )
    if not item:
        raise HTTPException(404, "订单或节点不存在")
    get_store().add_audit(user["name"], "推进生产节点", order_id, body.key)
    return item


@router.post("/api/orders/{order_id}/meta")
def order_update_meta(
    order_id: str, body: OrderMetaBody, user: dict = Depends(current_user)
) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    item = get_store().update_order_meta(order_id, patch)
    if not item:
        raise HTTPException(404, "订单不存在")
    get_store().add_audit(user["name"], "更新订单交期", order_id, str(patch))
    return item


@router.delete("/api/orders/{order_id}")
def order_delete(order_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_order(order_id)
    if not ok:
        raise HTTPException(404, "订单不存在")
    get_store().add_audit(user["name"], "删除订单", order_id)
    return {"ok": True}


@router.get("/api/collections")
def collections_board(_: dict = Depends(current_user)) -> dict:
    """收款账期看板：已收 / 未收 / 逾期催款清单。"""
    return get_store().collections_board()


@router.get("/api/tracking")
def tracking_board(_: dict = Depends(current_user)) -> dict:
    """生产跟单看板：在产订单与交期红绿灯。"""
    return get_store().tracking_board()
