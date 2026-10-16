"""无 API Key / 调试时的规则 LLM：按 agent_type 返回礼品寻源场景结果。"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def _human_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage) or getattr(m, "type", "") == "human":
            return str(getattr(m, "content", m))
    return str(getattr(messages[-1], "content", "")) if messages else ""


class MockChatModel(BaseChatModel):
    agent_type: str = Field(default="reply")

    @property
    def _llm_type(self) -> str:
        return "mock-sourcing-llm"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        human = _human_text(messages)
        text = self._fake_response(human)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _detect_category(self, text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["hoodie", "卫衣", "t-shirt", "服饰", "embroidery"]):
            return "服饰"
        if any(k in t for k in ["power bank", "充电宝", "u盘", "数码", "10000mah"]):
            return "数码"
        if any(k in t for k in ["tote", "帆布", "bag", "包袋", "トート"]):
            return "包袋"
        if any(k in t for k in ["umbrella", "伞", "雨伞"]):
            return "雨伞"
        if any(k in t for k in ["tumbler", "保温杯", "杯"]):
            return "保温杯"
        if "hoodie" in t and "tumbler" in t:
            return "组合"
        return "其他"

    def _fake_response(self, human: str) -> str:
        cat = self._detect_category(human)
        qty = 1000
        m = re.search(r"(\d{3,5})\s*(pcs|pieces|枚|个|件|把)?", human, re.I)
        if m:
            qty = int(m.group(1))

        if self.agent_type == "requirement":
            mapping = {
                "保温杯": ("500ml不锈钢保温杯带LOGO", "保温杯 500ml 激光 LOGO 义乌"),
                "包袋": ("帆布/环保袋带单色LOGO", "帆布袋 再生 丝印 东莞"),
                "数码": ("10000mAh充电宝带认证", "充电宝 10000mAh CE FCC UN38.3 深圳"),
                "雨伞": ("三折防晒伞带LOGO", "三折伞 黑胶 LOGO 永康"),
                "服饰": ("连帽卫衣刺绣LOGO", "卫衣 刺绣 欧码 绍兴"),
                "组合": ("卫衣+保温杯会员礼盒", "卫衣 保温杯 组合 礼品"),
                "其他": ("礼品定制需求", "礼品 定制 厂商"),
            }
            summary, q = mapping.get(cat, mapping["其他"])
            return json.dumps(
                {
                    "category": cat,
                    "product_summary": summary,
                    "quantity": qty,
                    "budget_min": 2,
                    "budget_max": 12,
                    "budget_currency": "USD",
                    "logo_requirement": "单色LOGO",
                    "certifications": [],
                    "deadline": "见邮件",
                    "sample_needed": True,
                    "language": "en",
                    "key_constraints": ["需国内厂商", "要参考报价"],
                    "search_query": q,
                },
                ensure_ascii=False,
            )

        if self.agent_type == "vendor_match":
            catalog = {
                "保温杯": [("V-YH01", "义乌星海家居礼品有限公司", "保温杯主力厂，交期稳")],
                "包袋": [("V-DG02", "东莞绿叶包袋制品厂", "帆布/RPET袋成熟")],
                "数码": [("V-SZ03", "深圳能量数码礼品有限公司", "充电宝有CE/FCC/UN38.3经验")],
                "雨伞": [("V-YK05", "永康晴雨伞业有限公司", "三折伞量大价优")],
                "服饰": [("V-SX04", "绍兴暖织服饰礼品有限公司", "卫衣刺绣可做欧码")],
                "组合": [
                    ("V-SX04", "绍兴暖织服饰礼品有限公司", "负责卫衣"),
                    ("V-YH01", "义乌星海家居礼品有限公司", "负责保温杯"),
                ],
                "其他": [("V-YH01", "义乌星海家居礼品有限公司", "综合礼品可转介绍")],
            }
            items = catalog.get(cat, catalog["其他"])
            return json.dumps(
                {
                    "matched_vendors": [
                        {
                            "vendor_id": vid,
                            "vendor_name": name,
                            "fit_reason": reason,
                            "can_do": True,
                            "risks": "旺季交期需再确认",
                        }
                        for vid, name, reason in items
                    ],
                    "missing_info": ["最终LOGO文件", "确认含税口径"],
                },
                ensure_ascii=False,
            )

        if self.agent_type == "compare":
            price = {
                "保温杯": (18, 2.5, 500, 20),
                "包袋": (7, 1.0, 500, 15),
                "数码": (42, 5.8, 300, 25),
                "雨伞": (14, 2.0, 500, 18),
                "服饰": (55, 7.5, 200, 28),
                "组合": (70, 9.5, 300, 30),
                "其他": (20, 2.8, 500, 20),
            }
            cny, usd, moq, days = price.get(cat, price["其他"])
            vid = {
                "保温杯": ("V-YH01", "义乌星海家居礼品有限公司"),
                "包袋": ("V-DG02", "东莞绿叶包袋制品厂"),
                "数码": ("V-SZ03", "深圳能量数码礼品有限公司"),
                "雨伞": ("V-YK05", "永康晴雨伞业有限公司"),
                "服饰": ("V-SX04", "绍兴暖织服饰礼品有限公司"),
                "组合": ("V-SX04", "绍兴暖织服饰礼品有限公司"),
                "其他": ("V-YH01", "义乌星海家居礼品有限公司"),
            }[cat if cat in {"保温杯", "包袋", "数码", "雨伞", "服饰", "组合"} else "其他"]
            return json.dumps(
                {
                    "options": [
                        {
                            "vendor_id": vid[0],
                            "vendor_name": vid[1],
                            "ref_unit_price_cny": cny,
                            "ref_unit_price_foreign": usd,
                            "foreign_currency": "USD",
                            "moq": moq,
                            "lead_time_days": days,
                            "logo_cost_note": "LOGO费用另计，视工艺",
                            "pros": "品类匹配、有量产经验",
                            "cons": "最终价需锁样品后确认",
                            "recommend_level": "首选",
                        }
                    ],
                    "suggested_client_price_note": "以上为工厂参考区间，对外报价请另加服务费/利润后由人工核定。",
                    "next_actions": ["向首选厂要正式报价单", "确认LOGO文件", "安排样品"],
                },
                ensure_ascii=False,
            )

        if self.agent_type == "factory_brief":
            return (
                "您好，我们是礼品中国分部，有一单海外礼品询价想请贵司评估：\n"
                f"1）产品方向：{cat}\n"
                f"2）数量：约 {qty}\n"
                "3）需要 LOGO 定制，请告知可否做及工艺建议\n"
                "4）请提供：MOQ、含税/不含税参考价、打样费、样品周期、大货交期\n"
                "5）如有认证（食品接触/CE/FCC/UN38.3等）也请一并说明\n"
                "麻烦尽快回复，谢谢！"
            )

        # reply
        return (
            "Dear Team,\n\n"
            "Thanks for your gift brief. Our China sourcing desk has shortlisted factories "
            f"for this request ({cat}).\n\n"
            "Indicative option (factory reference, not final sell price):\n"
            "- Capable supplier found in our vendor list\n"
            "- Rough unit price / MOQ / lead time will be confirmed after logo file review\n"
            "- We recommend sampling before bulk PO\n\n"
            "Please share: final quantity, logo artwork, and preferred Incoterms.\n"
            "We will revert with 1-2 factory options and a checked offer.\n\n"
            "Best regards,\nChina Sourcing Team"
        )
