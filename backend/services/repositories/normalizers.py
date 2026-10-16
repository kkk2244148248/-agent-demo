"""规范化函数：把「外部塞进来的字典」补齐成领域模型要求的样子。

这些都是纯函数（只改传入的 dict，不落盘），业务规则集中在此：

设计要点：规则用「重算」而不是「信任调用方」。
调用方可能传任何脏数据（前端表单、LLM 生成、历史 JSON），
所以每次读/写前都重算一次归属、底价、节点与风险，保证不变量成立。
"""
from __future__ import annotations

from typing import Any

from backend.services.repositories.constants import (
    DEFAULT_RECYCLE_DAYS,
    DEPOSIT_PAID_ORDER_STATUS,
    ORDER_FINAL_STATUS,
    PRODUCTION_MILESTONES,
)
from backend.services.repositories.utils import add_days, days_between, to_float, today_str

_SAMPLE_SPEC_FIELDS = (
    "color",
    "color_code",
    "material",
    "size_spec",
    "finish",
    "logo_process",
    "logo_position",
    "sample_qty",
    "sample_fee",
    "tracking_no",
)

# 对外的公开别名（下划线版保留给历史引用）
SAMPLE_SPEC_FIELDS = _SAMPLE_SPEC_FIELDS


def normalize_sample(item: dict) -> None:
    for key in _SAMPLE_SPEC_FIELDS:
        item.setdefault(key, "")


# ---------------------------------------------------------------------------
# 客户：公海 / 私海与回收倒计时
# ---------------------------------------------------------------------------


def normalize_customer_ownership(item: dict) -> None:
    """补齐归属字段并标记 pool。

    约定：`owner` 为空即公海；有 owner 即私海，并派生 `pool` 字段。
    倒计时锚点优先级：最近跟进 > 认领时间 > 入库时间。
    """
    item.setdefault("owner", "")
    item.setdefault("owner_id", "")
    item.setdefault("claimed_at", "")
    item.setdefault("intake_at", item.get("created_at") or "")
    item.setdefault("last_follow_at", item.get("last_contact") or "")
    item.setdefault("recycle_days", DEFAULT_RECYCLE_DAYS)
    item.setdefault("stage", "新询盘")
    item.setdefault("source", item.get("channel") or "email")
    item.setdefault("blacklist", False)
    item["pool"] = "private" if item.get("owner") else "public"


def customer_recycle_deadline(item: dict) -> str:
    """私海客户按最近跟进日 + 回收天数算出应回收日期；公海返回空串。"""
    if not item.get("owner"):
        return ""
    anchor = (
        item.get("last_follow_at")
        or item.get("claimed_at")
        or item.get("intake_at")
        or ""
    )
    if not anchor:
        return ""
    try:
        days = int(item.get("recycle_days") or DEFAULT_RECYCLE_DAYS)
    except Exception:
        days = DEFAULT_RECYCLE_DAYS
    return add_days(anchor, days)


# ---------------------------------------------------------------------------
# 报价：版本化 + 底价红线
# ---------------------------------------------------------------------------


def recompute_quote_floor(item: dict) -> None:
    """重算「是否低于底价」。

    规则：
    - 只有设置了「报价单级底价」才判定（底价缺失时不误伤）；
    - 任一行单价 > 0 且低于该行底价（未设则回落到单据底价）即命中；
    - 不再低于底价时，自动撤销旧的老板特批，避免特批被复用。
    """
    floor = to_float(item.get("floor_price"), 0.0)
    below = False
    if floor > 0:
        for line in item.get("lines") or []:
            if not isinstance(line, dict):
                continue
            price = to_float(line.get("unit_price"), 0.0)
            line_floor = to_float(line.get("floor_price"), 0.0) or floor
            if price > 0 and price < line_floor:
                below = True
                break
    item["below_floor"] = bool(below)
    if not below:
        item["boss_approved"] = False


def normalize_quotation(item: dict) -> None:
    """补齐报价版本字段并重算底价状态。"""
    item.setdefault("version", 1)
    item.setdefault("versions", [])
    item.setdefault("floor_price", "")
    item.setdefault("cost_price", "")
    item.setdefault("target_price", "")
    item.setdefault("below_floor", False)
    item.setdefault("boss_approved", False)
    item.setdefault("lost_reason", "")
    item.setdefault("sent_at", "")
    item.setdefault("last_action_at", item.get("updated_at") or "")
    for line in item.get("lines") or []:
        if isinstance(line, dict):
            line.setdefault("floor_price", "")
            line.setdefault("cost_price", "")
    recompute_quote_floor(item)


def quote_total(item: dict) -> str:
    """按明细行重算总额；无法计算时保留原 total。"""
    total = 0.0
    has = False
    for line in item.get("lines") or []:
        if not isinstance(line, dict):
            continue
        qty = to_float(line.get("qty"), 0.0)
        price = to_float(line.get("unit_price"), 0.0)
        if qty and price:
            total += qty * price
            has = True
    return str(round(total, 2)) if has else (item.get("total") or "")


# ---------------------------------------------------------------------------
# 订单：收款计划 + 生产节点 + 交期风险
# ---------------------------------------------------------------------------


def normalize_order(item: dict) -> None:
    """补齐收款计划与生产节点，并派生跟单看板要用的一切指标。

    派生字段：total_amount / paid_amount / due_amount /
             current_milestone / milestone_progress / delay_risk / delayed_nodes
    """
    qty = to_float(item.get("qty"), 0.0)
    price = to_float(item.get("unit_price"), 0.0)
    total = (
        round(qty * price, 2)
        if (qty and price)
        else to_float(item.get("total_amount"), 0.0)
    )
    if total:
        item["total_amount"] = str(total)

    # --- 收款计划（定金比例可被订单覆盖，默认 30%） ---
    deposit_raw = str(item.get("deposit") or "").strip().rstrip("%")
    ratio = 0.3
    if deposit_raw:
        try:
            ratio = float(deposit_raw) / 100.0
        except Exception:
            ratio = 0.3
    ratio = min(max(ratio, 0.0), 1.0)

    payments = item.get("payments")
    if not isinstance(payments, list) or not payments:
        payments = []
        for idx, (name, part) in enumerate((("定金", ratio), ("尾款", round(1 - ratio, 4)))):
            amount = round(total * part, 2) if total else 0.0
            deposit_settled = name == "定金" and item.get("status") in DEPOSIT_PAID_ORDER_STATUS
            payments.append(
                {
                    "id": f"PAY-{idx + 1}",
                    "name": name,
                    "ratio": part,
                    "amount": amount,
                    "due_date": item.get("etd") if name == "尾款" else (item.get("deposit_due") or ""),
                    "status": "paid" if deposit_settled else "pending",
                    "paid_amount": amount if deposit_settled else 0.0,
                    "paid_at": "",
                    "method": "",
                    "note": "",
                }
            )
    item["payments"] = payments

    paid = 0.0
    for p in payments:
        if isinstance(p, dict):
            paid += to_float(p.get("paid_amount"), 0.0)
    item["paid_amount"] = str(round(paid, 2))
    item["due_amount"] = str(round(max(total - paid, 0.0), 2)) if total else ""

    # --- 生产节点（按 ETD 倒推计划日） ---
    milestones = item.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        etd = item.get("etd") or ""
        offsets = {"deposit": -30, "po": -25, "midcheck": -15, "finalcheck": -7, "customs": -2, "arrived": 0}
        milestones = []
        for key, name in PRODUCTION_MILESTONES:
            milestones.append(
                {
                    "key": key,
                    "name": name,
                    "planned_date": add_days(etd, offsets[key]) if etd else "",
                    "actual_date": "",
                    "status": "pending",
                    "note": "",
                    "owner": "",
                }
            )
    item["milestones"] = milestones
    done = [m for m in milestones if isinstance(m, dict) and m.get("status") == "done"]
    item["current_milestone"] = (
        done[-1]["name"] if done else (milestones[0]["name"] if milestones else "")
    )
    item["milestone_progress"] = round(len(done) / len(milestones), 3) if milestones else 0.0

    # --- 交期风险（红绿灯） ---
    # 每个逾期未完成节点记 22 分，交期已过额外 +30，封顶 99。
    today = today_str()
    overdue_nodes = [
        m
        for m in milestones
        if isinstance(m, dict)
        and m.get("status") != "done"
        and (m.get("planned_date") or "")
        and m["planned_date"] < today
    ]
    delivery = item.get("delivery_date") or item.get("etd") or ""
    risk = 0.0
    if item.get("status") not in ORDER_FINAL_STATUS:
        risk = min(len(overdue_nodes) * 22.0, 88.0)
        if delivery and delivery < today:
            risk = min(risk + 30.0, 99.0)
    item["delay_risk"] = round(risk, 1)
    item["delayed_nodes"] = len(overdue_nodes)


def recycle_days_left(item: dict) -> int | None:
    """私海客户剩余的回收倒计时天数（可能为负）。"""
    deadline = customer_recycle_deadline(item)
    if not deadline:
        return None
    return days_between(deadline, today_str())
