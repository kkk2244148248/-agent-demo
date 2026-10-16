"""订单仓储：订单 CRUD、收款登记、生产节点推进、应收与跟单看板。"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.normalizers import normalize_order
from backend.services.repositories.utils import now_str, today_str, to_float

# 允许通过 /meta 接口改的字段白名单（防止前端顺带改金额）
META_ALLOWED_FIELDS = {
    "delivery_date",
    "deposit_due",
    "etd",
    "status",
    "notes",
    "owner",
    "tracking_no",
}

# 交期风险分档阈值（与前端红绿灯一致）
RISK_RED = 60
RISK_AMBER = 25


class OrderRepo:
    """订单域。

    订单是全链路汇聚点：报价转单 → 定金 → 排产 → 验货 → 报关 → 签收。
    因此这里同时承载三件事：收款计划、生产节点、由两者派生的两块看板。
    """

    def _orders(self) -> list[dict]:
        return self.data.setdefault("orders", [])

    # -- 读 ---------------------------------------------------------------

    def list_orders(self, status: str | None = None) -> list[dict]:
        items = self._orders()
        for item in items:
            normalize_order(item)
        if status:
            items = [o for o in items if o.get("status") == status]
        return deepcopy(items)

    def get_order(self, order_id: str) -> dict | None:
        for item in self._orders():
            if item.get("id") == order_id:
                normalize_order(item)
                return deepcopy(item)
        return None

    # -- 写 ---------------------------------------------------------------

    def upsert_order(self, payload: dict) -> dict:
        with self._lock:
            rows = self._orders()
            oid = (payload.get("id") or "").strip() or f"PO-{uuid.uuid4().hex[:6].upper()}"
            existing = None
            for item in rows:
                if item.get("id") == oid:
                    existing = item
                    break
            row = {
                "id": oid,
                "inquiry_id": (payload.get("inquiry_id") or "").strip(),
                "quotation_id": (payload.get("quotation_id") or "").strip(),
                "customer_id": (payload.get("customer_id") or "").strip(),
                "customer_name": (payload.get("customer_name") or "").strip(),
                "vendor_id": (payload.get("vendor_id") or "").strip(),
                "vendor_name": (payload.get("vendor_name") or "").strip(),
                "product": (payload.get("product") or "").strip(),
                "color": (payload.get("color") or "").strip(),
                "material": (payload.get("material") or "").strip(),
                "qty": str(payload.get("qty") or "").strip(),
                "unit_price": str(payload.get("unit_price") or "").strip(),
                "currency": (payload.get("currency") or "USD").strip(),
                "deposit": (payload.get("deposit") or "").strip(),
                "deposit_due": (payload.get("deposit_due") or "").strip(),
                "delivery_date": (payload.get("delivery_date") or "").strip(),
                "status": (payload.get("status") or "待定金").strip(),
                "etd": (payload.get("etd") or "").strip(),
                "tracking_no": (payload.get("tracking_no") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
                "payments": payload.get("payments") if isinstance(payload.get("payments"), list) else [],
                "milestones": payload.get("milestones") if isinstance(payload.get("milestones"), list) else [],
                "owner": (payload.get("owner") or "").strip(),
                "updated_at": now_str(),
            }
            if not row["product"] and not row["customer_name"]:
                raise ValueError("请填写产品或客户")
            if existing:
                # 局部更新时不能把已有收款/节点/交期擦掉
                if not row["payments"]:
                    row["payments"] = existing.get("payments") or []
                if not row["milestones"]:
                    row["milestones"] = existing.get("milestones") or []
                row["delivery_date"] = row["delivery_date"] or (existing.get("delivery_date") or "")
                row["deposit_due"] = row["deposit_due"] or (existing.get("deposit_due") or "")
                row["owner"] = row["owner"] or (existing.get("owner") or "")
            normalize_order(row)
            for i, item in enumerate(rows):
                if item.get("id") == oid:
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def record_payment(
        self,
        order_id: str,
        payment_id: str,
        amount: float = 0.0,
        method: str = "",
        note: str = "",
        employee: str = "",
    ) -> dict | None:
        """登记一笔收款：更新该期收款状态与订单已收/未收金额。

        副作用：定金到账自动推进「定金到账」节点，避免业务员重复手工点一次。
        """
        with self._lock:
            for i, item in enumerate(self._orders()):
                if item.get("id") != order_id:
                    continue
                normalize_order(item)
                hit = False
                for p in item.get("payments") or []:
                    if not isinstance(p, dict):
                        continue
                    if payment_id and p.get("id") != payment_id:
                        continue
                    # 不指定期次时，默认冲抵第一笔未付
                    if payment_id == "" and p.get("status") == "paid":
                        continue
                    paid = to_float(amount, 0.0) or to_float(p.get("amount"), 0.0)
                    p["paid_amount"] = round(paid, 2)
                    p["status"] = "paid"
                    p["paid_at"] = now_str()
                    p["method"] = method or p.get("method") or ""
                    p["note"] = note or p.get("note") or ""
                    p["recorded_by"] = employee
                    hit = True
                    break
                if not hit:
                    return None
                item["milestone_note"] = ""
                normalize_order(item)
                if item.get("payments") and str(item["payments"][0].get("status")) == "paid":
                    for m in item.get("milestones") or []:
                        if isinstance(m, dict) and m.get("key") == "deposit" and m.get("status") != "done":
                            m["status"] = "done"
                            m["actual_date"] = now_str()[:10]
                            m["owner"] = employee
                    normalize_order(item)
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def advance_milestone(
        self,
        order_id: str,
        key: str,
        employee: str = "",
        actual_date: str = "",
        note: str = "",
        status: str = "done",
    ) -> dict | None:
        """推进生产节点；推进后自动刷新交期风险与订单状态。"""
        with self._lock:
            for i, item in enumerate(self._orders()):
                if item.get("id") != order_id:
                    continue
                normalize_order(item)
                for m in item.get("milestones") or []:
                    if not isinstance(m, dict) or m.get("key") != key:
                        continue
                    m["status"] = status
                    if status == "done":
                        m["actual_date"] = actual_date or now_str()[:10]
                    m["owner"] = employee or m.get("owner") or ""
                    if note:
                        m["note"] = note
                normalize_order(item)
                # 节点推进联动订单状态：越靠后的节点优先级越高
                keys_done = {
                    m.get("key")
                    for m in item.get("milestones") or []
                    if isinstance(m, dict) and m.get("status") == "done"
                }
                if "arrived" in keys_done:
                    item["status"] = "已签收"
                elif "customs" in keys_done:
                    item["status"] = "已出货"
                elif "po" in keys_done or "deposit" in keys_done:
                    item["status"] = "生产中"
                normalize_order(item)
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def update_order_meta(self, order_id: str, patch: dict) -> dict | None:
        """更新订单附加字段（交期、定金到期等），字段受白名单限制。"""
        with self._lock:
            for i, item in enumerate(self._orders()):
                if item.get("id") != order_id:
                    continue
                for k, v in (patch or {}).items():
                    if k in META_ALLOWED_FIELDS:
                        item[k] = str(v or "").strip() if not isinstance(v, (int, float)) else v
                normalize_order(item)
                item["updated_at"] = now_str()
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def delete_order(self, order_id: str) -> bool:
        with self._lock:
            rows = self._orders()
            before = len(rows)
            self.data["orders"] = [r for r in rows if r.get("id") != order_id]
            if len(self.data["orders"]) == before:
                return False
            self._write()
            return True

    # -- 看板 -------------------------------------------------------------

    def collections_board(self) -> dict:
        """应收看板：按订单汇总已收/未收/逾期，并给出催款清单。"""
        today = today_str()
        rows = []
        total_due = 0.0
        total_overdue = 0.0
        for o in self.list_orders():
            if o.get("status") in ("已取消",):
                continue
            due = to_float(o.get("due_amount"), 0.0)
            if due <= 0 and to_float(o.get("total_amount"), 0.0) <= 0:
                continue
            overdue_items = []
            overdue_amt = 0.0
            next_due = ""
            for p in o.get("payments") or []:
                if not isinstance(p, dict) or p.get("status") == "paid":
                    continue
                pd = p.get("due_date") or ""
                if pd and pd < today:
                    overdue_items.append(p)
                    overdue_amt += to_float(p.get("amount"), 0.0) - to_float(p.get("paid_amount"), 0.0)
                if pd and (not next_due or pd < next_due):
                    next_due = pd
            rows.append(
                {
                    "id": o.get("id"),
                    "customer_name": o.get("customer_name"),
                    "product": o.get("product"),
                    "currency": o.get("currency"),
                    "total_amount": o.get("total_amount") or "",
                    "paid_amount": o.get("paid_amount") or "0",
                    "due_amount": o.get("due_amount") or "0",
                    "status": o.get("status"),
                    "owner": o.get("owner") or "",
                    "payments": o.get("payments") or [],
                    "overdue_count": len(overdue_items),
                    "overdue_amount": str(round(overdue_amt, 2)) if overdue_amt else "0",
                    "next_due_date": next_due,
                    "is_overdue": bool(overdue_items),
                    "etd": o.get("etd") or "",
                }
            )
            total_due += due
            total_overdue += overdue_amt
        # 逾期的排最前，其次按最近到期日
        rows.sort(key=lambda r: (not r["is_overdue"], r["next_due_date"] or "9999"))
        return {
            "rows": rows,
            "summary": {
                "order_count": len(rows),
                "total_due": str(round(total_due, 2)),
                "total_overdue": str(round(total_overdue, 2)),
                "overdue_orders": sum(1 for r in rows if r["is_overdue"]),
            },
        }

    def tracking_board(self) -> dict:
        """生产跟单看板：在产订单 + 交期红绿灯。"""
        today = today_str()
        rows = []
        for o in self.list_orders():
            if o.get("status") in ("已签收", "已取消"):
                continue
            risk = to_float(o.get("delay_risk"), 0.0)
            light = "green"
            if risk >= RISK_RED:
                light = "red"
            elif risk >= RISK_AMBER:
                light = "amber"
            rows.append(
                {
                    "id": o.get("id"),
                    "customer_name": o.get("customer_name"),
                    "product": o.get("product"),
                    "qty": o.get("qty"),
                    "vendor_name": o.get("vendor_name"),
                    "status": o.get("status"),
                    "etd": o.get("etd") or "",
                    "delivery_date": o.get("delivery_date") or "",
                    "current_milestone": o.get("current_milestone") or "",
                    "milestone_progress": o.get("milestone_progress") or 0,
                    "milestones": o.get("milestones") or [],
                    "delay_risk": risk,
                    "delayed_nodes": o.get("delayed_nodes") or 0,
                    "light": light,
                }
            )
        light_order = {"red": 0, "amber": 1, "green": 2}
        rows.sort(key=lambda r: light_order.get(r["light"], 3))
        return {
            "rows": rows,
            "summary": {
                "in_production": len(rows),
                "red": sum(1 for r in rows if r["light"] == "red"),
                "amber": sum(1 for r in rows if r["light"] == "amber"),
                "green": sum(1 for r in rows if r["light"] == "green"),
                "today": today,
            },
        }
