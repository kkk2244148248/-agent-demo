"""报价单测试：底价红线、老板特批、版本归档、丢单复盘。

底价机制是这个项目的风控核心，也是最容易被绕过的环节：
业务员为了成单会想各种办法压价，所以规则的每一条都要有测试兜住。
"""
from __future__ import annotations

import pytest

from backend.services.repositories.normalizers import (
    normalize_quotation,
    recompute_quote_floor,
)


def _lines(*specs) -> list[dict]:
    """按 (单价, 数量) 快速构造明细行。"""
    return [
        {"product": f"产品{i}", "qty": str(qty), "unit_price": str(price)}
        for i, (price, qty) in enumerate(specs, 1)
    ]


def _quote(store, qid: str, price, floor="5.00", qty=1000, **extra) -> dict:
    payload = {
        "id": qid,
        "customer_name": "底价测试客户",
        "currency": "USD",
        "floor_price": floor,
        "lines": _lines((price, qty)),
        **extra,
    }
    return store.upsert_quotation(payload)


class TestFloorPriceDetection:
    """判定规则：只有设了单据底价才判定，未设底价不误伤。"""

    def test_below_floor_detected(self, empty_store):
        q = _quote(empty_store, "QT-A1", 3.50, floor="5.00")
        assert q["below_floor"] is True
        assert q["boss_approved"] is False

    def test_at_floor_is_not_below(self, empty_store):
        """等于底价不算低于底价——边界不能写成 <=。"""
        q = _quote(empty_store, "QT-A2", 5.00, floor="5.00")
        assert q["below_floor"] is False

    def test_above_floor_is_fine(self, empty_store):
        q = _quote(empty_store, "QT-A3", 6.00, floor="5.00")
        assert q["below_floor"] is False

    def test_no_floor_set_means_no_judgement(self, empty_store):
        """没设底价时不判定，否则所有报价都会被标红。"""
        q = _quote(empty_store, "QT-A4", 1.00, floor="")
        assert q["below_floor"] is False

    def test_zero_price_line_ignored(self, empty_store):
        """尚未填价的草稿行不应触发红线判定。"""
        q = _quote(empty_store, "QT-A5", 0, floor="5.00")
        assert q["below_floor"] is False

    def test_recompute_is_pure_and_idempotent(self):
        item = {"floor_price": "5", "lines": [{"unit_price": "3"}]}
        recompute_quote_floor(item)
        assert item["below_floor"] is True
        recompute_quote_floor(item)
        assert item["below_floor"] is True

    def test_per_line_floor_overrides_document_floor(self, empty_store):
        """行级底价优先：不同产品线成本差异大，底价不能一刀切。"""
        q = empty_store.upsert_quotation(
            {
                "id": "QT-A6",
                "floor_price": "5.00",
                "lines": [{"qty": "100", "unit_price": "4.00", "floor_price": "3.00"}],
            }
        )
        assert q["below_floor"] is False


class TestBossApproval:
    """特批：低于底价必须老板放行，且只在「这件事」上有效。"""

    def test_approve_below_floor_grants_flag(self, empty_store):
        q = _quote(empty_store, "QT-B1", 3.50, floor="5.00")
        q["approve_below_floor"] = True
        updated = empty_store.upsert_quotation(q)
        assert updated["boss_approved"] is True
        assert updated["below_floor"] is True

    def test_approval_cleared_when_back_above_floor(self, empty_store):
        """价格改回底价之上后，旧特批不能留着。"""
        q = _quote(empty_store, "QT-B2", 3.50, floor="5.00")
        q["approve_below_floor"] = True
        empty_store.upsert_quotation(q)
        q2 = _quote(empty_store, "QT-B2", 6.00, floor="5.00")
        assert q2["boss_approved"] is False
        assert q2["below_floor"] is False

    def test_approval_cleared_on_further_price_change(self, empty_store):
        """特批是针对当时那个价格的，改价必须重新审批。"""
        q = _quote(empty_store, "QT-B3", 3.50, floor="5.00")
        q["approve_below_floor"] = True
        assert empty_store.upsert_quotation(q)["boss_approved"] is True
        # 再降一次价
        q2 = _quote(empty_store, "QT-B3", 3.00, floor="5.00")
        assert q2["boss_approved"] is False
        assert q2["below_floor"] is True

    def test_recompute_never_grants_approval(self):
        """纯函数只负责撤销，不能自己发放特批。"""
        item = {"floor_price": "5", "lines": [{"unit_price": "3"}], "boss_approved": False}
        recompute_quote_floor(item)
        assert item["boss_approved"] is False


class TestVersioning:
    """改价必留痕：版本号递增，历史进 versions。"""

    def test_first_save_is_version_1(self, empty_store):
        q = _quote(empty_store, "QT-C1", 6.00)
        assert q["version"] == 1
        assert q["versions"] == []

    def test_unchanged_save_does_not_bump_version(self, empty_store):
        """只改备注不改价，不应产生新版本。"""
        _quote(empty_store, "QT-C2", 6.00)
        again = _quote(empty_store, "QT-C2", 6.00, notes="加了一句备注")
        assert again["version"] == 1
        assert again["versions"] == []

    def test_price_change_bumps_version_and_archives(self, empty_store):
        _quote(empty_store, "QT-C3", 6.00)
        v2 = _quote(empty_store, "QT-C3", 5.50)
        assert v2["version"] == 2
        assert len(v2["versions"]) == 1
        archived = v2["versions"][0]
        assert archived["version"] == 1
        assert archived["total"] == "6000.0"

    def test_quantity_change_is_also_a_price_change(self, empty_store):
        """数量和单价都会改变总额，同样要留痕。"""
        _quote(empty_store, "QT-C4", 6.00, qty=1000)
        v2 = _quote(empty_store, "QT-C4", 6.00, qty=800)
        assert v2["version"] == 2

    def test_version_history_capped(self, empty_store):
        """版本历史要有上限，否则 runtime.json 会无限膨胀。"""
        from backend.services.repositories.quotation_repo import MAX_KEPT_VERSIONS

        for i in range(MAX_KEPT_VERSIONS + 6):
            _quote(empty_store, "QT-C5", 6.00 + i * 0.1)
        q = empty_store.get_quotation("QT-C5")
        assert len(q["versions"]) == MAX_KEPT_VERSIONS
        assert q["version"] == MAX_KEPT_VERSIONS + 6

    def test_new_version_resets_approval_and_status(self, empty_store):
        q = _quote(empty_store, "QT-C6", 3.50, floor="5.00")
        q["approve_below_floor"] = True
        empty_store.upsert_quotation(q)
        v2 = empty_store.new_quotation_version("QT-C6", _lines((4.00, 1000)), "李海涛", "客户压价")
        assert v2["version"] == 2
        assert v2["boss_approved"] is False
        assert v2["status"] == "draft"
        assert v2["notes"] == "客户压价"
        assert len(v2["versions"]) == 1

    def test_new_version_recomputes_total(self, empty_store):
        _quote(empty_store, "QT-C7", 6.00)
        v2 = empty_store.new_quotation_version("QT-C7", _lines((7.00, 500)), "李海涛")
        assert v2["total"] == "3500.0"

    def test_new_version_on_missing_quote_returns_none(self, empty_store):
        assert empty_store.new_quotation_version("QT-NOPE", []) is None


class TestTotals:
    def test_total_is_sum_of_line_amounts(self, empty_store):
        q = empty_store.upsert_quotation(
            {
                "id": "QT-D1",
                "lines": _lines((10.0, 100), (5.0, 200)),
            }
        )
        assert q["total"] == "2000.0"

    def test_falls_back_to_provided_total(self, empty_store):
        """明细没有数量/单价时，保留调用方给的总额（如手工议定价）。"""
        q = empty_store.upsert_quotation({"id": "QT-D2", "total": "8888", "lines": []})
        assert q["total"] == "8888"

    def test_strips_currency_symbols_in_amounts(self, empty_store):
        q = empty_store.upsert_quotation(
            {
                "id": "QT-D3",
                "lines": [{"qty": "1,000", "unit_price": "$6.5"}],
            }
        )
        assert q["total"] == "6500.0"


class TestLostAndStatus:
    def test_lost_records_reason(self, empty_store):
        _quote(empty_store, "QT-E1", 6.00)
        q = empty_store.get_quotation("QT-E1")
        q["status"] = "rejected"
        q["lost_reason"] = "价格高于竞品 8%"
        saved = empty_store.upsert_quotation(q)
        assert saved["lost_reason"] == "价格高于竞品 8%"

    def test_sent_status_stamps_time(self, empty_store):
        _quote(empty_store, "QT-E2", 6.00)
        q = empty_store.get_quotation("QT-E2")
        q["status"] = "sent"
        assert empty_store.upsert_quotation(q)["sent_at"] != ""

    def test_versions_view_includes_current(self, empty_store):
        """版本时间线要把「当前版」也列进去，否则用户看不懂改到第几版。"""
        _quote(empty_store, "QT-E3", 6.00)
        _quote(empty_store, "QT-E3", 5.50)
        view = empty_store.quotation_versions("QT-E3")
        assert view is not None
        assert len(view["versions"]) == 2
        assert view["versions"][-1]["is_current"] is True
        assert view["versions"][-1]["version"] == 2

    def test_versions_view_missing_returns_none(self, empty_store):
        assert empty_store.quotation_versions("QT-NOPE") is None


class TestPersistenceRoundTrip:
    """落盘再读回，派生字段必须被重算出来（否则看板会缺数据）。"""

    def test_below_floor_survives_reload(self, tmp_path, monkeypatch):
        from backend.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "storage_dir", str(tmp_path), raising=False)

        from backend.services import store as store_module

        first = store_module.RuntimeStore()
        first.data["customers"] = []
        first.data["quotations"] = []
        first.upsert_quotation(
            {
                "id": "QT-F1",
                "floor_price": "5.00",
                "lines": [{"qty": "1000", "unit_price": "3.00"}],
            }
        )
        assert first.get_quotation("QT-F1")["below_floor"] is True

        # 重新打开（模拟进程重启）
        second = store_module.RuntimeStore()
        reloaded = second.get_quotation("QT-F1")
        assert reloaded is not None
        assert reloaded["below_floor"] is True

    def test_normalize_adds_missing_fields(self):
        item = {"lines": [{"unit_price": "10"}]}
        normalize_quotation(item)
        for key in ("version", "versions", "floor_price", "below_floor", "boss_approved"):
            assert key in item
        assert item["lines"][0]["floor_price"] == ""
