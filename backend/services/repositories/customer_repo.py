"""客户仓储：客户 CRUD + 公海/私海归属流转 + 超期回收。"""
from __future__ import annotations

import uuid

from backend.services.repositories.constants import DEFAULT_RECYCLE_DAYS
from backend.services.repositories.normalizers import (
    customer_recycle_deadline,
    normalize_customer_ownership,
)
from backend.services.repositories.utils import add_days, now_str, today_str


class CustomerRepo:
    """客户域。

    归属规则（公海私海机制的核心）：
    - 无 owner = 公海，任何人可认领；
    - 有 owner = 私海，超过 recycle_days 未跟进自动回收；
    - 编辑客户时不允许顺带把归属改掉，必须走 claim/release/transfer。
    """

    _BASE_FIELDS = (
        "phone",
        "company_address",
        "website",
        "timezone",
        "payment_terms",
        "preferred_incoterms",
        "preferred_colors",
        "preferred_materials",
        "preferences",
        "memo",
        "notes",
        "email",
        "channel",
        "priority",
        "last_contact",
    )

    @staticmethod
    def _normalize_many(rows: list[dict]) -> None:
        for item in rows:
            for f in CustomerRepo._BASE_FIELDS:
                item.setdefault(f, "")
            tags = item.get("tags")
            if isinstance(tags, str):
                item["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            elif not isinstance(tags, list):
                item["tags"] = []
            normalize_customer_ownership(item)

    def _customers(self) -> list[dict]:
        return self.data.setdefault("customers", [])

    # -- 读 ---------------------------------------------------------------

    def list_customers(self) -> list[dict]:
        self._normalize_many(self._customers())
        for item in self._customers():
            item["recycle_deadline"] = customer_recycle_deadline(item)
        from copy import deepcopy

        return deepcopy(self._customers())

    def get_customer(self, customer_id: str) -> dict | None:
        from copy import deepcopy

        for item in self._customers():
            if item.get("id") == customer_id:
                normalize_customer_ownership(item)
                item["recycle_deadline"] = customer_recycle_deadline(item)
                return deepcopy(item)
        return None

    # -- 写 ---------------------------------------------------------------

    def upsert_customer(self, payload: dict) -> dict:
        from copy import deepcopy

        with self._lock:
            rows = self._customers()
            cid = (payload.get("id") or "").strip() or f"C-{uuid.uuid4().hex[:6]}"
            row = {
                "id": cid,
                "name": (payload.get("name") or "").strip(),
                "country": (payload.get("country") or "").strip(),
                "contact": (payload.get("contact") or "").strip(),
                "email": (payload.get("email") or "").strip(),
                "phone": (payload.get("phone") or "").strip(),
                "channel": (payload.get("channel") or "email").strip(),
                "tags": self._parse_tags(payload.get("tags")),
                "priority": (payload.get("priority") or "medium").strip(),
                "last_contact": (payload.get("last_contact") or "").strip(),
                "preferences": (payload.get("preferences") or "").strip(),
                "memo": (payload.get("memo") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
                "company_address": (payload.get("company_address") or "").strip(),
                "website": (payload.get("website") or "").strip(),
                "timezone": (payload.get("timezone") or "").strip(),
                "payment_terms": (payload.get("payment_terms") or "").strip(),
                "preferred_incoterms": (payload.get("preferred_incoterms") or "").strip(),
                "preferred_colors": (payload.get("preferred_colors") or "").strip(),
                "preferred_materials": (payload.get("preferred_materials") or "").strip(),
                "owner": (payload.get("owner") or "").strip(),
                "stage": (payload.get("stage") or "").strip(),
                "source": (payload.get("source") or "").strip(),
                "blacklist": bool(payload.get("blacklist", False)),
                "updated_at": now_str(),
            }
            if not row["name"]:
                raise ValueError("客户名称不能为空")
            for i, item in enumerate(rows):
                if item.get("id") == cid:
                    # 编辑时不丢归属 / 认领时间 / 回收设置
                    row["owner"] = row["owner"] or str(item.get("owner") or "")
                    row["owner_id"] = (
                        str(item.get("owner_id") or "")
                        if row["owner"] == item.get("owner")
                        else ""
                    )
                    row["claimed_at"] = str(item.get("claimed_at") or "")
                    row["last_follow_at"] = str(item.get("last_follow_at") or "")
                    row["intake_at"] = str(item.get("intake_at") or "")
                    row["recycle_note"] = str(item.get("recycle_note") or "")
                    row["transfer_note"] = str(item.get("transfer_note") or "")
                    row["recycle_days"] = item.get("recycle_days", DEFAULT_RECYCLE_DAYS)
                    if not row["stage"]:
                        row["stage"] = str(item.get("stage") or "新询盘")
                    if not row["source"]:
                        row["source"] = str(item.get("source") or "")
                    self._normalize_many([row])
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            row["recycle_days"] = DEFAULT_RECYCLE_DAYS
            if not row["stage"]:
                row["stage"] = "新询盘"
            self._normalize_many([row])
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def delete_customer(self, customer_id: str) -> bool:
        with self._lock:
            rows = self._customers()
            before = len(rows)
            self.data["customers"] = [r for r in rows if r.get("id") != customer_id]
            if len(self.data["customers"]) == before:
                return False
            self._write()
            return True

    # -- 公海 / 私海 ------------------------------------------------------

    def customer_pool_board(self) -> dict:
        """公海私海看板：私海归属、回收倒计时、公海可认领。"""
        today = today_str()
        customers = self.list_customers()
        private, public = [], []
        for c in customers:
            deadline = customer_recycle_deadline(c)
            days_left = ""
            if deadline:
                try:
                    from datetime import datetime

                    days_left = (
                        datetime.strptime(deadline, "%Y-%m-%d")
                        - datetime.strptime(today, "%Y-%m-%d")
                    ).days
                except Exception:
                    days_left = ""
            enriched = {
                **c,
                "recycle_deadline": deadline,
                "days_left": days_left,
                "need_attention": isinstance(days_left, int) and days_left <= 3,
                "is_public": not c.get("owner"),
            }
            (public if enriched["is_public"] else private).append(enriched)
        private.sort(key=lambda x: (x["days_left"] if isinstance(x["days_left"], int) else 9999))
        public.sort(key=lambda x: x.get("intake_at") or "", reverse=True)
        owners: dict[str, int] = {}
        for c in private:
            key = c.get("owner") or "未分配"
            owners[key] = owners.get(key, 0) + 1
        return {
            "private": private,
            "public": public,
            "summary": {
                "total": len(customers),
                "private_count": len(private),
                "public_count": len(public),
                "need_attention": sum(1 for c in private if c.get("need_attention")),
                "owners": owners,
                "today": today,
            },
        }

    def claim_customer(self, customer_id: str, employee: str, employee_id: str = "") -> dict | None:
        from copy import deepcopy

        with self._lock:
            for item in self._customers():
                if item.get("id") != customer_id:
                    continue
                if item.get("owner"):
                    raise ValueError(f"该客户已归属 {item.get('owner')}，需由经理转移")
                item["owner"] = employee
                item["owner_id"] = employee_id
                item["claimed_at"] = now_str()
                item["last_follow_at"] = today_str()
                normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def release_customer(self, customer_id: str, employee: str = "") -> dict | None:
        """把客户放回公海（业务员主动释放，或经理强制）。"""
        from copy import deepcopy

        with self._lock:
            for item in self._customers():
                if item.get("id") != customer_id:
                    continue
                item["owner"] = ""
                item["owner_id"] = ""
                item["claimed_at"] = ""
                normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def transfer_customer(self, customer_id: str, to_employee: str, by: str = "") -> dict | None:
        """经理把客户转移/分配给某个业务员。"""
        from copy import deepcopy

        if not to_employee:
            raise ValueError("请指定接收的业务员")
        with self._lock:
            for item in self._customers():
                if item.get("id") != customer_id:
                    continue
                prev = item.get("owner") or "公海"
                item["owner"] = to_employee
                item["claimed_at"] = now_str()
                item["last_follow_at"] = today_str()
                item["transfer_note"] = f"{by or '系统'}：{prev} → {to_employee}"
                normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def recycle_customers(self, days: int | None = None, by: str = "") -> dict:
        """扫描私海客户，超过回收天数且无新跟进的自动回公海。

        回收边界：`deadline < today` 才回收，即到期当天仍归属私海，
        次日才被收回（避免「第 30 天当天就被抢走」的争议）。
        """
        today = today_str()
        recycled = []
        with self._lock:
            for item in self._customers():
                if not item.get("owner"):
                    continue
                normalize_customer_ownership(item)
                limit = days if days else int(item.get("recycle_days") or DEFAULT_RECYCLE_DAYS)
                anchor = (
                    item.get("last_follow_at")
                    or item.get("claimed_at")
                    or item.get("intake_at")
                    or ""
                )
                if not anchor:
                    continue
                deadline = add_days(anchor, limit)
                if deadline and deadline < today:
                    recycled.append(
                        {"id": item.get("id"), "name": item.get("name"), "owner": item.get("owner")}
                    )
                    item["owner"] = ""
                    item["owner_id"] = ""
                    item["claimed_at"] = ""
                    item["recycle_note"] = f"{by or '系统'} 于 {today} 自动回收（{limit} 天未跟进）"
                    normalize_customer_ownership(item)
            if recycled:
                self._write()
        return {"recycled": recycled, "count": len(recycled)}

    def touch_customer(self, customer_id: str, employee: str = "") -> dict | None:
        """刷新客户最近跟进时间（防止被回收）。"""
        from copy import deepcopy

        with self._lock:
            for item in self._customers():
                if item.get("id") != customer_id:
                    continue
                item["last_follow_at"] = today_str()
                item["last_contact"] = item.get("last_contact") or item["last_follow_at"]
                normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None
