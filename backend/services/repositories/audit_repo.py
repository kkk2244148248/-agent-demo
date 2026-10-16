"""审批与审计：发送前人工闸门 + 全量操作留痕。

这两块放同一个文件，因为它们共同回答一个合规问题：
「这封邮件是谁写的、谁批的、什么时候发出去的」。
"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.utils import now_str

# 审计日志只保留最近 N 条，避免 runtime.json 无限增长
MAX_AUDIT_RECORDS = 200


class AuditRepo:
    """审计域：任何写操作都应留一条，用于事后追溯与责任划分。"""

    def _audit(self) -> list[dict]:
        return self.data.setdefault("audit", [])

    def add_audit(self, employee: str, action: str, target: str, detail: str = "") -> None:
        with self._lock:
            self._audit().insert(
                0,
                {
                    "id": f"AUD-{uuid.uuid4().hex[:8]}",
                    "time": now_str(),
                    "employee": employee or "未命名",
                    "action": action,
                    "target": target,
                    "detail": detail,
                },
            )
            self.data["audit"] = self.data["audit"][:MAX_AUDIT_RECORDS]
            self._write()

    def list_audit(self, limit: int = 50) -> list[dict]:
        return deepcopy(self._audit()[:limit])


class ApprovalRepo:
    """审批域：AI 起草 → 人工确认 → 才允许发出。

    状态机：
        提交 → pending
        批准 → approved（询盘置 sent，写入 approved_reply）
        驳回 → rejected（询盘退回 pending，可重新起草）

    设计取舍：审批单保存「草稿原文 + 最终发出文本」两份，
    这样复盘时能看出人到底改了什么，而不是只知道「批了」。
    """

    def _approvals(self) -> list[dict]:
        return self.data.setdefault("approvals", [])

    def _inquiries(self) -> list[dict]:
        return self.data.setdefault("inquiries", [])

    def create_approval(
        self, inquiry_id: str, draft: str, employee: str, meta: dict | None = None
    ) -> dict:
        with self._lock:
            item = {
                "id": f"APR-{uuid.uuid4().hex[:8]}",
                "inquiry_id": inquiry_id,
                "draft": draft,
                "status": "pending",
                "created_by": employee,
                "created_at": now_str(),
                "reviewed_by": "",
                "reviewed_at": "",
                "final_text": "",
                "meta": meta or {},
            }
            self._approvals().insert(0, item)
            for inq in self._inquiries():
                if inq.get("id") == inquiry_id:
                    inq["status"] = "awaiting_approval"
            self._write()
            return deepcopy(item)

    def decide_approval(
        self, approval_id: str, approve: bool, employee: str, final_text: str = ""
    ) -> dict | None:
        with self._lock:
            for item in self._approvals():
                if item["id"] != approval_id:
                    continue
                item["status"] = "approved" if approve else "rejected"
                item["reviewed_by"] = employee
                item["reviewed_at"] = now_str()
                item["final_text"] = final_text or item["draft"]
                for inq in self._inquiries():
                    if inq.get("id") != item["inquiry_id"]:
                        continue
                    if approve:
                        inq["status"] = "sent"
                        inq["approved_reply"] = item["final_text"]
                    else:
                        # 驳回后退回待处理，业务员可以改稿重提
                        inq["status"] = "pending"
                self._write()
                return deepcopy(item)
        return None

    def list_approvals(self, status: str | None = "pending") -> list[dict]:
        items = self._approvals()
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)
