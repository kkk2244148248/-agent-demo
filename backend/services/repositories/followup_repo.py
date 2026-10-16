"""跟进仓储：客户待办跟进单 CRUD 与完成标记。"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.utils import now_str


class FollowupRepo:
    """跟进域。

    「跟进」是私海机制的燃料：客户被回收的唯一依据就是 last_follow_at，
    所以完成跟进时除了标记 status，还要顺手刷新客户的最近跟进时间。
    """

    def _followups(self) -> list[dict]:
        return self.data.setdefault("followups", [])

    def list_followups(self, status: str | None = None) -> list[dict]:
        items = self._followups()
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def upsert_followup(self, payload: dict) -> dict:
        with self._lock:
            rows = self._followups()
            fid = (payload.get("id") or "").strip() or f"FU-{uuid.uuid4().hex[:6]}"
            row = {
                "id": fid,
                "customer_id": (payload.get("customer_id") or "").strip(),
                "customer_name": (payload.get("customer_name") or "").strip(),
                "inquiry_id": (payload.get("inquiry_id") or "").strip(),
                "due_date": (payload.get("due_date") or "").strip(),
                "reason": (payload.get("reason") or "").strip(),
                "suggested_action": (payload.get("suggested_action") or "").strip(),
                "priority": (payload.get("priority") or "medium").strip(),
                "status": (payload.get("status") or "open").strip(),
                "updated_at": now_str(),
            }
            if not row["customer_name"] and not row["reason"]:
                raise ValueError("请填写客户或跟进原因")
            for i, item in enumerate(rows):
                if item.get("id") == fid:
                    # 保留完成信息；若被重新打开则清空
                    row["done_by"] = item.get("done_by", "")
                    row["done_at"] = item.get("done_at", "")
                    if row["status"] != "done":
                        row["done_by"] = ""
                        row["done_at"] = ""
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def delete_followup(self, followup_id: str) -> bool:
        with self._lock:
            rows = self._followups()
            before = len(rows)
            self.data["followups"] = [r for r in rows if r.get("id") != followup_id]
            if len(self.data["followups"]) == before:
                return False
            self._write()
            return True

    def complete_followup(self, followup_id: str, employee: str) -> dict | None:
        with self._lock:
            for item in self._followups():
                if item["id"] == followup_id:
                    item["status"] = "done"
                    item["done_by"] = employee
                    item["done_at"] = now_str()
                    self._write()
                    return deepcopy(item)
        return None
