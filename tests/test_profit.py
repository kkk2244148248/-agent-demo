"""利润测算测试：收入 - 全成本 + 退税，含汇率压力测试与缺失值保护。

这组用例保护的是本项目最容易被误读的数字：
毛利率一旦算错（尤其是缺成本时给出 100% 毛利），
业务员就会拿着假的「高毛利」去接单。

所有用例都请求 `empty_store` 夹具，确保测的是纯计算逻辑，
而不会被种子订单（PO-1D01C6 等）的兜底取值污染。
"""
from __future__ import annotations

import pytest

from backend.agents.tools.extended import MARGIN_FLOOR_POLICY, tool_profit_calc

# 一个自洽的基准场景：
#   收入 1000 × 10 = 10000
#   工厂采购价 6 × 1000 = 6000
#   其他科目（按订单总额口径）合计 1100
#   退税 6000 × 13% = 780
#   毛利 = 10000 - 7100 + 780 = 3680 → 36.8%
BASE = {
    "unit_price": 10.0,
    "qty": 1000,
    "costs": {
        "工厂采购价": 6.0,
        "LOGO/印刷": 300,
        "内陆运费/拖车": 200,
        "报关/单证/商检": 150,
        "港杂/THC": 100,
        "海运费": 300,
        "保险": 50,
    },
    "rebate_rate": 0.13,
    "fx_rate": 7.2,
}


def calc(**overrides):
    """调用利润工具并只取利润段。overrides 直接并入 payload。"""
    payload = {**BASE}
    costs = payload["costs"]
    payload.update({k: v for k, v in overrides.items() if k != "costs"})
    if "costs" in overrides:
        payload["costs"] = overrides["costs"]
    elif costs is not payload.get("costs"):
        payload["costs"] = costs
    return tool_profit_calc(**payload)["profit"]


class TestProfitArithmetic:
    def test_full_cost_scenario(self, empty_store):
        p = calc()
        assert p["revenue"]["amount"] == pytest.approx(10000.0)
        assert p["total_cost"] == pytest.approx(7100.0)
        assert p["export_rebate"]["amount"] == pytest.approx(780.0)
        assert p["gross_profit"] == pytest.approx(3680.0)
        assert p["gross_margin"] == pytest.approx(0.368)

    def test_factory_cost_is_unit_based(self, empty_store):
        """工厂采购价按「单价 × 数量」，不是按总额——这是最容易搞错的科目。"""
        p = calc()
        line = next(x for x in p["cost_breakdown"] if x["item"] == "工厂采购价")
        assert line["unit"] == pytest.approx(6.0)
        assert line["amount"] == pytest.approx(6000.0)

    def test_other_costs_are_total_based(self, empty_store):
        """其余科目按订单总额口径传入，不应再乘数量。"""
        p = calc()
        line = next(x for x in p["cost_breakdown"] if x["item"] == "海运费")
        assert line["amount"] == pytest.approx(300.0)

    def test_rebate_based_on_factory_amount_not_revenue(self, empty_store):
        """退税基数是含税采购额，不是收入。"""
        base = calc()
        doubled = calc(rebate_rate=0.26)
        assert doubled["export_rebate"]["amount"] == pytest.approx(
            base["export_rebate"]["amount"] * 2
        )
        assert base["export_rebate"]["amount"] == pytest.approx(6000 * 0.13)

    def test_breakeven_and_suggested_floor(self, empty_store):
        p = calc()
        # 盈亏平衡 = (总成本 - 退税) / 数量 = (7100 - 780) / 1000
        assert p["breakeven_price"] == pytest.approx(6.32)
        # 建议底价 = 盈亏平衡 / (1 - 毛利红线)
        assert p["floor_advice"]["suggested_floor"] == pytest.approx(
            round(6.32 / (1 - MARGIN_FLOOR_POLICY), 2)
        )


class TestMissingCriticalCosts:
    """缺关键成本时必须给「谨慎」，绝不能凭空算出高毛利。"""

    def test_missing_factory_price_forces_zero_margin(self, empty_store):
        p = calc(costs={"海运费": 300})
        assert "工厂采购价" in " ".join(p["risk_flags"])
        assert p["gross_margin"] == 0.0
        assert p["verdict"] == "谨慎"

    def test_missing_rebate_rate_keeps_margin_but_flags(self, empty_store):
        """缺退税率时退税按 0 计，毛利被低估，必须打标提示核实。"""
        p = calc(rebate_rate=None)
        assert "退税率" in " ".join(p["risk_flags"])
        assert p["export_rebate"]["amount"] == 0.0
        # 少了 780 退税 → 毛利 = 3680 - 780 = 2900，毛利 29% 仍在健康区
        assert p["gross_profit"] == pytest.approx(2900.0)
        assert p["gross_margin"] == pytest.approx(0.29)
        # 但系统判定为谨慎：退税率未核实前不应直接放行
        assert p["verdict"] == "谨慎"

    def test_partial_costs_still_judged_when_factory_price_present(self, empty_store):
        """只要工厂采购价在，就允许按已有科目给出判定（并提示缺口）。"""
        p = calc(costs={"工厂采购价": 6.0}, rebate_rate=0.13)
        assert p["gross_margin"] > 0
        assert "海运费" in " ".join(p["risk_flags"])

    def test_no_revenue_is_cautious(self, empty_store):
        p = tool_profit_calc(
            unit_price=0, qty=0, costs={"工厂采购价": 5}, rebate_rate=0.13
        )["profit"]
        assert p["verdict"] == "谨慎"


class TestVerdictThresholds:
    """判定分档：低于红线不可接，贴着红线要谨慎，其余可接。"""

    def test_below_floor_is_rejected(self, empty_store):
        # 售价 7.0：收入 7000，成本 7100，退税 780 → 毛利 680 → 9.7% < 12%
        p = calc(unit_price=7.0)
        assert p["gross_margin"] < MARGIN_FLOOR_POLICY
        assert p["verdict"] == "不可接"

    def test_near_floor_is_cautious(self, empty_store):
        # 售价 7.6：收入 7600，毛利 1280 → 16.8%？需要落在 [12%,15%)
        # 用 7.3：收入 7300，毛利 980 → 13.4%，正好是「谨慎」区间
        p = calc(unit_price=7.3)
        assert MARGIN_FLOOR_POLICY <= p["gross_margin"] < MARGIN_FLOOR_POLICY + 0.03
        assert p["verdict"] == "谨慎"

    def test_healthy_margin_is_accepted(self, empty_store):
        p = calc()
        assert p["gross_margin"] >= MARGIN_FLOOR_POLICY + 0.03
        assert p["verdict"] == "可接"


class TestFxStress:
    """人民币升值 3% 的压力测试。"""

    def test_stress_rate_is_3_percent_stronger(self, empty_store):
        p = calc()
        assert p["fx"]["assumed_rate"] == pytest.approx(7.2)
        assert p["fx"]["stress_rate"] == pytest.approx(round(7.2 * 0.97, 3))

    def test_fx_loss_reduces_margin(self, empty_store):
        p = calc()
        assert p["net_margin_after_fx"] < p["gross_margin"]

    def test_thin_margin_flags_fx_risk(self, empty_store):
        """薄毛利订单在汇率压力下会跌破红线，必须打标。"""
        p = calc(unit_price=7.3)
        assert p["net_margin_after_fx"] < MARGIN_FLOOR_POLICY
        assert any("汇率" in f for f in p["risk_flags"])

    def test_custom_fx_rate_respected(self, empty_store):
        p = calc(fx_rate=7.0)
        assert p["fx"]["assumed_rate"] == pytest.approx(7.0)


class TestOrderFallback:
    """绑定了真实订单时，收入应从订单取，不必要求业务员重复手填。"""

    def test_reads_revenue_from_order(self, store):
        store.upsert_order(
            {
                "id": "PO-UT01",
                "customer_name": "测试客户",
                "product": "测试杯",
                "qty": "1000",
                "unit_price": "10",
                "currency": "USD",
            }
        )
        p = tool_profit_calc(
            order_id="PO-UT01",
            costs={"工厂采购价": 6.0, "海运费": 300},
            rebate_rate=0.13,
        )["profit"]
        # 收入来自订单 10 × 1000
        assert p["revenue"]["amount"] == pytest.approx(10000.0)
        assert p["qty"] == pytest.approx(1000.0)
        factory = next(x for x in p["cost_breakdown"] if x["item"] == "工厂采购价")
        assert factory["amount"] == pytest.approx(6000.0)

    def test_extracts_id_from_natural_language(self, store):
        """用户说「帮我算一下 PO-UT02 的利润」时也应能定位到订单。"""
        store.upsert_order(
            {
                "id": "PO-UT02",
                "customer_name": "测试客户",
                "product": "测试杯",
                "qty": "500",
                "unit_price": "12",
            }
        )
        p = tool_profit_calc(
            query="帮我算一下 PO-UT02 的利润",
            costs={"工厂采购价": 7.0, "海运费": 200},
            rebate_rate=0.13,
        )["profit"]
        assert p["revenue"]["amount"] == pytest.approx(6000.0)

    def test_accepts_explicit_revenue_when_order_has_no_unit_price(self, store):
        """订单只有数量没有单价时，允许调用方直接给收入总额。"""
        store.upsert_order(
            {
                "id": "PO-UT03",
                "customer_name": "测试客户",
                "product": "测试杯",
                "qty": "0",
                "unit_price": "0",
            }
        )
        p = tool_profit_calc(
            order_id="PO-UT03",
            revenue=8000,
            costs={"工厂采购价": 5.0},
            rebate_rate=0.13,
        )["profit"]
        assert p["revenue"]["amount"] == pytest.approx(8000.0)


class TestOutputContract:
    """字段契约：前端图表直接读这些 key，缺一个就白屏。"""

    def test_returns_all_fields_frontend_depends_on(self, empty_store):
        p = calc()
        for key in (
            "currency", "qty", "revenue", "cost_breakdown", "total_cost",
            "export_rebate", "fx", "gross_profit", "gross_margin",
            "net_margin_after_fx", "breakeven_price", "floor_advice",
            "risk_flags", "verdict", "next_actions",
        ):
            assert key in p, f"缺少字段 {key}"

    def test_summary_mentions_verdict_and_numbers(self, empty_store):
        result = tool_profit_calc(**BASE)
        assert "判定「可接」" in result["summary"]
        assert "10000" in result["summary"]

    def test_actions_point_to_real_routes(self, empty_store):
        paths = {a["path"] for a in tool_profit_calc(**BASE)["actions"]}
        assert paths == {"/quotations", "/collections"}
