"""客户路由：客户 CRUD、公海私海流转、超期回收、跟进单与 360° 关联。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import approver_user, current_user
from backend.api.schemas import CustomerBody, FollowupBody, RecycleBody, TransferBody
from backend.services.store import get_store

router = APIRouter(tags=["customers"])


# --- 客户 ---------------------------------------------------------------


@router.get("/api/customers")
def customers(_: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_customers()


@router.post("/api/customers")
def customer_upsert(body: CustomerBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    is_new = not (payload.get("id") or "").strip()
    if is_new and not (payload.get("owner") or "").strip():
        # 业务员自建的客户直接进自己的私海，避免刚建完就被别人认领
        payload["owner"] = user["name"]
    try:
        item = get_store().upsert_customer(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "新建客户" if is_new else "保存客户", item["id"], item.get("name", ""))
    return item


@router.get("/api/customers/pool")
def customers_pool(_: dict = Depends(current_user)) -> dict:
    """公海私海看板：私海归属与回收倒计时、公海可认领。"""
    return get_store().customer_pool_board()


@router.post("/api/customers/recycle")
def customers_recycle(body: RecycleBody, user: dict = Depends(current_user)) -> dict:
    """扫描并自动回收超期未跟进的私海客户。"""
    result = get_store().recycle_customers(days=body.days, by=user["name"])
    get_store().add_audit(user["name"], "执行客户回收", f"{result['count']} 个客户回到公海")
    return result


@router.get("/api/customers/{customer_id}")
def customer_detail(customer_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_customer(customer_id)
    if not item:
        raise HTTPException(404, "客户不存在")
    return item


@router.delete("/api/customers/{customer_id}")
def customer_delete(customer_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_customer(customer_id)
    if not ok:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "删除客户", customer_id)
    return {"ok": True}


@router.post("/api/customers/{customer_id}/claim")
def customers_claim(customer_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().claim_customer(customer_id, user["name"], user.get("id", ""))
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "认领客户", item["id"], item.get("name", ""))
    return item


@router.post("/api/customers/{customer_id}/release")
def customers_release(customer_id: str, user: dict = Depends(current_user)) -> dict:
    item = get_store().release_customer(customer_id, user["name"])
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "释放客户回公海", item["id"], item.get("name", ""))
    return item


@router.post("/api/customers/{customer_id}/transfer")
def customers_transfer(
    customer_id: str, body: TransferBody, user: dict = Depends(approver_user)
) -> dict:
    """转移归属属于管理动作，只有经理/老板可做（避免私下抢客户）。"""
    try:
        item = get_store().transfer_customer(customer_id, body.to_employee, user["name"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(
        user["name"], "转移客户", item["id"], f"{item.get('name','')} → {body.to_employee}"
    )
    return item


@router.post("/api/customers/{customer_id}/touch")
def customers_touch(customer_id: str, user: dict = Depends(current_user)) -> dict:
    """刷新最近跟进时间，避免被自动回收。"""
    item = get_store().touch_customer(customer_id, user["name"])
    if not item:
        raise HTTPException(404, "客户不存在")
    return item


@router.get("/api/customers/{customer_id}/related")
def customer_related(customer_id: str, _: dict = Depends(current_user)) -> dict:
    """客户 360°：该客户名下的询盘/样品/报价/订单。"""
    cust = get_store().get_customer(customer_id)
    if not cust:
        raise HTTPException(404, "客户不存在")
    return get_store().related_for_customer(
        customer_id=customer_id, customer_name=cust.get("name", "")
    )


# --- 跟进单 -------------------------------------------------------------


@router.get("/api/followups")
def followups(status: str | None = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_followups(status=status)


@router.post("/api/followups")
def followup_upsert(body: FollowupBody, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().upsert_followup(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存跟进", item["id"], item.get("customer_name", ""))
    return item


@router.delete("/api/followups/{followup_id}")
def followup_delete(followup_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_followup(followup_id)
    if not ok:
        raise HTTPException(404, "跟进不存在")
    get_store().add_audit(user["name"], "删除跟进", followup_id)
    return {"ok": True}


@router.post("/api/followups/{followup_id}/done")
def followup_done(followup_id: str, user: dict = Depends(current_user)) -> dict:
    item = get_store().complete_followup(followup_id, user["name"])
    if not item:
        raise HTTPException(404, "跟进不存在")
    get_store().add_audit(user["name"], "完成跟进", followup_id)
    return item
