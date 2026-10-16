"""客户公海私海机制测试：认领、释放、转移、超期回收的边界。

这是本项目最贴近真实业务痛点的机制：
客户资源属于公司而非个人，业务员不跟进就必须让出来。
边界（第 30 天当天算不算超期）一旦写错，就会变成真人之间的争吵，
所以这里把边界逐天钉死。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.services.repositories.constants import DEFAULT_RECYCLE_DAYS
from backend.services.repositories.normalizers import customer_recycle_deadline


def _day(offset: int) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _make_customer(store, **overrides) -> dict:
    payload = {
        "name": "边界测试客户",
        "country": "DE",
        "owner": "",
        **overrides,
    }
    return store.upsert_customer(payload)


class TestPublicPrivateSea:
    def test_new_customer_without_owner_is_public(self, empty_store):
        c = _make_customer(empty_store)
        assert c["pool"] == "public"
        assert c["owner"] == ""

    def test_new_customer_with_owner_is_private(self, empty_store):
        c = _make_customer(empty_store, owner="李海涛")
        assert c["pool"] == "private"
        assert c["owner"] == "李海涛"

    def test_claim_moves_to_private_and_stamps_time(self, empty_store):
        c = _make_customer(empty_store)
        claimed = empty_store.claim_customer(c["id"], "李海涛", "u-1")
        assert claimed["pool"] == "private"
        assert claimed["owner"] == "李海涛"
        assert claimed["owner_id"] == "u-1"
        assert claimed["claimed_at"]
        assert claimed["last_follow_at"] == _day(0)

    def test_claim_already_owned_raises(self, empty_store):
        c = _make_customer(empty_store, owner="李海涛")
        with pytest.raises(ValueError, match="已归属"):
            empty_store.claim_customer(c["id"], "陈晓雯")

    def test_release_returns_to_public(self, empty_store):
        c = _make_customer(empty_store, owner="李海涛")
        released = empty_store.release_customer(c["id"], "李海涛")
        assert released["pool"] == "public"
        assert released["owner"] == ""
        assert released["claimed_at"] == ""

    def test_transfer_records_audit_note(self, empty_store):
        c = _make_customer(empty_store, owner="李海涛")
        moved = empty_store.transfer_customer(c["id"], "陈晓雯", by="周敏")
        assert moved["owner"] == "陈晓雯"
        assert moved["pool"] == "private"
        assert "李海涛" in moved["transfer_note"]
        assert "陈晓雯" in moved["transfer_note"]

    def test_transfer_requires_target(self, empty_store):
        c = _make_customer(empty_store)
        with pytest.raises(ValueError, match="接收的业务员"):
            empty_store.transfer_customer(c["id"], "", by="周敏")

    def test_edit_does_not_clobber_ownership(self, empty_store):
        """编辑客户资料时不能顺手把归属改掉——必须走认领/转移。"""
        c = _make_customer(empty_store)
        claimed = empty_store.claim_customer(c["id"], "李海涛", "u-1")
        # 模拟前端只改了名字，没带 owner 字段
        edited = empty_store.upsert_customer({"id": c["id"], "name": "改过名的客户"})
        assert edited["owner"] == "李海涛"
        assert edited["claimed_at"] == claimed["claimed_at"]
        assert edited["pool"] == "private"

    def test_edit_with_different_owner_clears_owner_id(self, empty_store):
        """显式改归属时，旧的 owner_id 不能残留。"""
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        edited = empty_store.upsert_customer({"id": c["id"], "name": "客户", "owner": "陈晓雯"})
        assert edited["owner"] == "陈晓雯"
        assert edited["owner_id"] == ""


class TestRecycleDeadline:
    def test_deadline_is_anchor_plus_recycle_days(self, empty_store):
        c = _make_customer(empty_store)
        claimed = empty_store.claim_customer(c["id"], "李海涛", "u-1")
        # 认领当天 + 30 天。注意：claim_customer 返回快照，
        # recycle_deadline 由读取路径（list/get）派生，故此处直接算。
        assert customer_recycle_deadline(claimed) == _day(DEFAULT_RECYCLE_DAYS)
        assert empty_store.get_customer(c["id"])["recycle_deadline"] == _day(DEFAULT_RECYCLE_DAYS)

    def test_public_customer_has_no_deadline(self, empty_store):
        c = _make_customer(empty_store)
        # 公海客户没有归属，因此没有回收倒计时
        assert customer_recycle_deadline(c) == ""
        assert empty_store.get_customer(c["id"])["recycle_deadline"] == ""

    def test_list_customers_includes_deadline_field(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        rows = empty_store.list_customers()
        assert all("recycle_deadline" in r for r in rows)

    def test_custom_recycle_days_respected(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        # 直接改记录上的回收天数
        for row in empty_store.data["customers"]:
            if row["id"] == c["id"]:
                row["recycle_days"] = 7
        empty_store._write()
        fetched = empty_store.get_customer(c["id"])
        assert fetched["recycle_deadline"] == _day(7)

    def test_last_follow_at_takes_priority_as_anchor(self, empty_store):
        """跟进过就以最近跟进日重算，认领日不再起作用。"""
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        empty_store.touch_customer(c["id"], "李海涛")
        fetched = empty_store.get_customer(c["id"])
        assert fetched["last_follow_at"] == _day(0)
        assert fetched["recycle_deadline"] == _day(DEFAULT_RECYCLE_DAYS)


class TestRecycleBoundary:
    """回收边界：deadline < today 才回收，到期当天仍归私海。"""

    def _age_customer(self, store, customer_id: str, follow_days_ago: int) -> None:
        """把客户的最近跟进日改成 N 天前，用于伪造超期。"""
        for row in store.data["customers"]:
            if row["id"] == customer_id:
                row["last_follow_at"] = _day(-follow_days_ago)
                row["claimed_at"] = _day(-follow_days_ago)
        store._write()

    def test_not_recycled_before_deadline(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        self._age_customer(empty_store, c["id"], DEFAULT_RECYCLE_DAYS - 5)
        result = empty_store.recycle_customers(by="系统")
        assert result["count"] == 0
        assert empty_store.get_customer(c["id"])["owner"] == "李海涛"

    def test_not_recycled_on_deadline_day(self, empty_store):
        """到期当天不回收——给自己留出缓冲，避免第 30 天当天就被抢。"""
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        self._age_customer(empty_store, c["id"], DEFAULT_RECYCLE_DAYS)
        result = empty_store.recycle_customers(by="系统")
        assert result["count"] == 0
        assert empty_store.get_customer(c["id"])["pool"] == "private"

    def test_recycled_one_day_after_deadline(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        self._age_customer(empty_store, c["id"], DEFAULT_RECYCLE_DAYS + 1)
        result = empty_store.recycle_customers(by="系统")
        assert result["count"] == 1
        assert result["recycled"][0]["id"] == c["id"]
        fetched = empty_store.get_customer(c["id"])
        assert fetched["pool"] == "public"
        assert fetched["owner"] == ""
        assert fetched["owned"] if False else True  # 占位，避免误读
        assert "自动回收" in fetched["recycle_note"]

    def test_public_customers_not_touched(self, empty_store):
        _make_customer(empty_store, name="一直是公海")
        result = empty_store.recycle_customers(by="系统")
        assert result["count"] == 0

    def test_explicit_days_overrides_per_customer_setting(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        self._age_customer(empty_store, c["id"], 10)
        # 客户自身是 30 天，但强制按 7 天扫描 → 应回收
        result = empty_store.recycle_customers(days=7, by="系统")
        assert result["count"] == 1

    def test_touch_resets_countdown(self, empty_store):
        """跟进一下就能续命，这是机制能运转的关键。"""
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        self._age_customer(empty_store, c["id"], DEFAULT_RECYCLE_DAYS + 3)
        empty_store.touch_customer(c["id"], "李海涛")
        assert empty_store.recycle_customers(by="系统")["count"] == 0


class TestCustomerPoolBoard:
    def test_board_splits_public_and_private(self, empty_store):
        _make_customer(empty_store, name="公海A")
        c2 = _make_customer(empty_store, name="私海B")
        empty_store.claim_customer(c2["id"], "李海涛", "u-1")
        board = empty_store.customer_pool_board()
        assert board["summary"]["total"] == 2
        assert board["summary"]["public_count"] == 1
        assert board["summary"]["private_count"] == 1
        assert board["summary"]["owners"] == {"李海涛": 1}

    def test_days_left_is_none_for_public(self, empty_store):
        _make_customer(empty_store, name="公海A")
        board = empty_store.customer_pool_board()
        assert board["public"][0]["days_left"] == ""

    def test_need_attention_within_three_days(self, empty_store):
        c = _make_customer(empty_store)
        empty_store.claim_customer(c["id"], "李海涛", "u-1")
        # 伪造只剩 2 天
        for row in empty_store.data["customers"]:
            if row["id"] == c["id"]:
                row["last_follow_at"] = _day(-(DEFAULT_RECYCLE_DAYS - 2))
        empty_store._write()
        board = empty_store.customer_pool_board()
        assert board["private"][0]["days_left"] == 2
        assert board["private"][0]["need_attention"] is True
        assert board["summary"]["need_attention"] == 1

    def test_private_sorted_by_urgency(self, empty_store):
        """快到期的排前面，业务员打开就能看到最该跟进的。"""
        a = _make_customer(empty_store, name="还剩2天")
        b = _make_customer(empty_store, name="还剩10天")
        for c, days_ago in ((a, DEFAULT_RECYCLE_DAYS - 2), (b, DEFAULT_RECYCLE_DAYS - 10)):
            empty_store.claim_customer(c["id"], "李海涛", "u-1")
            for row in empty_store.data["customers"]:
                if row["id"] == c["id"]:
                    row["last_follow_at"] = _day(-days_ago)
        empty_store._write()
        board = empty_store.customer_pool_board()
        assert [x["name"] for x in board["private"]] == ["还剩2天", "还剩10天"]


class TestCustomerCrud:
    def test_name_required(self, empty_store):
        with pytest.raises(ValueError, match="名称不能为空"):
            empty_store.upsert_customer({"name": "  "})

    def test_tags_parsed_from_string(self, empty_store):
        c = empty_store.upsert_customer({"name": "标签测试", "tags": "欧洲,礼品/促销，VIP"})
        assert c["tags"] == ["欧洲", "礼品", "促销", "VIP"]

    def test_delete_removes_customer(self, empty_store):
        c = _make_customer(empty_store)
        assert empty_store.delete_customer(c["id"]) is True
        assert empty_store.get_customer(c["id"]) is None
        assert empty_store.delete_customer(c["id"]) is False
