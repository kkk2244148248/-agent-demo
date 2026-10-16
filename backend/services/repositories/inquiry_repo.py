"""询盘仓储：询盘 CRUD 与状态流转（pending → processed → awaiting_approval → sent）。"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.utils import now_str


class InquiryRepo:
    """询盘域。状态机：

    pending ──(跑 Agent)──> processed ──(提交审批)──> awaiting_approval
       ^                                                     │
       └──────────────(驳回)───────────────  approved(发送) ──> sent
    """

    def _inquiries(self) -> list[dict]:
        return self.data.setdefault("inquiries", [])

    def list_inquiries(self, status: str | None = None) -> list[dict]:
        from backend.services.seed_data import normalize_inquiry

        for item in self._inquiries():
            normalize_inquiry(item)
        items = self._inquiries()
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def get_inquiry(self, inquiry_id: str) -> dict | None:
        from backend.services.seed_data import normalize_inquiry

        for item in self._inquiries():
            if item["id"] == inquiry_id:
                normalize_inquiry(item)
                return deepcopy(item)
        return None

    def create_inquiry(self, payload: dict) -> dict:
        from backend.services.seed_data import normalize_inquiry

        with self._lock:
            iid = (payload.get("id") or "").strip() or f"INQ-{uuid.uuid4().hex[:6].upper()}"
            row = normalize_inquiry(
                {
                    "id": iid,
                    "customer_id": (payload.get("customer_id") or "").strip(),
                    "customer_name": (payload.get("customer_name") or "").strip(),
                    "country": (payload.get("country") or "").strip(),
                    "from_email": (payload.get("from_email") or "").strip(),
                    "subject": (payload.get("subject") or "").strip() or "新建询盘",
                    "body": (payload.get("body") or "").strip(),
                    "received_at": (payload.get("received_at") or "").strip() or now_str(),
                    "status": (payload.get("status") or "pending").strip(),
                    "assignee": (payload.get("assignee") or "").strip(),
                    "pipeline": payload.get("pipeline"),
                    "approved_reply": "",
                    "qty": str(payload.get("qty") or "").strip(),
                    "target_price": str(payload.get("target_price") or "").strip(),
                    "currency": (payload.get("currency") or "USD").strip(),
                    "incoterms": (payload.get("incoterms") or "FOB").strip(),
                    "destination": (payload.get("destination") or "").strip(),
                    "deadline": (payload.get("deadline") or "").strip(),
                    "product_name": (payload.get("product_name") or "").strip(),
                    "color": (payload.get("color") or "").strip(),
                    "material": (payload.get("material") or "").strip(),
                    "size_spec": (payload.get("size_spec") or "").strip(),
                    "priority": (payload.get("priority") or "medium").strip(),
                    "source_channel": (payload.get("source_channel") or "email").strip(),
                    "updated_at": now_str(),
                }
            )
            self._inquiries().insert(0, row)
            self._write()
            return deepcopy(row)

    def update_inquiry(self, inquiry_id: str, patch: dict) -> dict | None:
        from backend.services.seed_data import normalize_inquiry

        with self._lock:
            for item in self._inquiries():
                if item["id"] == inquiry_id:
                    # id 不允许被 patch 覆盖，其余字段按调用方意图合并
                    clean = {k: v for k, v in patch.items() if k != "id"}
                    item.update(clean)
                    item["updated_at"] = now_str()
                    normalize_inquiry(item)
                    self._write()
                    return deepcopy(item)
        return None
