"""意图识别 → 匹配 Skill → 产出工具链。"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.skills.loader import get_skill, list_skills
from backend.agents.tools.handlers import bootstrap_tools
from backend.agents.tools.registry import list_tools
from backend.core.logger import get_logger

logger = get_logger(__name__)

# 规则匹配优先级（越靠前越先判定）
# 顺序原则：先判「动作明确且易误判」的，再判泛化意图，kb_qa 永远兜底。
_RULE_ORDER = [
    # 强动作、强关键词（先说先判，避免被泛化规则抢走）
    "crm_action",
    "doc_parse",
    "full_rfq",
    "floor_price_guard",
    "profit_check",
    "collection_chase",
    "tracking_board",
    "customer_radar",
    "followup_mail",
    "email_todos",
    "sample_track",
    "cert_check",
    "vendor_risk",
    "cost_estimate",
    "ask_factory",
    "reply_overseas",
    "compare_quotes",
    "parse_requirement",
    "find_vendor",
    # 兜底
    "kb_qa",
]


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}


def _skill_catalog_prompt() -> str:
    lines = []
    for s in list_skills():
        tools = ", ".join(s.get("tools") or []) or "(无工具，走知识库)"
        lines.append(
            f"- {s['id']}: {s['title']} | {s.get('when') or s.get('description')} | tools=[{tools}] | mode={s.get('mode')}"
        )
    return "\n".join(lines)


def _enrich(skill_id: str, reason: str, tools_override: list[str] | None = None) -> dict[str, Any]:
    skill = get_skill(skill_id) or {
        "id": skill_id,
        "title": skill_id,
        "tools": tools_override or [],
        "mode": "agents",
        "parallel_ok": False,
    }
    known = {x["name"] for x in list_tools()} if skill.get("mode") != "kb" else set()
    raw_tools = tools_override if tools_override is not None else list(skill.get("tools") or [])
    if skill.get("mode") == "kb":
        tools: list[str] = []
    else:
        tools = [t for t in raw_tools if t in known]
    return {
        "skill": skill["id"],
        "skill_title": skill.get("title") or skill["id"],
        "skill_mode": skill.get("mode") or "agents",
        "tools": tools,
        "reason": reason or skill.get("when") or "",
        "intents": [skill["id"]],
        "parallel_ok": bool(skill.get("parallel_ok", False)),
    }


def _rule_match_skill(user_goal: str, has_product_hint: bool = False) -> dict[str, Any]:
    """无模型或兜底：按 triggers 命中 Skill。"""
    g = (user_goal or "").lower()
    skills = {s["id"]: s for s in list_skills()}

    for sid in _RULE_ORDER:
        skill = skills.get(sid)
        if not skill:
            continue
        triggers = [t.lower() for t in (skill.get("triggers") or [])]
        if any(t in g for t in triggers):
            # find_vendor：无产品线索时前置 parse
            if sid == "find_vendor":
                tools = list(skill.get("tools") or [])
                if not has_product_hint and "parse_requirement" not in tools:
                    tools = ["parse_requirement"] + tools
                # 「只要找厂」保持仅 search
                if any(k in g for k in ["只要", "仅", "只找", "only"]):
                    tools = ["search_vendors"]
                return _enrich(sid, f"规则命中：{skill.get('title')}", tools)
            return _enrich(sid, f"规则命中：{skill.get('title')}")

    # 模糊找厂
    if any(k in g for k in ["找厂", "厂商", "谁能做", "vendor", "匹配"]) or (
        ("找" in g or "哪家" in g or "有没有" in g) and ("厂" in g or "做" in g)
    ):
        tools = ["search_vendors"]
        if not has_product_hint:
            tools = ["parse_requirement", "search_vendors"]
        if any(k in g for k in ["只要", "仅", "只找", "only"]):
            tools = ["search_vendors"]
        return _enrich("find_vendor", "规则命中：找厂/匹配厂商", tools)

    # 默认：有询盘上下文 → 解析+找厂；纯闲聊式问题 → kb_qa
    if has_product_hint or len(g) > 8:
        return _enrich(
            "find_vendor",
            "默认：先拆需求并找厂",
            ["parse_requirement", "search_vendors"],
        )
    return _enrich("kb_qa", "默认：知识问答（无明确业务动作）")


def _llm_match_skill(user_goal: str, inquiry_hint: str) -> dict[str, Any] | None:
    from backend.config import get_settings
    from backend.core.llm_factory import get_llm

    if not get_settings().use_real_llm:
        return None

    catalog = _skill_catalog_prompt()
    from backend.agents.prompts_registry import DISPATCH_SKILL_SYSTEM

    system = DISPATCH_SKILL_SYSTEM.format(catalog=catalog)
    llm = get_llm("intent", temperature=0)
    prompt = f"用户目标：{user_goal}\n需求摘要：{inquiry_hint[:500]}"
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    data = _parse_json(getattr(resp, "content", "") or str(resp))
    sid = (data.get("skill") or "").strip()
    if not sid or not get_skill(sid):
        return None
    tools_override = data.get("tools")
    if isinstance(tools_override, list) and tools_override:
        return _enrich(sid, data.get("reason") or "", [str(t) for t in tools_override])
    plan = _enrich(sid, data.get("reason") or "")
    if "parallel_ok" in data:
        plan["parallel_ok"] = bool(data.get("parallel_ok"))
    return plan


def match_skill(user_goal: str, inquiry_hint: str = "") -> dict[str, Any]:
    """识别意图并匹配 Skill，返回 skill + tools + reason。"""
    bootstrap_tools()
    hint = inquiry_hint or ""
    has_product = bool(hint.strip()) and len(hint.strip()) > 20
    # 目标里自带产品词也算有线索
    g = user_goal or ""
    if any(k in g for k in ["杯", "伞", "袋", "服", "充电宝", "礼品", "tumbler", "hoodie"]):
        has_product = True

    try:
        plan = _llm_match_skill(user_goal, hint)
        if plan:
            logger.info(f"match_skill.llm skill={plan.get('skill')} tools={plan.get('tools')}")
            return plan
    except Exception as e:
        logger.error(f"match_skill.llm_fallback err={e}")

    plan = _rule_match_skill(user_goal, has_product_hint=has_product)
    logger.info(f"match_skill.rule skill={plan.get('skill')} tools={plan.get('tools')}")
    return plan
