"""审批闸门测试：AI 起草 → 人工确认 → 才允许发出。

这是项目里唯一一道「机器不能自己做主」的关口。
AI 写完的信必须先被人看过，理由很实在：
发错的开发信会直接损伤客户关系，而且发出去了收不回来。
"""
from __future__ import annotations

import pytest


def _inquiry(store, iid="INQ-T1", *, status="processed", draft="Dear sir, ...") -> dict:
    payload = {
        "id": iid,
        "customer_name": "审批测试客户",
        "subject": "询盘测试",
        "body": "Please quote",
        "status": status,
    }
    if draft is not None:
        payload["pipeline"] = {"reply_draft": draft}
    return store.create_inquiry(payload)


class TestApprovalLifecycle:
    def test_create_approval_moves_inquiry_to_awaiting(self, empty_store):
        _inquiry(empty_store, "INQ-A1")
        approval = empty_store.create_approval("INQ-A1", "草稿正文", "李海涛")
        assert approval["status"] == "pending"
        assert approval["created_by"] == "李海涛"
        assert approval["reviewed_by"] == ""
        assert empty_store.get_inquiry("INQ-A1")["status"] == "awaiting_approval"

    def test_approve_marks_sent_and_stores_final_text(self, empty_store):
        _inquiry(empty_store, "INQ-A2")
        ap = empty_store.create_approval("INQ-A2", "原始草稿", "李海涛")
        decided = empty_store.decide_approval(ap["id"], True, "周敏", "改过的最终稿")
        assert decided["status"] == "approved"
        assert decided["reviewed_by"] == "周敏"
        assert decided["final_text"] == "改过的最终稿"

        inq = empty_store.get_inquiry("INQ-A2")
        assert inq["status"] == "sent"
        assert inq["approved_reply"] == "改过的最终稿"

    def test_approve_without_edit_uses_draft(self, empty_store):
        """审批人直接通过不改字时，发出的就是原草稿。"""
        _inquiry(empty_store, "INQ-A3")
        ap = empty_store.create_approval("INQ-A3", "原文照发", "李海涛")
        decided = empty_store.decide_approval(ap["id"], True, "周敏", "")
        assert decided["final_text"] == "原文照发"
        assert empty_store.get_inquiry("INQ-A3")["approved_reply"] == "原文照发"

    def test_reject_returns_inquiry_to_pending(self, empty_store):
        """驳回后退回待处理，业务员可以改稿重提。"""
        _inquiry(empty_store, "INQ-A4")
        ap = empty_store.create_approval("INQ-A4", "草稿", "李海涛")
        decided = empty_store.decide_approval(ap["id"], False, "周敏", "")
        assert decided["status"] == "rejected"
        inq = empty_store.get_inquiry("INQ-A4")
        assert inq["status"] == "pending"
        # 驳回不应把草稿写进已发送字段
        assert not inq.get("approved_reply")

    def test_rejected_can_be_resubmitted(self, empty_store):
        """驳回不是死路：改完还能再提交一次。"""
        _inquiry(empty_store, "INQ-A5")
        ap1 = empty_store.create_approval("INQ-A5", "第一版", "李海涛")
        empty_store.decide_approval(ap1["id"], False, "周敏")
        assert empty_store.get_inquiry("INQ-A5")["status"] == "pending"

        ap2 = empty_store.create_approval("INQ-A5", "第二版", "李海涛")
        assert ap2["status"] == "pending"
        assert empty_store.get_inquiry("INQ-A5")["status"] == "awaiting_approval"
        empty_store.decide_approval(ap2["id"], True, "周敏", "")
        assert empty_store.get_inquiry("INQ-A5")["status"] == "sent"

    def test_decide_unknown_approval_returns_none(self, empty_store):
        assert empty_store.decide_approval("APR-NOPE", True, "周敏") is None

    def test_reviewed_at_stamped(self, empty_store):
        _inquiry(empty_store, "INQ-A6")
        ap = empty_store.create_approval("INQ-A6", "草稿", "李海涛")
        decided = empty_store.decide_approval(ap["id"], True, "周敏")
        assert decided["reviewed_at"] != ""


class TestApprovalQueue:
    def test_list_defaults_to_pending(self, empty_store):
        _inquiry(empty_store, "INQ-Q1")
        _inquiry(empty_store, "INQ-Q2")
        empty_store.create_approval("INQ-Q1", "草稿1", "李海涛")
        ap2 = empty_store.create_approval("INQ-Q2", "草稿2", "李海涛")
        empty_store.decide_approval(ap2["id"], True, "周敏")

        pending = empty_store.list_approvals()
        assert len(pending) == 1
        assert pending[0]["inquiry_id"] == "INQ-Q1"

    def test_list_all_shows_every_status(self, empty_store):
        _inquiry(empty_store, "INQ-Q3")
        _inquiry(empty_store, "INQ-Q4")
        empty_store.create_approval("INQ-Q3", "草稿1", "李海涛")
        ap = empty_store.create_approval("INQ-Q4", "草稿2", "李海涛")
        empty_store.decide_approval(ap["id"], False, "周敏")
        assert len(empty_store.list_approvals(status=None)) == 2

    def test_list_by_explicit_status(self, empty_store):
        _inquiry(empty_store, "INQ-Q5")
        ap = empty_store.create_approval("INQ-Q5", "草稿", "李海涛")
        empty_store.decide_approval(ap["id"], False, "周敏")
        assert len(empty_store.list_approvals(status="rejected")) == 1
        assert empty_store.list_approvals(status="approved") == []

    def test_newest_first(self, empty_store):
        """审批队列要最新在前，经理打开就能看到刚提交的。"""
        _inquiry(empty_store, "INQ-Q6")
        _inquiry(empty_store, "INQ-Q7")
        empty_store.create_approval("INQ-Q6", "早", "李海涛")
        empty_store.create_approval("INQ-Q7", "晚", "李海涛")
        queue = empty_store.list_approvals()
        assert queue[0]["inquiry_id"] == "INQ-Q7"


class TestApprovalMetadata:
    def test_meta_preserved(self, empty_store):
        """记下当时的意图，复盘时能看出这封信原本要干什么。"""
        _inquiry(empty_store, "INQ-M1")
        ap = empty_store.create_approval(
            "INQ-M1", "草稿", "李海涛", meta={"intent": "quotation"}
        )
        assert ap["meta"]["intent"] == "quotation"

    def test_pipeline_draft_is_used_as_source(self, empty_store):
        """提交审批时默认取 pipeline 里的 AI 草稿。"""
        inq = _inquiry(empty_store, "INQ-M2", draft="AI 写的草稿")
        draft = (inq.get("pipeline") or {}).get("reply_draft") or ""
        ap = empty_store.create_approval("INQ-M2", draft, "李海涛")
        assert ap["draft"] == "AI 写的草稿"

    def test_empty_draft_still_allowed_at_repo_level(self, empty_store):
        """仓储层不做非空校验——该由接口层拒绝，这里只记录事实。"""
        ap = empty_store.create_approval("INQ-M3", "", "李海涛")
        assert ap["draft"] == ""
        assert ap["status"] == "pending"


class TestAuditTrail:
    """审批动作必须留痕，否则出了事查不到是谁批的。"""

    def test_audit_records_are_newest_first(self, empty_store):
        empty_store.add_audit("李海涛", "提交发送审批", "APR-1", "INQ-1")
        empty_store.add_audit("周敏", "确认发送", "APR-1", "INQ-1")
        trail = empty_store.list_audit()
        assert trail[0]["employee"] == "周敏"
        assert trail[0]["action"] == "确认发送"
        assert trail[1]["employee"] == "李海涛"

    def test_audit_has_stable_shape(self, empty_store):
        empty_store.add_audit("李海涛", "登录系统", "liht")
        row = empty_store.list_audit()[0]
        for key in ("id", "time", "employee", "action", "target", "detail"):
            assert key in row
        assert row["id"].startswith("AUD-")

    def test_audit_limit_respected(self, empty_store):
        for i in range(10):
            empty_store.add_audit("李海涛", f"动作{i}", f"目标{i}")
        assert len(empty_store.list_audit(limit=3)) == 3

    def test_audit_capacity_capped(self, empty_store):
        """日志要有上限，单机 JSON 存储下尤其重要。"""
        from backend.services.repositories.audit_repo import MAX_AUDIT_RECORDS

        for i in range(MAX_AUDIT_RECORDS + 25):
            empty_store.add_audit("李海涛", f"动作{i}", "目标")
        assert len(empty_store.data["audit"]) == MAX_AUDIT_RECORDS

    def test_blank_employee_gets_placeholder(self, empty_store):
        empty_store.add_audit("", "系统动作", "目标")
        assert empty_store.list_audit()[0]["employee"] == "未命名"


class TestInquiryStateMachine:
    """询盘状态流转：pending → processed → awaiting_approval → sent。"""

    def test_new_inquiry_is_pending(self, empty_store):
        inq = _inquiry(empty_store, "INQ-S1", status="pending")
        assert inq["status"] == "pending"

    def test_full_happy_path(self, empty_store):
        _inquiry(empty_store, "INQ-S2", status="pending")
        empty_store.update_inquiry("INQ-S2", {"status": "processed"})
        assert empty_store.get_inquiry("INQ-S2")["status"] == "processed"

        ap = empty_store.create_approval("INQ-S2", "草稿", "李海涛")
        assert empty_store.get_inquiry("INQ-S2")["status"] == "awaiting_approval"

        empty_store.decide_approval(ap["id"], True, "周敏", "")
        assert empty_store.get_inquiry("INQ-S2")["status"] == "sent"

    def test_patch_cannot_change_id(self, empty_store):
        _inquiry(empty_store, "INQ-S3")
        updated = empty_store.update_inquiry("INQ-S3", {"id": "HACKED", "subject": "新主题"})
        assert updated["id"] == "INQ-S3"
        assert empty_store.get_inquiry("HACKED") is None
        assert updated["subject"] == "新主题"

    def test_update_stamps_time(self, empty_store):
        _inquiry(empty_store, "INQ-S4")
        updated = empty_store.update_inquiry("INQ-S4", {"priority": "high"})
        assert updated["updated_at"] != ""

    def test_filter_by_status(self, empty_store):
        _inquiry(empty_store, "INQ-S5", status="pending")
        _inquiry(empty_store, "INQ-S6", status="processed")
        assert len(empty_store.list_inquiries(status="pending")) == 1
        assert len(empty_store.list_inquiries(status=None)) == 2

    def test_missing_inquiry_returns_none(self, empty_store):
        assert empty_store.get_inquiry("INQ-NOPE") is None
        assert empty_store.update_inquiry("INQ-NOPE", {"status": "sent"}) is None
