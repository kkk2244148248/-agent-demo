"""扩充各领域 Agent 的工具：让 Agent 不只是 1～2 个薄封装。"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.prompts_registry import (
    KB_SEARCH_SYSTEM,
    TOOL_COST_ESTIMATE_SYSTEM,
    TOOL_DOC_GAP_SYSTEM,
    TOOL_EMAIL_TODOS_SYSTEM,
    TOOL_EXTRACT_QUOTE_FIELDS_SYSTEM,
    TOOL_FOLLOWUP_MAIL_SYSTEM,
    TOOL_POLISH_REPLY_SYSTEM,
    TOOL_SAMPLE_BRIEF_SYSTEM,
)
from backend.agents.tools.handlers import _ctx, _parse_json, tool_parse_requirement
from backend.config import get_settings
from backend.core.knowledge_base import get_knowledge_base
from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.services.store import _to_float, get_store

logger = get_logger(__name__)

_SAMPLE_FLOW = ["待打样", "打样中", "已寄出", "海外确认中", "已完成"]


def _today() -> date:
    return date.today()


def _parse_day(s: str) -> date | None:
    s = (s or "").strip()[:10]
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ─── 寻源 ─────────────────────────────────────────────


def tool_rank_vendors(**payload: Any) -> dict[str, Any]:
    """对候选厂商打分排序（MOQ/交期/风险/匹配分）。"""
    c = _ctx(payload)
    matched = (c["vendor_match"] or {}).get("matched_vendors") or []
    store_vendors = {v.get("id"): v for v in get_store().list_vendors(active_only=True)}
    req = c["requirement"] or {}
    want_qty = 0
    try:
        want_qty = int(re.sub(r"\D", "", str(req.get("quantity") or "0")) or 0)
    except Exception:
        want_qty = 0

    if not matched:
        # 无匹配结果时，用 query 从 CRM 厂商库粗筛
        q = (c["query"] or c["subject"] or "").lower()
        for v in store_vendors.values():
            blob = " ".join(
                [
                    str(v.get("name") or ""),
                    str(v.get("categories") or ""),
                    str(v.get("strengths") or ""),
                    str(v.get("region") or ""),
                ]
            ).lower()
            if q and any(tok in blob for tok in re.split(r"\s+", q) if len(tok) > 1):
                matched.append(
                    {
                        "vendor_id": v.get("id"),
                        "vendor_name": v.get("name"),
                        "match_score": 0.5,
                        "notes": v.get("memo") or "",
                    }
                )

    ranked: list[dict[str, Any]] = []
    for m in matched:
        vid = m.get("vendor_id") or ""
        sv = store_vendors.get(vid) or {}
        moq = 0
        lead = 30
        try:
            moq = int(m.get("moq") or sv.get("moq") or 0)
        except Exception:
            moq = 0
        try:
            lead = int(m.get("lead_time_days") or sv.get("lead_time_days") or 30)
        except Exception:
            lead = 30
        base = float(m.get("match_score") or m.get("score") or 0.6)
        score = base * 100
        reasons: list[str] = []
        if want_qty and moq and want_qty < moq:
            score -= 25
            reasons.append(f"数量{want_qty}<MOQ{moq}")
        else:
            reasons.append("MOQ可接受" if moq else "MOQ未标")
        if lead > 45:
            score -= 10
            reasons.append(f"交期偏长{lead}天")
        elif lead <= 25:
            score += 5
            reasons.append(f"交期快{lead}天")
        risk = str(m.get("risk") or sv.get("risk") or sv.get("notes") or "")
        if any(k in risk for k in ["投诉", "延期", "质量", "高风险"]):
            score -= 15
            reasons.append("存在风险备注")
        if sv.get("active") is False:
            score -= 40
            reasons.append("厂商已停用")
        ranked.append(
            {
                "vendor_id": vid,
                "vendor_name": m.get("vendor_name") or sv.get("name") or vid,
                "score": round(score, 1),
                "moq": moq,
                "lead_time_days": lead,
                "reasons": reasons,
                "region": sv.get("region") or m.get("region") or "",
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    shortlist = ranked[:3]
    return {
        "vendor_ranking": ranked,
        "vendor_shortlist": shortlist,
        "summary": f"已排序 {len(ranked)} 家，短名单 {len(shortlist)} 家",
    }


def tool_estimate_cost(**payload: Any) -> dict[str, Any]:
    """粗算参考成本/FOB 区间（基于比价或规则估算，非正式报价）。"""
    c = _ctx(payload)
    compare = c["compare"] or {}
    options = compare.get("options") or []
    req = c["requirement"] or {}
    qty = 0
    try:
        qty = int(re.sub(r"\D", "", str(req.get("quantity") or "0")) or 0)
    except Exception:
        qty = 0

    lines: list[dict[str, Any]] = []
    if options:
        for o in options[:5]:
            unit = float(o.get("ref_unit_price_foreign") or o.get("unit_price") or 0)
            unit_cny = float(o.get("ref_unit_price_cny") or 0)
            lines.append(
                {
                    "vendor_id": o.get("vendor_id"),
                    "vendor_name": o.get("vendor_name"),
                    "unit_price": unit,
                    "unit_price_cny": unit_cny,
                    "currency": o.get("foreign_currency") or "USD",
                    "qty": qty or None,
                    "ext_amount": round(unit * qty, 2) if qty and unit else None,
                    "note": "来自比价草案",
                }
            )
    else:
        # 无比价时用 LLM/规则给区间
        cat = str(req.get("category") or c["query"] or c["subject"] or "礼品")
        estimate = {
            "category": cat,
            "unit_price_low_usd": 1.2,
            "unit_price_high_usd": 4.5,
            "assumptions": ["无正式厂报，仅品类经验区间", "不含运费/关税/LOGO加价"],
        }
        if get_settings().use_real_llm:
            try:
                llm = get_llm("compare", temperature=0)
                resp = llm.invoke(
                    [
                        SystemMessage(
                            content=TOOL_COST_ESTIMATE_SYSTEM
                        ),
                        HumanMessage(
                            content=f"品类/需求：{json.dumps(req or {'q': cat}, ensure_ascii=False)}\n数量:{qty}"
                        ),
                    ]
                )
                data = _parse_json(getattr(resp, "content", "") or "")
                if data:
                    estimate.update(data)
            except Exception as e:
                logger.error(f"estimate_cost.llm err={e}")
        low = float(estimate.get("unit_price_low_usd") or 0)
        high = float(estimate.get("unit_price_high_usd") or 0)
        lines.append(
            {
                "vendor_name": "（未定点）",
                "unit_price_low": low,
                "unit_price_high": high,
                "currency": "USD",
                "qty": qty or None,
                "ext_low": round(low * qty, 2) if qty else None,
                "ext_high": round(high * qty, 2) if qty else None,
                "assumptions": estimate.get("assumptions") or [],
                "logo_extra_note": estimate.get("logo_extra_note") or "",
            }
        )

    return {
        "cost_estimate": {"lines": lines, "disclaimer": "仅供内部参考，非正式报价"},
        "summary": f"成本粗算 {len(lines)} 条",
    }


def tool_vendor_risk_check(**payload: Any) -> dict[str, Any]:
    """检查候选/指定厂商风险点（交期、认证缺口、历史备注）。"""
    c = _ctx(payload)
    vids: list[str] = []
    for m in (c["vendor_match"] or {}).get("matched_vendors") or []:
        if m.get("vendor_id"):
            vids.append(str(m["vendor_id"]))
    for o in (c["compare"] or {}).get("options") or []:
        if o.get("vendor_id"):
            vids.append(str(o["vendor_id"]))
    q = c["query"] or ""
    m = re.search(r"(V-[\w]+)", q)
    if m:
        vids.append(m.group(1))
    vids = list(dict.fromkeys(vids))
    store = get_store()
    req_cat = str((c["requirement"] or {}).get("category") or "").lower()
    reports: list[dict[str, Any]] = []
    for vid in vids[:8]:
        v = store.get_vendor(vid) or {}
        if not v:
            reports.append({"vendor_id": vid, "level": "unknown", "issues": ["厂商库无此 ID"]})
            continue
        issues: list[str] = []
        level = "low"
        if not v.get("active", True):
            issues.append("已停用")
            level = "high"
        notes = str(v.get("notes") or v.get("memo") or "")
        if any(k in notes for k in ["延期", "投诉", "质量", "欠款"]):
            issues.append(f"备注风险：{notes[:60]}")
            level = "high" if level != "high" else level
        certs = str(v.get("certs") or v.get("certifications") or "")
        if any(k in req_cat for k in ["电池", "充电宝", "数码"]) and not any(
            x in certs.upper() for x in ["CE", "FCC", "UN38", "ROHS"]
        ):
            issues.append("数码/电池类缺少常见认证字段")
            level = "medium" if level == "low" else level
        if not issues:
            issues.append("未见明显风险标记")
        reports.append(
            {
                "vendor_id": vid,
                "vendor_name": v.get("name"),
                "level": level,
                "issues": issues,
                "region": v.get("region"),
            }
        )
    if not reports:
        return {
            "risk_report": [],
            "summary": "没有可检查的厂商。请先找厂/比价，或在话里带厂商 ID。",
        }
    high = sum(1 for r in reports if r["level"] == "high")
    return {
        "risk_report": reports,
        "summary": f"风险检查 {len(reports)} 家，高风险 {high} 家",
    }


# ─── 沟通 ─────────────────────────────────────────────


def tool_polish_reply(**payload: Any) -> dict[str, Any]:
    """润色已有海外回复：更短/更正式/更强硬。"""
    c = _ctx(payload)
    draft = c.get("reply_draft") or (payload.get("pipeline") or {}).get("reply_draft") or ""
    if not draft:
        # 没有草稿则先提示
        return {
            "reply_draft": "",
            "summary": "没有可润色的 reply_draft，请先生成海外回复。",
            "error": "missing_reply_draft",
        }
    tone = "professional"
    g = (c["query"] or "").lower()
    if any(k in g for k in ["短", "简洁", "brief"]):
        tone = "concise"
    elif any(k in g for k in ["强硬", "催", "urgent"]):
        tone = "firm"
    elif any(k in g for k in ["软", "客气", "友好"]):
        tone = "friendly"

    llm = get_llm("reply", temperature=0.3)
    resp = llm.invoke(
        [
            SystemMessage(
                content=TOOL_POLISH_REPLY_SYSTEM.format(tone=tone)
            ),
            HumanMessage(content=draft),
        ]
    )
    text = (getattr(resp, "content", None) or str(resp)).strip()
    return {
        "reply_draft": text,
        "reply_polish_meta": {"tone": tone},
        "summary": f"已按「{tone}」润色海外回复",
    }


def tool_extract_email_todos(**payload: Any) -> dict[str, Any]:
    """从询盘/邮件正文抽取待办与风险点。"""
    c = _ctx(payload)
    text = f"{c['subject']}\n{c['body']}\n{c['query']}".strip()
    if len(text) < 8:
        return {"email_todos": [], "summary": "正文太短，无法抽取待办"}

    todos: list[dict[str, Any]] = []
    if get_settings().use_real_llm:
        try:
            llm = get_llm("intent", temperature=0)
            resp = llm.invoke(
                [
                    SystemMessage(
                        content=TOOL_EMAIL_TODOS_SYSTEM
                    ),
                    HumanMessage(content=text[:3000]),
                ]
            )
            data = _parse_json(getattr(resp, "content", "") or "")
            todos = data.get("todos") or []
            return {
                "email_todos": todos,
                "email_risks": data.get("risks") or [],
                "deadline_hints": data.get("deadline_hints") or [],
                "summary": f"抽出待办 {len(todos)} 条",
            }
        except Exception as e:
            logger.error(f"extract_email_todos.llm err={e}")

    # 规则兜底
    for line in text.splitlines():
        line = line.strip()
        if any(k in line.lower() for k in ["please", "need", "asap", "请", "需要", "尽快", "确认"]):
            todos.append({"task": line[:120], "owner": "我方", "priority": "medium"})
    return {"email_todos": todos[:10], "summary": f"规则抽出待办 {len(todos[:10])} 条"}


def tool_draft_followup_mail(**payload: Any) -> dict[str, Any]:
    """客户未回复时的跟催邮件草稿。"""
    c = _ctx(payload)
    llm = get_llm("reply", temperature=0.3)
    prompt = (
        f"公司:{get_settings().company_name}\n客户:{c['customer_name']} / {c['country']}\n"
        f"原主题:{c['subject']}\n原需求摘要:{json.dumps(c['requirement'] or {}, ensure_ascii=False)[:800]}\n"
        f"上次方案摘要:{json.dumps(c['compare'] or {}, ensure_ascii=False)[:800]}\n"
        "请写一封简短专业的英文跟催邮件（可中英双语），催确认数量/交期/LOGO，不要施压过度。"
    )
    resp = llm.invoke(
        [
            SystemMessage(content=TOOL_FOLLOWUP_MAIL_SYSTEM),
            HumanMessage(content=prompt),
        ]
    )
    text = (getattr(resp, "content", None) or str(resp)).strip()
    return {"followup_mail_draft": text, "reply_draft": text, "summary": "已生成跟催邮件草稿"}


# ─── 样品 ─────────────────────────────────────────────


def tool_sample_overdue(**payload: Any) -> dict[str, Any]:
    """列出 ETA 已过且未完成的样品。"""
    items = get_store().list_samples()
    today = _today()
    overdue = []
    for s in items:
        st = str(s.get("status") or "")
        if st in ("已完成", "取消", "已取消"):
            continue
        eta = _parse_day(str(s.get("eta") or ""))
        if eta and eta < today:
            overdue.append({**s, "overdue_days": (today - eta).days})
    overdue.sort(key=lambda x: x.get("overdue_days") or 0, reverse=True)
    return {
        "samples_overdue": overdue,
        "samples": overdue,
        "summary": f"逾期样品 {len(overdue)} 条",
    }


def tool_advance_sample_status(**payload: Any) -> dict[str, Any]:
    """按标准流程推进样品状态；可指定 sample_id 与目标 status。"""
    sid = (payload.get("sample_id") or payload.get("id") or "").strip()
    target = (payload.get("status") or "").strip()
    store = get_store()
    items = store.list_samples()
    if not sid and items:
        # 取最近一条未完成
        for s in items:
            if str(s.get("status") or "") not in ("已完成", "取消", "已取消"):
                sid = s.get("id") or ""
                break
    cur = next((s for s in items if s.get("id") == sid), None)
    if not cur:
        return {"summary": "未找到样品，请提供 sample_id", "error": "missing_sample"}

    cur_status = str(cur.get("status") or "待打样")
    if target:
        new_status = target
    else:
        if cur_status in _SAMPLE_FLOW:
            idx = _SAMPLE_FLOW.index(cur_status)
            new_status = _SAMPLE_FLOW[min(idx + 1, len(_SAMPLE_FLOW) - 1)]
        else:
            new_status = "打样中"

    updated = store.upsert_sample({**cur, "status": new_status})
    return {
        "sample": updated,
        "sample_status_change": {"from": cur_status, "to": new_status},
        "summary": f"样品 {sid}：{cur_status} → {new_status}",
    }


def tool_sample_brief(**payload: Any) -> dict[str, Any]:
    """生成给工厂的打样要求简报（中文）。"""
    c = _ctx(payload)
    sample = payload.get("sample") or {}
    llm = get_llm("factory_brief", temperature=0.2)
    prompt = (
        f"需求:{json.dumps(c['requirement'] or {}, ensure_ascii=False)}\n"
        f"样品字段:{json.dumps(sample or {k: payload.get(k) for k in ['product','color','material','size_spec','logo_process','sample_qty']}, ensure_ascii=False)}\n"
        f"客户:{c['customer_name']}\n请输出给工厂的打样简报（要点列表）。"
    )
    resp = llm.invoke(
        [
            SystemMessage(content=TOOL_SAMPLE_BRIEF_SYSTEM),
            HumanMessage(content=prompt),
        ]
    )
    text = (getattr(resp, "content", None) or str(resp)).strip()
    return {"sample_brief": text, "factory_brief": text, "summary": "已生成打样简报"}


# ─── 合规 ─────────────────────────────────────────────


_MARKET_PACKS: dict[str, list[str]] = {
    "us": ["商业发票", "装箱单", "PO/合同", "FDA(食品接触如适用)", "CPC/CPSIA(儿童如适用)", "FCC(电子)"],
    "eu": ["商业发票", "装箱单", "CE", "RoHS", "REACH", "包装法注册(如适用)"],
    "uk": ["商业发票", "装箱单", "UKCA", "RoHS"],
    "au": ["商业发票", "装箱单", "RCM(电子如适用)"],
    "jp": ["商业发票", "装箱单", "PSE(电器如适用)", "食品接触标准(如适用)"],
    "default": ["商业发票", "装箱单", "合同/PO", "按目的国补充认证"],
}


def tool_market_cert_pack(**payload: Any) -> dict[str, Any]:
    """按目的市场给出认证/单证包。"""
    c = _ctx(payload)
    country = (c["country"] or c["query"] or "").lower()
    key = "default"
    if any(k in country for k in ["美", "usa", "united states", "us"]):
        key = "us"
    elif any(k in country for k in ["英", "uk", "britain"]):
        key = "uk"
    elif any(k in country for k in ["欧", "德", "法", "意", "西", "eu", "europe", "germany", "france"]):
        key = "eu"
    elif any(k in country for k in ["澳", "au", "australia"]):
        key = "au"
    elif any(k in country for k in ["日", "japan", "jp"]):
        key = "jp"
    pack = list(_MARKET_PACKS[key])
    # 合并品类清单
    from backend.agents.tools.handlers import tool_cert_checklist

    cat = tool_cert_checklist(**payload)
    merged = list(dict.fromkeys(pack + list(cat.get("checklist") or [])))
    return {
        "market": key,
        "market_cert_pack": merged,
        "checklist": merged,
        "summary": f"目的市场「{key}」认证/单证 {len(merged)} 项",
    }


def tool_claim_risk_check(**payload: Any) -> dict[str, Any]:
    """检查宣传用语风险（再生、可降解、医疗等）。"""
    c = _ctx(payload)
    text = f"{c['subject']}\n{c['body']}\n{c['query']}\n{json.dumps(c['requirement'] or {}, ensure_ascii=False)}"
    risks: list[dict[str, str]] = []
    rules = [
        (r"可降解|biodegradable", "可降解宣称需测试报告，否则易被打假"),
        (r"再生|recycle|GRS|RPET", "再生料宣称建议备 GRS/链式证明"),
        (r"抗菌|医疗|医用", "医疗/抗菌宣称监管严格，礼品场景慎用"),
        (r"FDA认证|已认证FDA", "食品接触材料≠FDA认证产品，措辞需谨慎"),
        (r"绝对|第一|最好|100%", "绝对化用语广告法/海外广告风险"),
    ]
    for pat, msg in rules:
        if re.search(pat, text, re.I):
            risks.append({"pattern": pat, "risk": msg, "level": "medium"})
    return {
        "claim_risks": risks,
        "summary": f"宣传风险点 {len(risks)} 条" if risks else "未发现高风险宣传措辞",
    }


def tool_shipping_doc_checklist(**payload: Any) -> dict[str, Any]:
    """出货单证清单（发票/箱单/产地证等）。"""
    c = _ctx(payload)
    base = ["商业发票 Commercial Invoice", "装箱单 Packing List", "合同/PO", "提单/运单草稿核对"]
    extra: list[str] = []
    country = (c["country"] or "").lower()
    if any(k in country for k in ["美", "欧", "英", "澳"]):
        extra.append("产地证/声明（客户若要求）")
    if "海" in (c["query"] or "") or "fob" in (c["query"] or "").lower():
        extra.append("FOB 装运港与截关日确认")
    items = base + extra
    return {"shipping_docs": items, "checklist": items, "summary": f"出货单证 {len(items)} 项"}


# ─── 文档 ─────────────────────────────────────────────


def tool_extract_quote_fields(**payload: Any) -> dict[str, Any]:
    """从已解析文档中抽取报价字段（单价/MOQ/交期）。"""
    pipe = payload.get("pipeline") or {}
    doc = payload.get("document") or pipe.get("document") or {}
    text = (
        payload.get("document_text")
        or pipe.get("document_text")
        or doc.get("text")
        or ""
    )
    if not text and not doc:
        # 若有路径先解析
        path = payload.get("file_path") or (doc.get("file_path") if isinstance(doc, dict) else "") or ""
        if path:
            from backend.agents.tools.handlers import tool_parse_document

            parsed = tool_parse_document(**payload)
            text = parsed.get("document_text") or ""
            doc = parsed.get("document") or {}
            pipe_extra = parsed
        else:
            return {"summary": "请先上传并识别文档", "error": "missing_document", "quote_fields": {}}
    else:
        pipe_extra = {}

    fields: dict[str, Any] = {}
    if get_settings().use_real_llm and text:
        try:
            llm = get_llm("requirement", temperature=0)
            resp = llm.invoke(
                [
                    SystemMessage(
                        content=TOOL_EXTRACT_QUOTE_FIELDS_SYSTEM
                    ),
                    HumanMessage(content=text[:6000]),
                ]
            )
            fields = _parse_json(getattr(resp, "content", "") or "") or {}
        except Exception as e:
            logger.error(f"extract_quote_fields.llm err={e}")

    if not fields:
        # 正则兜底
        m = re.search(r"(?:单价|unit\s*price|price)[^\d]{0,8}(\d+(?:\.\d+)?)", text, re.I)
        if m:
            fields["unit_price"] = float(m.group(1))
        m2 = re.search(r"(?:MOQ|起订)[^\d]{0,8}(\d+)", text, re.I)
        if m2:
            fields["moq"] = int(m2.group(1))
        m3 = re.search(r"(?:交期|lead\s*time)[^\d]{0,8}(\d+)\s*天", text, re.I)
        if m3:
            fields["lead_time_days"] = int(m3.group(1))

    out = {
        "quote_fields": fields,
        "document_fields": {**(doc.get("structured") or {}), **fields},
        "summary": f"已抽取报价字段 {len(fields)} 项" if fields else "未抽到明确报价字段",
    }
    out.update({k: v for k, v in pipe_extra.items() if k.startswith("document")})
    return out


def tool_doc_vs_requirement(**payload: Any) -> dict[str, Any]:
    """对比文档内容与需求缺口。"""
    c = _ctx(payload)
    pipe = payload.get("pipeline") or {}
    text = payload.get("document_text") or pipe.get("document_text") or ""
    req = c["requirement"] or {}
    if not req and (c["subject"] or c["body"]):
        # 尝试先解析需求
        try:
            pr = tool_parse_requirement(**payload)
            req = pr.get("requirement") or {}
        except Exception:
            req = {}
    if not text:
        return {"summary": "缺少文档文本，请先 parse_document", "error": "missing_document", "gaps": []}

    gaps: list[str] = []
    checks = [
        ("quantity", "数量/Quantity"),
        ("category", "品类"),
        ("logo", "LOGO/印刷"),
        ("color", "颜色"),
        ("deadline", "交期"),
    ]
    blob = text.lower()
    for key, label in checks:
        val = str((req or {}).get(key) or (req or {}).get("product_summary") or "")
        if key == "logo" and not val:
            val = str((req or {}).get("logo_requirement") or "")
        if val and str(val).lower()[:12] not in blob and label.lower() not in blob:
            # soft check
            if key in ("quantity",) and not re.search(r"\b\d{2,}\b", text):
                gaps.append(f"文档可能缺少：{label}")
            elif key != "quantity":
                gaps.append(f"需求有「{label}」但文档未明显体现")

    if get_settings().use_real_llm:
        try:
            llm = get_llm("intent", temperature=0)
            resp = llm.invoke(
                [
                    SystemMessage(
                        content=TOOL_DOC_GAP_SYSTEM
                    ),
                    HumanMessage(
                        content=f"需求:{json.dumps(req, ensure_ascii=False)}\n文档:\n{text[:4000]}"
                    ),
                ]
            )
            data = _parse_json(getattr(resp, "content", "") or "")
            if data.get("gaps"):
                gaps = list(dict.fromkeys(gaps + list(data["gaps"])))
            return {
                "doc_gap_analysis": data,
                "gaps": gaps,
                "summary": f"缺口 {len(gaps)} 项",
            }
        except Exception as e:
            logger.error(f"doc_vs_requirement.llm err={e}")

    return {"gaps": gaps, "summary": f"缺口 {len(gaps)} 项（规则）"}


# ─── CRM ─────────────────────────────────────────────


def tool_search_crm(**payload: Any) -> dict[str, Any]:
    """搜索客户/厂商档案。"""
    q = (payload.get("query") or payload.get("body") or "").strip().lower()
    store = get_store()
    customers = []
    vendors = []
    for c in store.list_customers():
        blob = " ".join(str(c.get(k) or "") for k in ("id", "name", "country", "contact", "email", "tags")).lower()
        if not q or q in blob:
            customers.append(c)
    for v in store.list_vendors():
        blob = " ".join(
            str(v.get(k) or "") for k in ("id", "name", "region", "contact", "categories", "strengths")
        ).lower()
        if not q or any(tok in blob for tok in re.split(r"\s+", q) if tok):
            vendors.append(v)
    return {
        "crm_customers": customers[:20],
        "crm_vendors": vendors[:20],
        "summary": f"客户命中 {len(customers[:20])} · 厂商命中 {len(vendors[:20])}",
    }


def tool_customer_360(**payload: Any) -> dict[str, Any]:
    """客户 360：关联询盘/报价/订单/跟进。"""
    c = _ctx(payload)
    store = get_store()
    name = (payload.get("customer_name") or c["customer_name"] or "").strip()
    cid = (payload.get("customer_id") or "").strip()
    if not name and not cid and c["query"]:
        # 尝试从 CRM 搜
        for cust in store.list_customers():
            if cust.get("name") and cust["name"] in c["query"]:
                name = cust["name"]
                cid = cust.get("id") or ""
                break
    if not name and not cid:
        return {"summary": "请提供客户名或 customer_id", "error": "missing_customer"}
    related = store.related_for_customer(customer_id=cid, customer_name=name)
    return {
        "customer_360": related,
        "summary": f"客户「{name or cid}」关联数据已汇总",
        "actions": [
            {
                "type": "link",
                "page": "customers",
                "path": "/customers",
                "label": f"打开客户 {name or cid}",
            }
        ],
        "nav_links": [
            {
                "type": "link",
                "page": "customers",
                "path": "/customers",
                "label": f"打开客户 {name or cid}",
            }
        ],
    }


def tool_list_overdue_followups(**payload: Any) -> dict[str, Any]:
    """列出逾期跟进。"""
    dash = get_store().dashboard()
    items = dash.get("overdue_followup_items") or []
    return {
        "overdue_followups": items,
        "summary": f"逾期跟进 {len(items)} 条",
        "actions": [
            {"type": "link", "page": "followups", "path": "/followups", "label": "打开跟进页"}
        ],
        "nav_links": [
            {"type": "link", "page": "followups", "path": "/followups", "label": "打开跟进页"}
        ],
    }


# ─── 知识（让 knowledge_agent 也有真工具）────────────────


def tool_kb_search(**payload: Any) -> dict[str, Any]:
    """知识库检索（给 knowledge_agent 用）。"""
    c = _ctx(payload)
    q = (c["query"] or c["subject"] or payload.get("question") or "").strip()
    if not q:
        return {"summary": "请输入检索问题", "kb_hits": []}
    kb = get_knowledge_base()
    if not kb.ready:
        try:
            kb.build()
        except Exception as e:
            return {"summary": f"知识库未就绪：{e}", "kb_hits": [], "error": str(e)}
    hits = kb.search(q, top_k=int(payload.get("top_k") or 4))
    context = kb.format_context(q, top_k=int(payload.get("top_k") or 4))
    answer = ""
    if get_settings().use_real_llm and context:
        try:
            llm = get_llm("summarize", temperature=0.2)
            resp = llm.invoke(
                [
                    SystemMessage(content=KB_SEARCH_SYSTEM),
                    HumanMessage(content=f"问题：{q}\n\n资料：\n{context}"),
                ]
            )
            answer = (getattr(resp, "content", None) or "").strip()
        except Exception as e:
            logger.error(f"kb_search.llm err={e}")
            answer = context[:800]
    else:
        answer = context[:800] if context else "未检索到相关资料。"
    return {
        "kb_hits": [
            {"source_name": h.source_name, "score": getattr(h, "score", None), "content": h.content[:400]}
            for h in hits
        ],
        "retrieved_context": context,
        "kb_answer": answer,
        "summary": f"知识检索 {len(hits)} 条",
    }


def tool_faq_lookup(**payload: Any) -> dict[str, Any]:
    """FAQ/BM25 快查。"""
    c = _ctx(payload)
    q = (c["query"] or payload.get("question") or "").strip()
    if not q:
        return {"summary": "请输入问题", "faq_hit": None}
    try:
        from backend.services.faq_mysql import get_faq_store

        faq = get_faq_store()
        if not faq.ready:
            faq.reload()
        hit = faq.best_above_threshold(q) if faq.ready else None
        if not hit:
            # 尝试任意 best
            hit = None
            if hasattr(faq, "search"):
                rows = faq.search(q, top_k=1) if faq.ready else []
                hit = rows[0] if rows else None
        if hit:
            return {
                "faq_hit": {
                    "id": getattr(hit, "id", None),
                    "question": getattr(hit, "question", None),
                    "answer": getattr(hit, "answer", None),
                    "confidence": getattr(hit, "confidence", None),
                },
                "kb_answer": getattr(hit, "answer", ""),
                "summary": "FAQ 命中",
            }
    except Exception as e:
        logger.error(f"faq_lookup err={e}")
    return {"faq_hit": None, "summary": "FAQ 未命中，可再走 kb_search"}


# ═══════════════════════════════════════════════════════════════
# 钱账链路：利润核算 Agent
# ═══════════════════════════════════════════════════════════════

# 成本科目模板（缺项须由调用方补齐，不得默认 0 蒙混）
_COST_ITEMS = [
    "工厂采购价", "LOGO/印刷", "内陆运费/拖车", "报关/单证/商检",
    "港杂/THC", "海运费", "保险", "佣金/中间费", "其他",
]

# 公司毛利红线（低于此值需谨慎/不可接）
MARGIN_FLOOR_POLICY = 0.12


def _find_order_or_quotation(key: str) -> dict[str, Any]:
    """按 ID 在订单/报价里找一条记录。"""
    store = get_store()
    if not key:
        return {}
    for o in store.list_orders():
        if str(o.get("id")) == key:
            return {"kind": "order", "item": o}
    for q in store.list_quotations():
        if str(q.get("id")) == key:
            return {"kind": "quotation", "item": q}
    return {}


def _extract_ref_id(text: str) -> str:
    """从自然语言里提取订单/报价编号，如 PO-1D01C6 / QT-546467。"""
    m = re.search(r"(PO-[A-Za-z0-9]+|QT-[A-Za-z0-9]+)", str(text or ""))
    return m.group(1) if m else ""


def _recent_order() -> dict[str, Any]:
    """取最近更新的一条订单，作为未指明编号时的兜底。"""
    orders = get_store().list_orders()
    if not orders:
        return {}
    orders.sort(key=lambda o: str(o.get("updated_at") or ""), reverse=True)
    return orders[0]


def tool_profit_calc(**payload: Any) -> dict[str, Any]:
    """真实毛利测算：收入 - 全成本 + 退税，考虑汇率。"""
    c = _ctx(payload)
    key = str(payload.get("order_id") or payload.get("quotation_id") or "").strip()
    # 未显式给编号时，尝试从用户的自然语言里提取，最后兜底取最近订单
    if not key:
        key = _extract_ref_id(payload.get("query") or c.get("query") or c.get("body") or "")
    found = _find_order_or_quotation(key)
    if not found:
        recent = _recent_order()
        if recent:
            key = str(recent.get("id") or "")
            found = {"kind": "order", "item": recent}
    item = found.get("item") or {}
    kind = found.get("kind") or ""

    # 收入
    currency = str(item.get("currency") or payload.get("currency") or "USD")
    unit_price = _to_float(item.get("unit_price") or payload.get("unit_price"))
    qty = _to_float(item.get("qty") or payload.get("qty"))
    if not unit_price:
        revenue_amount = _to_float(item.get("total_amount") or item.get("total") or payload.get("revenue"))
    else:
        revenue_amount = round(unit_price * qty, 2) if qty else 0.0

    # 成本输入：支持 payload.costs 字典，或从 order/quotation 的 cost_price
    # costs 里若已给「总额」按总额计；成本项默认按总额口径理解，避免误乘数量。
    costs_in = payload.get("costs") if isinstance(payload.get("costs"), dict) else {}
    fx = _to_float(payload.get("fx_rate")) or 7.2
    stress = round(fx * 0.97, 3)  # 假设人民币升值 3%

    lines: list[dict[str, Any]] = []
    total_cost = 0.0
    missing: list[str] = []

    # 工厂采购价（单位价 × 数量）
    factory_unit = _to_float(
        costs_in.get("工厂采购价")
        or item.get("cost_price")
        or payload.get("cost_price")
    )
    if factory_unit:
        amt = round(factory_unit * qty, 2) if qty else factory_unit
        lines.append({"item": "工厂采购价", "unit": factory_unit, "amount": amt, "note": "须注明含税/不含税"})
        total_cost += amt
    else:
        missing.append("工厂采购价")

    for name in _COST_ITEMS[1:]:
        v = _to_float(costs_in.get(name))
        if v:
            # 约定：除工厂采购价外，其余科目按「该订单总额」口径传入
            lines.append({"item": name, "unit": v, "amount": v, "note": "按订单总额口径"})
            total_cost += v
        elif name in ("海运费", "保险"):
            missing.append(name)

    # 退税
    rebate_rate = _to_float(payload.get("rebate_rate"))
    rebate_amount = round(factory_unit * qty * rebate_rate, 2) if (factory_unit and qty and rebate_rate) else 0.0
    if not rebate_rate:
        missing.append("退税率")

    gross = round(revenue_amount - total_cost + rebate_amount, 2)
    margin = round(gross / revenue_amount, 4) if revenue_amount else 0.0
    # 缺关键成本项时，毛利数据不可信，不得给出正向判定
    critical_missing = [x for x in missing if x in ("工厂采购价", "退税率")]
    if critical_missing:
        margin = 0.0 if not factory_unit else margin
    # 汇率压力测试：收入按人民币计价的部分受汇率影响
    fx_loss = round(revenue_amount * (1 - stress / fx), 2) if revenue_amount else 0.0
    margin_stress = round((gross - fx_loss) / revenue_amount, 4) if revenue_amount else 0.0
    if critical_missing:
        margin_stress = 0.0 if not factory_unit else margin_stress
    breakeven = round((total_cost - rebate_amount) / qty, 2) if qty else 0.0
    suggested_floor = round(breakeven / (1 - MARGIN_FLOOR_POLICY), 2) if breakeven else 0.0

    verdict = "可接"
    if not revenue_amount or critical_missing:
        verdict = "谨慎"
    elif margin < MARGIN_FLOOR_POLICY:
        verdict = "不可接"
    elif margin < MARGIN_FLOOR_POLICY + 0.03:
        verdict = "谨慎"

    risk_flags: list[str] = []
    if missing:
        risk_flags.append("缺成本项：" + "、".join(missing[:6]))
    if margin_stress < MARGIN_FLOOR_POLICY and revenue_amount:
        risk_flags.append(f"汇率贬至 {stress} 后毛利降至 {margin_stress:.2%}，跌破红线")
    if rebate_amount and not rebate_rate:
        risk_flags.append("退税率未核实")

    return {
        "profit": {
            "currency": currency,
            "qty": qty or None,
            "revenue": {"unit_price": unit_price or None, "amount": revenue_amount},
            "cost_breakdown": lines,
            "total_cost": total_cost,
            "export_rebate": {"rate": rebate_rate, "amount": rebate_amount},
            "fx": {"assumed_rate": fx, "stress_rate": stress, "fx_loss": fx_loss},
            "gross_profit": gross,
            "gross_margin": margin,
            "net_margin_after_fx": margin_stress,
            "breakeven_price": breakeven,
            "floor_advice": {
                "suggested_floor": suggested_floor,
                "reason": f"盈亏平衡 {breakeven} + 公司毛利红线 {MARGIN_FLOOR_POLICY:.0%}",
            },
            "risk_flags": risk_flags,
            "verdict": verdict,
            "next_actions": [f"补全成本项：{x}" for x in missing[:5]] or ["可推进报价，注意锁定汇率"],
        },
        "cost_estimate": {"lines": lines, "disclaimer": "按真实成本口径测算，非正式报价"},
        "summary": (
            f"{key or '该单'}：收入 {revenue_amount} {currency}，"
            f"成本 {total_cost}，退税 {rebate_amount}，"
            f"毛利 {gross}（{margin:.2%}），判定「{verdict}」"
        ),
        "actions": [
            {"type": "link", "path": "/quotations", "label": "打开报价单"},
            {"type": "link", "path": "/collections", "label": "打开收款看板"},
        ],
    }


def tool_margin_check(**payload: Any) -> dict[str, Any]:
    """只判毛利是否达标，快速给结论。"""
    result = tool_profit_calc(**payload)
    p = result.get("profit") or {}
    margin = p.get("gross_margin") or 0.0
    ok = margin >= MARGIN_FLOOR_POLICY
    return {
        "margin_check": {
            "gross_margin": margin,
            "floor": MARGIN_FLOOR_POLICY,
            "pass": ok,
            "level": "达标" if ok else ("临界" if margin > 0 else "亏损"),
        },
        "summary": (
            f"毛利率 {margin:.2%}，" + ("达到" if ok else "低于") + f"公司红线 {MARGIN_FLOOR_POLICY:.0%}"
        ),
        "profit": p,
    }


def tool_rebate_estimate(**payload: Any) -> dict[str, Any]:
    """估算出口退税金额。"""
    factory_amount = _to_float(payload.get("factory_amount") or payload.get("amount"))
    rate = _to_float(payload.get("rebate_rate"))
    if not factory_amount:
        return {
            "rebate": {"rate": rate, "amount": 0.0, "note": "缺少采购金额，无法计算"},
            "summary": "缺少采购金额",
            "error": "missing_amount",
        }
    amount = round(factory_amount * rate, 2) if rate else 0.0
    note = "退税率待核" if not rate else f"按 {rate:.2%} 计算，基数为含税采购额"
    return {
        "rebate": {"rate": rate, "base": factory_amount, "amount": amount, "note": note},
        "summary": f"退税约 {amount}（税率 {rate:.2%}）" if rate else "退税率未提供，需核实",
    }


def tool_fx_stress_test(**payload: Any) -> dict[str, Any]:
    """汇率压力测试：人民币升值若干个百分点后毛利变化。"""
    amount = _to_float(payload.get("amount") or payload.get("revenue"))
    cost = _to_float(payload.get("cost"))
    base = _to_float(payload.get("fx_rate")) or 7.2
    shock_pct = _to_float(payload.get("shock_pct")) or 0.03
    if not amount:
        return {"fx": {"assumed_rate": base, "note": "缺少金额"}, "summary": "缺少金额", "error": "missing_amount"}
    stressed = round(base * (1 - shock_pct), 3)
    loss = round(amount * (1 - stressed / base), 2)
    base_margin = round((amount - cost) / amount, 4) if amount and cost else 0.0
    new_margin = round((amount - loss - cost) / amount, 4) if amount else 0.0
    return {
        "fx": {
            "assumed_rate": base,
            "stress_rate": stressed,
            "shock_pct": shock_pct,
            "fx_loss": loss,
            "margin_before": base_margin,
            "margin_after": new_margin,
        },
        "summary": f"汇率 {base} → {stressed} 时，毛利由 {base_margin:.2%} 变为 {new_margin:.2%}",
    }


def tool_quote_price_suggest(**payload: Any) -> dict[str, Any]:
    """基于成本与目标毛利，给出建议对外报价区间与底价。"""
    cost_unit = _to_float(payload.get("cost_unit") or payload.get("cost_price"))
    if not cost_unit:
        return {"price_suggest": {}, "summary": "缺少单位成本", "error": "missing_cost"}
    target_low = _to_float(payload.get("target_margin_low")) or MARGIN_FLOOR_POLICY
    target_high = _to_float(payload.get("target_margin_high")) or 0.22
    floor = round(cost_unit / (1 - target_low), 2)
    good = round(cost_unit / (1 - target_high), 2)
    return {
        "price_suggest": {
            "cost_unit": cost_unit,
            "floor_price": floor,
            "suggest_low": floor,
            "suggest_high": good,
            "target_margin_low": target_low,
            "target_margin_high": target_high,
            "note": "对外报价须经人工核定；此区间按成本加成法推算",
        },
        "summary": f"建议报价 {floor} ~ {good}，底价不低于 {floor}",
    }


# ═══════════════════════════════════════════════════════════════
# 报价守门 Agent
# ═══════════════════════════════════════════════════════════════

def tool_floor_price_check(**payload: Any) -> dict[str, Any]:
    """校验报价明细是否低于底价红线。"""
    c = _ctx(payload)
    key = str(payload.get("quotation_id") or payload.get("order_id") or "").strip()
    if not key:
        key = _extract_ref_id(payload.get("query") or c.get("query") or c.get("body") or "")
    found = _find_order_or_quotation(key)
    item = found.get("item") or {}
    floor = _to_float(item.get("floor_price") or payload.get("floor_price"))
    price = _to_float(item.get("total") or payload.get("price"))
    below = bool(item.get("below_floor"))
    if floor and price:
        below = price < floor
    return {
        "floor_check": {
            "quotation_id": key,
            "floor_price": floor or None,
            "quoted_price": price or None,
            "below_floor": below,
            "boss_approved": bool(item.get("boss_approved")),
            "verdict": "低于底价，需特批" if below else "在底价之上，可正常报出",
        },
        "summary": (
            f"报价 {price or '-'} vs 底价 {floor or '-'}："
            + ("低于红线，需走特批" if below else "未触红线")
        ),
        "actions": [{"type": "link", "path": "/quotations", "label": "打开报价单"}],
    }


def tool_quote_version_diff(**payload: Any) -> dict[str, Any]:
    """对比报价的历史版本，看每版改了什么。"""
    c = _ctx(payload)
    key = str(payload.get("quotation_id") or "").strip()
    if not key:
        key = _extract_ref_id(payload.get("query") or c.get("query") or c.get("body") or "")
    found = _find_order_or_quotation(key)
    item = found.get("item") or {}
    versions = item.get("versions") or []
    current = {
        "version": item.get("version") or 1,
        "total": item.get("total"),
        "lines": item.get("lines") or [],
        "updated_at": item.get("updated_at"),
    }
    history = [
        {"version": v.get("version"), "total": v.get("total"), "updated_at": v.get("updated_at"), "note": v.get("note")}
        for v in versions
    ]
    return {
        "version_diff": {"quotation_id": key, "current": current, "history": history, "count": len(history) + 1},
        "summary": f"{key}：当前 v{current['version']}，共 {len(history) + 1} 个版本",
        "actions": [{"type": "link", "path": "/quotations", "label": "打开报价单"}],
    }


def tool_below_floor_review(**payload: Any) -> dict[str, Any]:
    """列出所有低于底价、待特批的报价。"""
    store = get_store()
    rows = []
    for q in store.list_quotations():
        if q.get("below_floor") and not q.get("boss_approved"):
            rows.append({
                "quotation_id": q.get("id"),
                "customer_name": q.get("customer_name"),
                "total": q.get("total"),
                "floor_price": q.get("floor_price"),
                "below_floor": True,
            })
    return {
        "below_floor_review": rows,
        "summary": f"待特批报价 {len(rows)} 条",
        "actions": [{"type": "link", "path": "/quotations", "label": "打开报价单"}],
    }


def tool_lost_deal_analysis(**payload: Any) -> dict[str, Any]:
    """统计丢单原因分布。"""
    store = get_store()
    counter: dict[str, int] = {}
    rows = []
    for q in store.list_quotations():
        if str(q.get("status") or "").lower() in ("lost", "已丢单", "丢单"):
            reason = str(q.get("lost_reason") or "未填写")
            counter[reason] = counter.get(reason, 0) + 1
            rows.append({"quotation_id": q.get("id"), "customer_name": q.get("customer_name"), "lost_reason": reason})
    return {
        "lost_deals": {"rows": rows, "by_reason": counter, "count": len(rows)},
        "summary": f"丢单 {len(rows)} 条" + (f"，主要原因：{max(counter, key=counter.get)}" if counter else ""),
    }


# ═══════════════════════════════════════════════════════════════
# 生产跟单 Agent
# ═══════════════════════════════════════════════════════════════

def tool_tracking_overview(**payload: Any) -> dict[str, Any]:
    """生产跟单总览：各订单节点进度与交期红绿灯。"""
    board = get_store().tracking_board()
    rows = board.get("rows") or []
    summary = board.get("summary") or {}
    return {
        "tracking": {"orders": rows, "summary": summary},
        "order_tracking": {"rows": rows, "summary": summary},
        "summary": (
            f"在产订单 {len(rows)} 张：红灯 {summary.get('red', 0)} / "
            f"黄灯 {summary.get('amber', 0)} / 绿灯 {summary.get('green', 0)}"
        ),
        "actions": [{"type": "link", "path": "/tracking", "label": "打开生产跟单看板"}],
    }


def tool_delay_alert(**payload: Any) -> dict[str, Any]:
    """只挑出有延期风险的订单。"""
    board = get_store().tracking_board()
    rows = [r for r in (board.get("rows") or []) if r.get("light") in ("red", "amber")]
    rows.sort(key=lambda r: (0 if r.get("light") == "red" else 1, -(r.get("delayed_nodes") or 0)))
    return {
        "delay_alerts": rows,
        "summary": f"交期预警 {len(rows)} 张（红 {sum(1 for r in rows if r.get('light') == 'red')}）"
        if rows else "暂无交期预警，全部按计划",
        "actions": [{"type": "link", "path": "/tracking", "label": "打开生产跟单看板"}],
    }


def tool_milestone_advance(**payload: Any) -> dict[str, Any]:
    """推进订单生产节点。"""
    oid = str(payload.get("order_id") or "").strip()
    key = str(payload.get("key") or payload.get("milestone") or "").strip()
    if not oid or not key:
        return {"summary": "缺少 order_id 或 milestone key", "error": "missing_params"}
    item = get_store().advance_milestone(
        oid, key,
        employee=str(payload.get("employee") or ""),
        actual_date=str(payload.get("actual_date") or ""),
        note=str(payload.get("note") or ""),
    )
    if not item:
        return {"summary": f"未找到订单 {oid}", "error": "not_found"}
    return {
        "order": item,
        "summary": f"订单 {oid} 节点 {key} 已推进，当前进度 {item.get('milestone_progress')}",
        "actions": [{"type": "link", "path": "/tracking", "label": "打开生产跟单看板"}],
    }


def tool_chase_factory_script(**payload: Any) -> dict[str, Any]:
    """生成催工厂的话术（中文）。"""
    oid = str(payload.get("order_id") or "").strip()
    found = _find_order_or_quotation(oid)
    item = found.get("item") or {}
    product = item.get("product") or payload.get("product") or "该订单"
    node = item.get("current_milestone") or payload.get("current_node") or "当前节点"
    etd = item.get("etd") or payload.get("etd") or "（未定）"
    script = (
        f"张厂长您好，打扰下。\n"
        f"订单 {oid}（{product}）现在卡在「{node}」这一步，"
        f"计划出货日 {etd}，我们这边客户催得比较紧。\n"
        f"麻烦您帮忙确认三件事：\n"
        f"1) 目前实际进度到哪一步了？\n"
        f"2) 排产/完工预计几号？\n"
        f"3) 有没有卡点（材料、人工、模具）需要我们一起解决？\n"
        f"麻烦今天内回我一下，谢谢！"
    )
    return {
        "chase_script": script,
        "summary": f"已生成订单 {oid} 的催办话术",
    }


# ═══════════════════════════════════════════════════════════════
# 收款催款 Agent
# ═══════════════════════════════════════════════════════════════

def _aging_level(days: int) -> tuple[str, str]:
    """账龄 → (灯色, 力度说明)。"""
    if days <= 0:
        return "green", "未到期"
    if days <= 7:
        return "amber", "温和提醒"
    if days <= 30:
        return "orange", "正式催款"
    return "red", "升级处理"


def tool_collection_board(**payload: Any) -> dict[str, Any]:
    """应收看板：各订单收款进度与逾期情况。"""
    board = get_store().collections_board()
    rows = board.get("rows") or []
    for r in rows:
        days = int(r.get("overdue_days") or 0)
        light, action = _aging_level(days)
        r["aging_light"] = light
        r["collection_action"] = action
    summary = board.get("summary") or {}
    return {
        "collections": {"rows": rows, "summary": summary},
        "summary": (
            f"应收 {len(rows)} 笔，逾期 {summary.get('overdue_count', 0)} 笔，"
            f"逾期金额 {summary.get('overdue_amount', 0)}"
        ),
        "actions": [{"type": "link", "path": "/collections", "label": "打开收款看板"}],
    }


def tool_overdue_aging(**payload: Any) -> dict[str, Any]:
    """只列逾期款项，按账龄分级排序。"""
    board = get_store().collections_board()
    rows = []
    for r in board.get("rows") or []:
        days = int(r.get("overdue_days") or 0)
        if days > 0:
            light, action = _aging_level(days)
            rows.append({**r, "aging_light": light, "collection_action": action})
    rows.sort(key=lambda x: (-(x.get("overdue_days") or 0)))
    return {
        "overdue": rows,
        "summary": f"逾期 {len(rows)} 笔" if rows else "暂无逾期，回款正常",
        "actions": [{"type": "link", "path": "/collections", "label": "打开收款看板"}],
    }


def tool_payment_record(**payload: Any) -> dict[str, Any]:
    """登记一笔收款。"""
    oid = str(payload.get("order_id") or "").strip()
    pid = str(payload.get("payment_id") or "").strip()
    if not oid or not pid:
        return {"summary": "缺少 order_id 或 payment_id", "error": "missing_params"}
    item = get_store().record_payment(
        oid, pid,
        amount=_to_float(payload.get("amount")),
        method=str(payload.get("method") or ""),
        note=str(payload.get("note") or ""),
        employee=str(payload.get("employee") or ""),
    )
    if not item:
        return {"summary": f"未找到订单 {oid}", "error": "not_found"}
    return {
        "order": item,
        "summary": f"订单 {oid} 已登记收款，累计已收 {item.get('paid_amount')}，未收 {item.get('due_amount')}",
        "actions": [{"type": "link", "path": "/collections", "label": "打开收款看板"}],
    }


def tool_dunning_script(**payload: Any) -> dict[str, Any]:
    """生成催款话术，语气随账龄升级。"""
    days = int(_to_float(payload.get("overdue_days")))
    customer = str(payload.get("customer_name") or "客户")
    oid = str(payload.get("order_id") or "")
    amount = payload.get("due_amount") or "-"
    light, action = _aging_level(days)
    if light == "green":
        body = (
            f"Dear {customer},\n\nThis is a friendly reminder that the payment for order {oid} "
            f"({amount}) is due on {payload.get('due_date') or 'the agreed date'}.\n"
            f"Please let us know if you need the invoice or bank details again.\n\nBest regards"
        )
    elif light == "amber":
        body = (
            f"Dear {customer},\n\nWe noticed that the payment for order {oid} ({amount}) "
            f"is now {days} days past due. Could you kindly check with your finance team?\n"
            f"We would appreciate an update on the expected payment date.\n\nBest regards"
        )
    elif light == "orange":
        body = (
            f"Dear {customer},\n\nRegarding order {oid}, the outstanding balance of {amount} "
            f"is now {days} days overdue. We kindly request that payment be arranged within this week.\n"
            f"Please confirm the payment date so we can keep the production/shipping schedule on track.\n\nBest regards"
        )
    else:
        body = (
            f"Dear {customer},\n\nWe must bring to your attention that the balance of {amount} "
            f"for order {oid} is now {days} days overdue, which exceeds our agreed terms.\n"
            f"We request immediate settlement. Please note that further shipments and new production "
            f"may need to be placed on hold until this is resolved.\n"
            f"Kindly confirm today.\n\nBest regards"
        )
    return {
        "dunning": {"level": light, "action": action, "overdue_days": days, "script": body},
        "summary": f"{customer} 逾期 {days} 天 → {action}（{light}）",
    }


def tool_escalation_advice(**payload: Any) -> dict[str, Any]:
    """逾期升级建议。"""
    board = get_store().collections_board()
    escalations = []
    for r in board.get("rows") or []:
        days = int(r.get("overdue_days") or 0)
        if days <= 30:
            continue
        escalations.append({
            "order_id": r.get("id") or r.get("order_id"),
            "customer_name": r.get("customer_name"),
            "due_amount": r.get("due_amount"),
            "overdue_days": days,
            "escalate_to": "经理/信保",
            "action": "暂停新单排产，正式书面催收",
        })
    return {
        "escalations": escalations,
        "summary": f"需升级 {len(escalations)} 笔（逾期超 30 天）" if escalations else "无需升级的逾期款项",
    }


# ═══════════════════════════════════════════════════════════════
# 客户雷达 Agent
# ═══════════════════════════════════════════════════════════════

def _days_between(day_str: str) -> int:
    """距离今天过去了多少天。"""
    d = _parse_day(str(day_str or ""))
    if not d:
        return -1
    return (date.today() - d).days


def tool_customer_pool_scan(**payload: Any) -> dict[str, Any]:
    """扫描公私海客户池现状。"""
    board = get_store().customer_pool_board()
    private = board.get("private") or []
    public = board.get("public") or []
    summary = board.get("summary") or {}
    return {
        "customer_pool": {"private": private, "public": public, "summary": summary},
        "summary": f"私海 {len(private)} 个，公海 {len(public)} 个",
        "actions": [{"type": "link", "path": "/customers/pool", "label": "打开客户公海"}],
    }


def tool_customer_radar_report(**payload: Any) -> dict[str, Any]:
    """私海降温预警 + 公海可认领推荐。"""
    board = get_store().customer_pool_board()
    private = board.get("private") or []
    public = board.get("public") or []
    owner = str(payload.get("owner") or "").strip()

    at_risk = []
    for c in private:
        if owner and str(c.get("owner") or "") != owner:
            continue
        since = _days_between(c.get("last_follow_at") or c.get("claimed_at"))
        recycle_days = int(c.get("recycle_days") or 30)
        recycle_in = (recycle_days - since) if since >= 0 else recycle_days
        if since >= 0 and recycle_in > 7:
            continue
        level = "high" if recycle_in <= 3 else ("medium" if recycle_in <= 7 else "low")
        at_risk.append({
            "customer_id": c.get("id"),
            "customer_name": c.get("name") or c.get("customer_name"),
            "country": c.get("country"),
            "owner": c.get("owner"),
            "days_since_contact": since,
            "recycle_in_days": recycle_in,
            "stage": c.get("stage"),
            "risk_level": level,
            "risk_reason": f"已 {since} 天未跟进，{recycle_in} 天后回收",
        })
    at_risk.sort(key=lambda x: x.get("recycle_in_days") or 0)

    public_picks = []
    for c in public[:5]:
        public_picks.append({
            "customer_id": c.get("id"),
            "customer_name": c.get("name") or c.get("customer_name"),
            "country": c.get("country"),
            "stage": c.get("stage"),
            "suggested_first_move": "先看客户档案与历史沟通，再发一条针对性开场",
        })

    return {
        "customer_radar": {
            "at_risk": at_risk,
            "public_picks": public_picks,
            "summary": {
                "at_risk_count": len(at_risk),
                "recycle_soon": sum(1 for x in at_risk if (x.get("recycle_in_days") or 99) <= 3),
                "public_total": len(public),
            },
        },
        "summary": f"私海预警 {len(at_risk)} 个（3 天内回收 {sum(1 for x in at_risk if (x.get('recycle_in_days') or 99) <= 3)} 个），公海可捞 {len(public)} 个",
        "actions": [{"type": "link", "path": "/customers/pool", "label": "打开客户公海"}],
    }


def tool_reachout_script(**payload: Any) -> dict[str, Any]:
    """按客户阶段生成触达话术。"""
    stage = str(payload.get("stage") or "新询盘")
    name = str(payload.get("customer_name") or "客户")
    days = int(_to_float(payload.get("days_since_contact")))
    product = str(payload.get("product") or "我们的产品")
    if "已报价" in stage:
        body = (
            f"Hi {name},\n\nHope you are doing well. I wanted to follow up on the quotation "
            f"we sent for {product} a few days ago — happy to adjust the spec or MOQ "
            f"if that helps you move forward.\nWould you like me to send a revised option?\n\nBest regards"
        )
    elif "已打样" in stage:
        body = (
            f"Hi {name},\n\nJust checking in on the sample we sent for {product}. "
            f"Have you had a chance to review it?\nIf any adjustment is needed on color/logo, "
            f"we can arrange a revised sample quickly.\n\nBest regards"
        )
    elif "沉睡" in stage:
        body = (
            f"Hi {name},\n\nIt has been a while since we last spoke. We have recently added "
            f"new options in {product} with better lead times.\nIf you have any upcoming projects, "
            f"I would be glad to share the updated catalog.\n\nBest regards"
        )
    else:
        body = (
            f"Hi {name},\n\nThanks again for your inquiry about {product}. "
            f"To move things forward, could you confirm the target quantity and logo requirement?\n"
            f"I will then come back with a firm offer.\n\nBest regards"
        )
    return {
        "reachout": {"stage": stage, "days_since_contact": days, "script": body},
        "summary": f"已按「{stage}」阶段生成触达话术",
    }


def tool_claim_advice(**payload: Any) -> dict[str, Any]:
    """给定客户，给出是否值得认领的建议。"""
    cid = str(payload.get("customer_id") or "").strip()
    board = get_store().customer_pool_board()
    target = None
    for c in (board.get("public") or []) + (board.get("private") or []):
        if str(c.get("id")) == cid:
            target = c
            break
    if not target:
        return {"claim_advice": {}, "summary": f"未找到客户 {cid}", "error": "not_found"}
    is_public = any(str(c.get("id")) == cid for c in (board.get("public") or []))
    return {
        "claim_advice": {
            "customer_id": cid,
            "customer_name": target.get("name") or target.get("customer_name"),
            "in_public_pool": is_public,
            "stage": target.get("stage"),
            "advice": "值得认领：先看档案再触达，24 小时内建立首次联系" if is_public else "该客户已在私海，注意跟进节奏避免被回收",
        },
        "summary": f"{target.get('name') or cid}：" + ("公海可认领" if is_public else "已在私海"),
    }
