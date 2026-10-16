"""订单跟单测试：收款计划、定金自动推进、节点红绿灯、账期与催款分级。

这是「跑单」最耗人的一段：一个业务员同时跟十几张单，
哪张该催款、哪张要炸交期，全靠看板替他记着。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.services.repositories.order_repo import RISK_AMBER, RISK_RED


def _day(offset: int) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _order(store, oid: str, qty="1000", price="6.5", etd=None, deposit="30%", **extra) -> dict:
    return store.upsert_order(
        {
            "id": oid,
            "customer_name": "跟单测试客户",
            "product": "测试保温杯",
            "qty": qty,
            "unit_price": price,
            "currency": "USD",
            "deposit": deposit,
            "etd": etd if etd is not None else _day(60),
            **extra,
        }
    )


class TestPaymentPlan:
    """收款计划按定金比例自动拆两期。"""

    def test_default_thirty_percent_split(self, empty_store):
        o = _order(empty_store, "PO-P1")
        assert o["total_amount"] == "6500.0"
        payments = o["payments"]
        assert len(payments) == 2
        deposit, balance = payments
        assert deposit["name"] == "定金"
        assert deposit["amount"] == pytest.approx(1950.0)
        assert balance["name"] == "尾款"
        assert balance["amount"] == pytest.approx(4550.0)
        assert deposit["ratio"] + balance["ratio"] == pytest.approx(1.0)

    def test_custom_deposit_ratio(self, empty_store):
        o = _order(empty_store, "PO-P2", deposit="50%")
        assert o["payments"][0]["amount"] == pytest.approx(3250.0)
        assert o["payments"][1]["amount"] == pytest.approx(3250.0)

    def test_ratios_sum_to_total(self, empty_store):
        o = _order(empty_store, "PO-P3", deposit="37%")
        total = sum(p["amount"] for p in o["payments"])
        assert total == pytest.approx(6500.0, abs=0.01)

    def test_invalid_deposit_falls_back_to_thirty(self, empty_store):
        o = _order(empty_store, "PO-P4", deposit="abc")
        assert o["payments"][0]["amount"] == pytest.approx(1950.0)

    def test_over_hundred_percent_is_clamped(self, empty_store):
        o = _order(empty_store, "PO-P5", deposit="180%")
        assert o["payments"][0]["amount"] == pytest.approx(6500.0)
        assert o["payments"][1]["amount"] == pytest.approx(0.0)

    def test_balance_due_on_etd(self, empty_store):
        etd = _day(60)
        o = _order(empty_store, "PO-P6", etd=etd)
        assert o["payments"][1]["due_date"] == etd


class TestRecordPayment:
    def test_recording_deposit_updates_amounts(self, empty_store):
        _order(empty_store, "PO-R1")
        o = empty_store.record_payment("PO-R1", "PAY-1", amount=1950, employee="李海涛")
        assert o["paid_amount"] == "1950.0"
        assert o["due_amount"] == "4550.0"
        assert o["payments"][0]["status"] == "paid"
        assert o["payments"][0]["paid_at"] != ""
        assert o["payments"][0]["recorded_by"] == "李海涛"

    def test_deposit_payment_auto_advances_deposit_node(self, empty_store):
        """业务员不该被要求手点两次同一个事实。"""
        _order(empty_store, "PO-R2")
        o = empty_store.record_payment("PO-R2", "PAY-1", amount=1950, employee="李海涛")
        deposit_node = next(m for m in o["milestones"] if m["key"] == "deposit")
        assert deposit_node["status"] == "done"
        assert deposit_node["actual_date"] == _day(0)
        assert o["milestone_progress"] == pytest.approx(round(1 / 6, 3))

    def test_balance_payment_does_not_touch_deposit_node(self, empty_store):
        _order(empty_store, "PO-R3")
        empty_store.record_payment("PO-R3", "PAY-1", amount=1950)
        o = empty_store.record_payment("PO-R3", "PAY-2", amount=4550)
        assert o["paid_amount"] == "6500.0"
        assert o["due_amount"] == "0.0"
        # 只有定金节点被自动推进，其余仍待人工确认
        done_keys = {m["key"] for m in o["milestones"] if m["status"] == "done"}
        assert done_keys == {"deposit"}

    def test_amount_defaults_to_scheduled_amount(self, empty_store):
        """只登记「收到了」不带金额时，按计划金额入账。"""
        _order(empty_store, "PO-R4")
        o = empty_store.record_payment("PO-R4", "PAY-1", amount=0)
        assert o["paid_amount"] == "1950.0"

    def test_unknown_payment_id_returns_none(self, empty_store):
        _order(empty_store, "PO-R5")
        assert empty_store.record_payment("PO-R5", "PAY-999", amount=100) is None

    def test_unknown_order_returns_none(self, empty_store):
        assert empty_store.record_payment("PO-NOPE", "PAY-1", amount=100) is None


class TestMilestoneAdvance:
    def test_advance_sets_done_and_date(self, empty_store):
        _order(empty_store, "PO-M1")
        o = empty_store.advance_milestone("PO-M1", "po", employee="李海涛")
        node = next(m for m in o["milestones"] if m["key"] == "po")
        assert node["status"] == "done"
        assert node["actual_date"] == _day(0)

    def test_status_transitions(self, empty_store):
        """节点推进联动订单状态，越靠后的节点优先级越高。"""
        _order(empty_store, "PO-M2")
        assert empty_store.get_order("PO-M2")["status"] == "待定金"
        assert empty_store.advance_milestone("PO-M2", "po")["status"] == "生产中"
        assert empty_store.advance_milestone("PO-M2", "customs")["status"] == "已出货"
        assert empty_store.advance_milestone("PO-M2", "arrived")["status"] == "已签收"

    def test_progress_increments_by_sixth(self, empty_store):
        _order(empty_store, "PO-M3")
        o = empty_store.advance_milestone("PO-M3", "deposit")
        assert o["milestone_progress"] == pytest.approx(round(1 / 6, 3))
        o = empty_store.advance_milestone("PO-M3", "po")
        assert o["milestone_progress"] == pytest.approx(round(2 / 6, 3))

    def test_current_milestone_is_last_done(self, empty_store):
        _order(empty_store, "PO-M4")
        empty_store.advance_milestone("PO-M4", "deposit")
        o = empty_store.advance_milestone("PO-M4", "po")
        assert o["current_milestone"] == "排产下单"

    def test_out_of_order_advance_respects_latest_node(self, empty_store):
        """跳过中间节点直接报关，状态仍应是「已出货」。"""
        _order(empty_store, "PO-M5")
        o = empty_store.advance_milestone("PO-M5", "customs")
        assert o["status"] == "已出货"

    def test_can_revert_node_status(self, empty_store):
        _order(empty_store, "PO-M6")
        empty_store.advance_milestone("PO-M6", "po")
        o = empty_store.advance_milestone("PO-M6", "po", status="pending")
        node = next(m for m in o["milestones"] if m["key"] == "po")
        assert node["status"] == "pending"

    def test_unknown_key_returns_order_unchanged(self, empty_store):
        _order(empty_store, "PO-M7")
        o = empty_store.advance_milestone("PO-M7", "not_a_node")
        assert all(m["status"] == "pending" for m in o["milestones"])

    def test_unknown_order_returns_none(self, empty_store):
        assert empty_store.advance_milestone("PO-NOPE", "po") is None


class TestDelayRisk:
    """交期风险 = 逾期节点数 × 22，交期已过再 +30，封顶 99。"""

    def test_no_overdue_no_risk(self, empty_store):
        o = _order(empty_store, "PO-D1", etd=_day(60))
        assert o["delay_risk"] == 0.0
        assert o["delayed_nodes"] == 0

    def test_overdue_planned_node_raises_risk(self, empty_store):
        # ETD 已过 → 各节点计划日大多也在过去
        o = _order(empty_store, "PO-D2", etd=_day(-1))
        assert o["delayed_nodes"] > 0
        assert o["delay_risk"] > 0

    def test_risk_capped_at_99(self, empty_store):
        o = _order(empty_store, "PO-D3", etd=_day(-120))
        assert o["delay_risk"] <= 99.0

    def test_finished_order_has_no_risk(self, empty_store):
        """已签收的单不该继续报红，否则看板永远清理不干净。"""
        _order(empty_store, "PO-D4", etd=_day(-30))
        for key in ("deposit", "po", "midcheck", "finalcheck", "customs", "arrived"):
            empty_store.advance_milestone("PO-D4", key)
        o = empty_store.get_order("PO-D4")
        assert o["status"] == "已签收"
        assert o["delay_risk"] == 0.0

    def test_cancelled_order_has_no_risk(self, empty_store):
        _order(empty_store, "PO-D5", etd=_day(-30), status="已取消")
        o = empty_store.upsert_order({**empty_store.get_order("PO-D5"), "status": "已取消"})
        assert o["delay_risk"] == 0.0


class TestTrackingBoard:
    def test_light_thresholds(self, empty_store):
        _order(empty_store, "PO-T1", etd=_day(90))       # 无风险 → green
        _order(empty_store, "PO-T2", etd=_day(-1))       # 有逾期 → 至少 amber
        _order(empty_store, "PO-T3", etd=_day(-150))     # 严重 → red
        board = empty_store.tracking_board()
        by_id = {r["id"]: r for r in board["rows"]}
        assert by_id["PO-T1"]["light"] == "green"
        assert by_id["PO-T3"]["light"] == "red"
        # amber 的出现依赖具体日期差，这里只断言分档逻辑一致
        t2_risk = by_id["PO-T2"]["delay_risk"]
        expected = "red" if t2_risk >= RISK_RED else ("amber" if t2_risk >= RISK_AMBER else "green")
        assert by_id["PO-T2"]["light"] == expected

    def test_red_rows_sorted_first(self, empty_store):
        _order(empty_store, "PO-T4", etd=_day(90))
        _order(empty_store, "PO-T5", etd=_day(-150))
        board = empty_store.tracking_board()
        assert board["rows"][0]["id"] == "PO-T5"

    def test_summary_counts_match_rows(self, empty_store):
        _order(empty_store, "PO-T6", etd=_day(90))
        _order(empty_store, "PO-T7", etd=_day(-150))
        board = empty_store.tracking_board()
        s = board["summary"]
        assert s["in_production"] == len(board["rows"])
        assert s["red"] + s["amber"] + s["green"] == s["in_production"]

    def test_finished_orders_excluded(self, empty_store):
        _order(empty_store, "PO-T8", status="已签收")
        board = empty_store.tracking_board()
        assert all(r["id"] != "PO-T8" for r in board["rows"])


class TestCollectionsBoard:
    def test_unpaid_order_appears(self, empty_store):
        _order(empty_store, "PO-C1")
        board = empty_store.collections_board()
        row = next(r for r in board["rows"] if r["id"] == "PO-C1")
        assert row["due_amount"] == "6500.0"
        assert row["is_overdue"] is False

    def test_overdue_detected_when_due_date_passed(self, empty_store):
        # ETD 在过去 → 尾款到期日也在过去，但定金未付，两期都逾期
        _order(empty_store, "PO-C2", etd=_day(-10), deposit_due=_day(-20))
        board = empty_store.collections_board()
        row = next(r for r in board["rows"] if r["id"] == "PO-C2")
        assert row["is_overdue"] is True
        assert row["overdue_count"] == 2
        assert float(row["overdue_amount"]) > 0

    def test_paid_order_not_overdue(self, empty_store):
        _order(empty_store, "PO-C3", etd=_day(-10), deposit_due=_day(-20))
        empty_store.record_payment("PO-C3", "PAY-1", amount=1950)
        empty_store.record_payment("PO-C3", "PAY-2", amount=4550)
        board = empty_store.collections_board()
        row = next(r for r in board["rows"] if r["id"] == "PO-C3")
        assert row["is_overdue"] is False
        assert row["due_amount"] == "0.0"

    def test_partial_overdue_only_counts_unpaid(self, empty_store):
        _order(empty_store, "PO-C4", etd=_day(-10), deposit_due=_day(-20))
        empty_store.record_payment("PO-C4", "PAY-1", amount=1950)
        board = empty_store.collections_board()
        row = next(r for r in board["rows"] if r["id"] == "PO-C4")
        assert row["overdue_count"] == 1

    def test_overdue_rows_sorted_first(self, empty_store):
        _order(empty_store, "PO-C5", etd=_day(30))
        _order(empty_store, "PO-C6", etd=_day(-10), deposit_due=_day(-20))
        board = empty_store.collections_board()
        assert board["rows"][0]["id"] == "PO-C6"

    def test_summary_totals(self, empty_store):
        _order(empty_store, "PO-C7", etd=_day(30))
        _order(empty_store, "PO-C8", etd=_day(-10), deposit_due=_day(-20))
        s = empty_store.collections_board()["summary"]
        assert s["order_count"] == 2
        assert s["overdue_orders"] == 1
        assert float(s["total_due"]) > 0
        assert float(s["total_overdue"]) > 0

    def test_cancelled_order_excluded(self, empty_store):
        _order(empty_store, "PO-C9", status="已取消")
        board = empty_store.collections_board()
        assert all(r["id"] != "PO-C9" for r in board["rows"])


class TestAgingLevels:
    """催款力度随账龄升级：0 温和、7 内提醒、30 内正式、超 30 升级。"""

    @pytest.mark.parametrize(
        "days,expected_light",
        [
            (0, "green"),
            (-5, "green"),
            (1, "amber"),
            (7, "amber"),
            (8, "orange"),
            (30, "orange"),
            (31, "red"),
            (120, "red"),
        ],
    )
    def test_aging_boundaries(self, days, expected_light):
        from backend.agents.tools.extended import _aging_level

        light, action = _aging_level(days)
        assert light == expected_light
        assert action

    def test_dunning_script_escalates_with_days(self):
        from backend.agents.tools.extended import tool_dunning_script

        friendly = tool_dunning_script(overdue_days=0, customer_name="ACME", order_id="PO-1")
        harsh = tool_dunning_script(overdue_days=90, customer_name="ACME", order_id="PO-1")
        assert friendly["dunning"]["level"] == "green"
        assert harsh["dunning"]["level"] == "red"
        assert "immediate settlement" in harsh["dunning"]["script"].lower()


class TestOrderValidation:
    def test_requires_product_or_customer(self, empty_store):
        with pytest.raises(ValueError, match="产品或客户"):
            empty_store.upsert_order({"qty": "100", "unit_price": "5"})

    def test_update_preserves_payments_and_milestones(self, empty_store):
        """改交期时不能把已有的收款记录和节点进度冲掉。"""
        _order(empty_store, "PO-V1")
        empty_store.record_payment("PO-V1", "PAY-1", amount=1950)
        before = empty_store.get_order("PO-V1")

        after = empty_store.upsert_order(
            {"id": "PO-V1", "customer_name": "跟单测试客户", "product": "测试保温杯",
             "qty": "1000", "unit_price": "6.5", "etd": _day(90)}
        )
        assert after["paid_amount"] == before["paid_amount"]
        assert after["etd"] == _day(90)
        done = {m["key"] for m in after["milestones"] if m["status"] == "done"}
        assert done == {"deposit"}

    def test_meta_patch_whitelist(self, empty_store):
        _order(empty_store, "PO-V2")
        o = empty_store.update_order_meta("PO-V2", {"delivery_date": _day(45), "owner": "李海涛"})
        assert o["delivery_date"] == _day(45)
        assert o["owner"] == "李海涛"

    def test_meta_patch_rejects_amount_fields(self, empty_store):
        """金额字段必须走报价单，不能从 /meta 偷偷改。"""
        _order(empty_store, "PO-V3")
        o = empty_store.update_order_meta("PO-V3", {"unit_price": "1.00"})
        assert o["unit_price"] == "6.5"

    def test_delete_order(self, empty_store):
        _order(empty_store, "PO-V4")
        assert empty_store.delete_order("PO-V4") is True
        assert empty_store.delete_order("PO-V4") is False
