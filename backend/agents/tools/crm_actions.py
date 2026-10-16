"""
CRM 操作工具：从用户自然语言抽取字段并写入客户/厂商/跟进；
信息不足时返回页面跳转链接。
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.services.store import get_store

logger = get_logger(__name__)

NAV_MAP = {
    "vendors": {"path": "/vendors", "label": "打开厂商名录"},
    "customers": {"path": "/customers", "label": "打开海外客户"},
    "followups": {"path": "/followups", "label": "打开跟进待办"},
    "inbox": {"path": "/inbox", "label": "打开需求收件箱"},
    "samples": {"path": "/samples", "label": "打开样品进度"},
    "quotations": {"path": "/quotations", "label": "打开报价单"},
    "orders": {"path": "/orders", "label": "打开订单"},
    "assistant": {"path": "/assistant", "label": "打开对话助手"},
    "knowledge": {"path": "/knowledge", "label": "打开知识库"},
}


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


def _link(page: str, label: str | None = None, query: str = "") -> dict[str, str]:
    meta = NAV_MAP.get(page) or {"path": f"/{page}", "label": label or page}
    path = meta["path"]
    if query:
        path = f"{path}?{query}" if "?" not in path else f"{path}&{query}"
    return {"type": "link", "page": page, "path": path, "label": label or meta["label"]}


def _extract_crm_payload(user_text: str, intent: str) -> dict[str, Any]:
    """用 LLM/规则从自然语言抽字段。"""
    g = user_text or ""
    # 规则兜底
    rule: dict[str, Any] = {"intent": intent, "fields": {}, "missing": [], "can_execute": False}

    if intent == "add_vendor":
        # 简单抓「叫XX」「名称XX」
        m = re.search(r"(?:厂商|厂名|厂家|供应商)[：:\s]*([^\s,，。；;]+)", g)
        if not m:
            m = re.search(r"(?:添加|新建|登记)(?:一个)?(?:厂商|厂家)?[：:\s]*([^\s,，。；;]+)", g)
        if m:
            rule["fields"]["name"] = m.group(1)
        m2 = re.search(r"(?:地区|区域|地址)[：:\s]*([^\s,，。；;]+)", g)
        if m2:
            rule["fields"]["region"] = m2.group(1)
        m3 = re.search(r"(?:联系人)[：:\s]*([^\s,，。；;]+)", g)
        if m3:
            rule["fields"]["contact"] = m3.group(1)
        m4 = re.search(r"(?:品类|擅长|做)[：:\s]*([^\n]+)", g)
        if m4:
            rule["fields"]["categories"] = m4.group(1).strip()
            rule["fields"]["strengths"] = m4.group(1).strip()
        if rule["fields"].get("name"):
            rule["can_execute"] = True
        else:
            rule["missing"] = ["name"]

    elif intent == "add_customer":
        m = re.search(r"(?:客户|公司)[：:\s]*([^\s,，。；;]+)", g)
        if not m:
            m = re.search(r"(?:添加|新建)(?:一个)?客户[：:\s]*([^\s,，。；;]+)", g)
        if m:
            rule["fields"]["name"] = m.group(1)
        m2 = re.search(r"(?:国家|地区)[：:\s]*([^\s,，。；;]+)", g)
        if m2:
            rule["fields"]["country"] = m2.group(1)
        m3 = re.search(r"(?:联系人)[：:\s]*([^\s,，。；;]+)", g)
        if m3:
            rule["fields"]["contact"] = m3.group(1)
        m4 = re.search(r"[\w.+-]+@[\w.-]+", g)
        if m4:
            rule["fields"]["email"] = m4.group(0)
        if rule["fields"].get("name"):
            rule["can_execute"] = True
        else:
            rule["missing"] = ["name"]

    elif intent == "add_followup":
        m = re.search(r"(?:客户)[：:\s]*([^\s,，。；;]+)", g)
        if m:
            rule["fields"]["customer_name"] = m.group(1)
        m2 = re.search(r"(?:原因|事项|跟进)[：:\s]*([^\n]+)", g)
        if m2:
            rule["fields"]["reason"] = m2.group(1).strip()
        elif "跟进" in g:
            rule["fields"]["reason"] = g.strip()[:80]
        if rule["fields"].get("customer_name") or rule["fields"].get("reason"):
            rule["can_execute"] = True
            if not rule["fields"].get("reason"):
                rule["fields"]["reason"] = "业务跟进"
        else:
            rule["missing"] = ["customer_name", "reason"]

    # LLM 增强
    try:
        from backend.config import get_settings

        if get_settings().use_real_llm:
            llm = get_llm("intent", temperature=0)
            system = f"""从用户话里抽取 CRM 字段。意图={intent}。
输出 JSON：
{{
  "fields": {{...可写入字段...}},
  "missing": ["缺的必填字段"],
  "can_execute": true/false,
  "confirm_summary": "一句话确认将写入什么"
}}
厂商必填 name；客户必填 name；跟进建议有 customer_name 或 reason。
只输出 JSON。"""
            resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=g)])
            data = _parse_json(getattr(resp, "content", "") or "")
            if data.get("fields"):
                rule["fields"] = {**rule.get("fields", {}), **(data.get("fields") or {})}
            if "can_execute" in data:
                rule["can_execute"] = bool(data["can_execute"]) and bool(rule["fields"])
            if data.get("missing"):
                rule["missing"] = data["missing"]
            if data.get("confirm_summary"):
                rule["confirm_summary"] = data["confirm_summary"]
            # 厂商名兜底
            if intent == "add_vendor" and rule["fields"].get("name"):
                rule["can_execute"] = True
            if intent == "add_customer" and rule["fields"].get("name"):
                rule["can_execute"] = True
    except Exception as e:
        logger.error(f"crm.extract_llm_fallback err={e}")

    return rule


def _detect_intent(text: str) -> str:
    g = (text or "").lower()
    if any(k in g for k in ["添加厂商", "新建厂商", "登记厂商", "加个厂", "加厂商", "新增厂商", "录入厂商"]):
        return "add_vendor"
    if any(k in g for k in ["添加客户", "新建客户", "加客户", "新增客户", "录入客户"]):
        return "add_customer"
    if any(k in g for k in ["添加跟进", "新建跟进", "加跟进", "记个跟进"]):
        return "add_followup"
    if any(k in g for k in ["打开厂商", "去厂商", "厂商页", "厂商名录"]):
        return "goto_vendors"
    if any(k in g for k in ["打开客户", "去客户", "客户页"]):
        return "goto_customers"
    if any(k in g for k in ["打开跟进", "去跟进", "跟进页"]):
        return "goto_followups"
    if any(k in g for k in ["打开询盘", "收件箱", "去询盘"]):
        return "goto_inbox"
    if any(k in g for k in ["打开样品", "样品页"]):
        return "goto_samples"
    if any(k in g for k in ["打开报价", "报价页"]):
        return "goto_quotations"
    if any(k in g for k in ["打开订单", "订单页"]):
        return "goto_orders"
    if "厂商" in g and any(k in g for k in ["添加", "新建", "登记", "录入", "加"]):
        return "add_vendor"
    if "客户" in g and any(k in g for k in ["添加", "新建", "登记", "录入", "加"]):
        return "add_customer"
    return "goto_vendors"


def tool_crm_action(**payload: Any) -> dict[str, Any]:
    """统一 CRM：执行写入或返回跳转。"""
    text = (payload.get("query") or payload.get("body") or payload.get("user_goal") or "").strip()
    intent = (payload.get("crm_intent") or "").strip() or _detect_intent(text)
    actions: list[dict[str, Any]] = []
    store = get_store()

    # 纯跳转
    if intent.startswith("goto_"):
        page = intent.replace("goto_", "")
        link = _link(page)
        actions.append(link)
        return {
            "crm": {"intent": intent, "executed": False},
            "actions": actions,
            "summary": f"可前往：{link['label']}",
            "nav_links": actions,
        }

    extracted = _extract_crm_payload(text, intent)
    fields = extracted.get("fields") or {}

    if intent == "add_vendor":
        if not extracted.get("can_execute") or not fields.get("name"):
            actions.append(_link("vendors", "去厂商名录手动添加"))
            return {
                "crm": {"intent": intent, "executed": False, "missing": extracted.get("missing") or ["name"]},
                "actions": actions,
                "summary": "厂商信息不完整（至少需要厂名）。可补充后重说，或点链接去页面添加。",
                "nav_links": actions,
            }
        try:
            item = store.upsert_vendor(fields)
        except Exception as e:
            actions.append(_link("vendors"))
            return {
                "crm": {"intent": intent, "executed": False, "error": str(e)},
                "actions": actions,
                "summary": f"添加厂商失败：{e}",
                "nav_links": actions,
            }
        actions.append(_link("vendors", f"查看厂商 {item.get('name')}"))
        actions.append({"type": "created", "entity": "vendor", "id": item.get("id"), "name": item.get("name")})
        return {
            "crm": {"intent": intent, "executed": True, "item": item},
            "actions": actions,
            "summary": f"已添加厂商 {item.get('id')} · {item.get('name')}",
            "nav_links": [a for a in actions if a.get("type") == "link"],
            "vendor": item,
        }

    if intent == "add_customer":
        if not extracted.get("can_execute") or not fields.get("name"):
            actions.append(_link("customers", "去客户页手动添加"))
            return {
                "crm": {"intent": intent, "executed": False, "missing": extracted.get("missing") or ["name"]},
                "actions": actions,
                "summary": "客户信息不完整（至少需要客户名）。可补充后重说，或点链接去页面添加。",
                "nav_links": actions,
            }
        try:
            item = store.upsert_customer(fields)
        except Exception as e:
            actions.append(_link("customers"))
            return {
                "crm": {"intent": intent, "executed": False, "error": str(e)},
                "actions": actions,
                "summary": f"添加客户失败：{e}",
                "nav_links": actions,
            }
        actions.append(_link("customers", f"查看客户 {item.get('name')}"))
        actions.append({"type": "created", "entity": "customer", "id": item.get("id"), "name": item.get("name")})
        return {
            "crm": {"intent": intent, "executed": True, "item": item},
            "actions": actions,
            "summary": f"已添加客户 {item.get('id')} · {item.get('name')}",
            "nav_links": [a for a in actions if a.get("type") == "link"],
            "customer": item,
        }

    if intent == "add_followup":
        if not extracted.get("can_execute"):
            actions.append(_link("followups", "去跟进页手动添加"))
            return {
                "crm": {"intent": intent, "executed": False, "missing": extracted.get("missing") or []},
                "actions": actions,
                "summary": "跟进信息不完整。可补充客户/原因，或点链接去页面添加。",
                "nav_links": actions,
            }
        try:
            item = store.upsert_followup(fields)
        except Exception as e:
            actions.append(_link("followups"))
            return {
                "crm": {"intent": intent, "executed": False, "error": str(e)},
                "actions": actions,
                "summary": f"添加跟进失败：{e}",
                "nav_links": actions,
            }
        actions.append(_link("followups", "查看跟进待办"))
        actions.append({"type": "created", "entity": "followup", "id": item.get("id")})
        return {
            "crm": {"intent": intent, "executed": True, "item": item},
            "actions": actions,
            "summary": f"已添加跟进 {item.get('id')}",
            "nav_links": [a for a in actions if a.get("type") == "link"],
            "followup": item,
        }

    actions.append(_link("assistant"))
    return {
        "crm": {"intent": intent or "unknown", "executed": False},
        "actions": actions,
        "summary": "未识别到可执行的 CRM 操作。可说：添加厂商义乌XX，擅长保温杯",
        "nav_links": actions,
    }


def tool_suggest_nav(**payload: Any) -> dict[str, Any]:
    """只返回页面跳转建议。"""
    text = (payload.get("query") or payload.get("body") or "").strip()
    intent = _detect_intent(text)
    page = intent.replace("goto_", "") if intent.startswith("goto_") else "assistant"
    if intent.startswith("add_"):
        page = {"add_vendor": "vendors", "add_customer": "customers", "add_followup": "followups"}.get(intent, "assistant")
    link = _link(page)
    return {
        "actions": [link],
        "nav_links": [link],
        "summary": f"建议前往：{link['label']}",
    }
