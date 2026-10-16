"""各司其职的 Agent 工具实现（可被编排器按需调用，也可单独调用）。"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.tools.registry import AgentTool, register_tool
from backend.agents.trade.prompts import (
    CLIENT_REPLY_SYSTEM,
    CLIENT_REPLY_USER,
    COMPARE_SYSTEM,
    COMPARE_USER,
    FACTORY_BRIEF_SYSTEM,
    FACTORY_BRIEF_USER,
    REQUIREMENT_SYSTEM,
    REQUIREMENT_USER,
    VENDOR_MATCH_SYSTEM,
    VENDOR_MATCH_USER,
)
from backend.config import get_settings
from backend.core.knowledge_base import get_knowledge_base
from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.services.store import get_store

logger = get_logger(__name__)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _ctx(payload: dict[str, Any]) -> dict[str, Any]:
    """统一上下文：inquiry 字段 + 已有 pipeline 中间结果。"""
    pipe = payload.get("pipeline") or {}
    return {
        "inquiry_id": payload.get("inquiry_id") or payload.get("id") or "",
        "customer_name": payload.get("customer_name", ""),
        "country": payload.get("country", ""),
        "subject": payload.get("subject", ""),
        "body": payload.get("body", ""),
        "requirement": payload.get("requirement") or pipe.get("requirement") or pipe.get("intent_detail") or {},
        "vendor_match": payload.get("vendor_match") or pipe.get("vendor_match") or {},
        "compare": payload.get("compare") or pipe.get("compare") or {},
        "retrieved_context": payload.get("retrieved_context") or pipe.get("retrieved_context") or "",
        "retrieved_sources": payload.get("retrieved_sources") or pipe.get("retrieved_sources") or [],
        "reply_draft": payload.get("reply_draft") or pipe.get("reply_draft") or "",
        "factory_brief": payload.get("factory_brief") or pipe.get("factory_brief") or "",
        "query": payload.get("query") or "",
    }


def tool_parse_requirement(**payload: Any) -> dict[str, Any]:
    c = _ctx(payload)
    llm = get_llm("requirement", temperature=0)
    prompt = REQUIREMENT_USER.format(
        customer=c["customer_name"],
        country=c["country"],
        subject=c["subject"],
        body=c["body"],
    )
    resp = llm.invoke([SystemMessage(content=REQUIREMENT_SYSTEM), HumanMessage(content=prompt)])
    data = _parse_json(resp.content)
    logger.info(f"tool.parse_requirement category={data.get('category')}")
    return {
        "requirement": data,
        "intent": data.get("category", ""),
        "intent_detail": data,
        "summary": f"已解析品类：{data.get('category')}，数量约 {data.get('quantity')}",
    }


def tool_search_vendors(**payload: Any) -> dict[str, Any]:
    c = _ctx(payload)
    req = c["requirement"]
    query = (
        c["query"]
        or " ".join(
            [
                str(req.get("search_query") or ""),
                str(req.get("product_summary") or ""),
                str(req.get("category") or ""),
                c["subject"],
                c["body"][:300],
            ]
        )
    ).strip()
    if not query:
        query = "礼品 厂商"

    kb = get_knowledge_base()
    if not kb.ready:
        kb.build()
    hits = kb.search(query, top_k=5)
    context = kb.format_context(query, top_k=5)
    sources = [h.source_name for h in hits]

    llm = get_llm("vendor_match", temperature=0)
    prompt = VENDOR_MATCH_USER.format(
        requirement_json=json.dumps(req or {"raw_query": query}, ensure_ascii=False),
        context=context,
    )
    resp = llm.invoke([SystemMessage(content=VENDOR_MATCH_SYSTEM), HumanMessage(content=prompt)])
    data = _parse_json(resp.content)
    from backend.agents.vendor_cards import enrich_matched_vendors, vendor_actions

    cards = enrich_matched_vendors(data.get("matched_vendors") or [])
    # 回写补全后的匹配列表，便于下游与聊天展示
    data["matched_vendors"] = [
        {
            "vendor_id": c.get("vendor_id"),
            "vendor_name": c.get("vendor_name"),
            "fit_reason": c.get("fit_reason"),
            "can_do": c.get("can_do", True),
            "risks": c.get("risks"),
        }
        for c in cards
    ]
    n = len(cards)
    actions = vendor_actions(cards)
    logger.info(f"tool.search_vendors n={n}")
    return {
        "vendor_match": data,
        "vendors": cards,
        "actions": actions,
        "nav_links": [a for a in actions if a.get("type") == "link"],
        "retrieved_context": context,
        "retrieved_sources": sources,
        "summary": f"匹配到 {n} 家候选厂商",
    }


def tool_compare_quotes(**payload: Any) -> dict[str, Any]:
    c = _ctx(payload)
    if not c["requirement"] and not c["vendor_match"]:
        return {"error": "请先运行需求解析或厂商匹配，或在参数里提供 requirement/vendor_match"}
    llm = get_llm("compare", temperature=0)
    prompt = COMPARE_USER.format(
        requirement_json=json.dumps(c["requirement"], ensure_ascii=False),
        matched_json=json.dumps(c["vendor_match"], ensure_ascii=False),
        context=c["retrieved_context"] or "（无检索上下文，请基于匹配结果估算）",
    )
    resp = llm.invoke([SystemMessage(content=COMPARE_SYSTEM), HumanMessage(content=prompt)])
    data = _parse_json(resp.content)
    options = data.get("options") or []
    top = next((o for o in options if o.get("recommend_level") == "首选"), options[0] if options else None)
    quote_draft = None
    if top:
        quote_draft = {
            "currency": top.get("foreign_currency") or "USD",
            "incoterms": "FOB China",
            "lead_time_days": top.get("lead_time_days") or 0,
            "moq": top.get("moq") or 0,
            "unit_price": top.get("ref_unit_price_foreign") or 0,
            "unit_price_cny": top.get("ref_unit_price_cny") or 0,
            "vendor_id": top.get("vendor_id"),
            "vendor_name": top.get("vendor_name"),
            "notes": data.get("suggested_client_price_note") or "",
            "options": options,
        }
    return {
        "compare": data,
        "quote_draft": quote_draft,
        "summary": f"生成 {len(options)} 个比价方案",
    }


def tool_draft_client_reply(**payload: Any) -> dict[str, Any]:
    c = _ctx(payload)
    llm = get_llm("reply", temperature=0.3)
    prompt = CLIENT_REPLY_USER.format(
        company=get_settings().company_name,
        customer=c["customer_name"],
        country=c["country"],
        subject=c["subject"],
        body=c["body"],
        requirement_json=json.dumps(c["requirement"], ensure_ascii=False),
        compare_json=json.dumps(c["compare"], ensure_ascii=False),
    )
    resp = llm.invoke([SystemMessage(content=CLIENT_REPLY_SYSTEM), HumanMessage(content=prompt)])
    text = resp.content.strip()
    return {"reply_draft": text, "summary": "已生成海外回复草稿"}


def tool_draft_factory_brief(**payload: Any) -> dict[str, Any]:
    c = _ctx(payload)
    vendors = (c["vendor_match"] or {}).get("matched_vendors") or []
    options = (c["compare"] or {}).get("options") or []
    top = next((o for o in options if o.get("recommend_level") == "首选"), None)
    vendor: Any = None
    if top:
        vendor = next((v for v in vendors if v.get("vendor_id") == top.get("vendor_id")), top)
    elif vendors:
        vendor = vendors[0]
    if not vendor:
        return {
            "factory_brief": "暂无厂商信息。请先单独运行「厂商匹配」。",
            "summary": "缺少厂商，已跳过",
        }
    llm = get_llm("factory_brief", temperature=0.2)
    prompt = FACTORY_BRIEF_USER.format(
        requirement_json=json.dumps(c["requirement"], ensure_ascii=False),
        vendor_json=json.dumps(vendor, ensure_ascii=False),
    )
    resp = llm.invoke([SystemMessage(content=FACTORY_BRIEF_SYSTEM), HumanMessage(content=prompt)])
    return {"factory_brief": resp.content.strip(), "summary": f"已生成询厂话术 → {vendor.get('vendor_name', '')}"}


def tool_list_samples(**payload: Any) -> dict[str, Any]:
    status = payload.get("status")
    items = get_store().list_samples(status=status)
    return {"samples": items, "summary": f"样品记录 {len(items)} 条"}


def tool_upsert_sample(**payload: Any) -> dict[str, Any]:
    item = get_store().upsert_sample(
        {
            "id": payload.get("sample_id") or payload.get("id"),
            "inquiry_id": payload.get("inquiry_id", ""),
            "customer_name": payload.get("customer_name", ""),
            "vendor_id": payload.get("vendor_id", ""),
            "vendor_name": payload.get("vendor_name", ""),
            "product": payload.get("product", ""),
            "color": payload.get("color", ""),
            "color_code": payload.get("color_code", ""),
            "material": payload.get("material", ""),
            "size_spec": payload.get("size_spec", ""),
            "finish": payload.get("finish", ""),
            "logo_process": payload.get("logo_process", ""),
            "logo_position": payload.get("logo_position", ""),
            "sample_qty": payload.get("sample_qty", ""),
            "sample_fee": payload.get("sample_fee", ""),
            "tracking_no": payload.get("tracking_no", ""),
            "status": payload.get("status", "待打样"),
            "eta": payload.get("eta", ""),
            "notes": payload.get("notes", ""),
        }
    )
    return {"sample": item, "summary": f"样品已更新：{item.get('status')}"}


def tool_cert_checklist(**payload: Any) -> dict[str, Any]:
    """轻量认证检查：按品类给出出口常见认证清单（规则+知识库补充）。"""
    c = _ctx(payload)
    cat = str((c["requirement"] or {}).get("category") or c["query"] or c["subject"]).lower()
    base = ["商业发票", "装箱单", "合同/PO"]
    extra: list[str] = []
    if any(k in cat for k in ["数码", "power", "充电宝", "电池"]):
        extra = ["CE", "FCC", "RoHS", "UN38.3（含电池运输）"]
    elif any(k in cat for k in ["杯", "tumbler", "餐", "食品"]):
        extra = ["食品接触材料证明", "FDA/LFGB（视市场）"]
    elif any(k in cat for k in ["服饰", "hoodie", "布"]):
        extra = ["成分标", "OEKO-TEX（若客户要求）"]
    elif any(k in cat for k in ["袋", "tote", "再生"]):
        extra = ["GRS（再生料，若宣传环保）"]
    else:
        extra = ["按目标市场补充认证"]
    return {
        "checklist": base + extra,
        "summary": f"认证检查项 {len(base) + len(extra)} 条",
    }


def tool_parse_document(**payload: Any) -> dict[str, Any]:
    """解析 PDF / 图片中的文字与表格（pdfplumber + 视觉模型）。"""
    from backend.services.doc_parser import parse_document_file

    path = (payload.get("file_path") or payload.get("document_path") or "").strip()
    hint = (payload.get("query") or payload.get("user_goal") or payload.get("hint") or "").strip()
    force_vision = bool(payload.get("force_vision"))
    if not path:
        path = ((payload.get("pipeline") or {}).get("document") or {}).get("file_path") or ""
    if not path:
        return {
            "document": {},
            "summary": "未提供文件。请先上传 PDF/图片，或传入 file_path。",
            "error": "missing_file_path",
        }
    try:
        parsed = parse_document_file(path, hint=hint, force_vision=force_vision)
    except Exception as e:
        logger.error(f"tool_parse_document.failed err={e}")
        return {"document": {}, "summary": f"文档解析失败：{e}", "error": str(e)}
    return {
        "document": parsed,
        "document_text": parsed.get("text") or "",
        "document_tables": parsed.get("tables") or [],
        "document_fields": parsed.get("structured") or {},
        "summary": parsed.get("summary") or "文档已解析",
    }


def tool_crm_action(**payload: Any) -> dict[str, Any]:
    from backend.agents.tools.crm_actions import tool_crm_action as _impl

    return _impl(**payload)


def tool_suggest_nav(**payload: Any) -> dict[str, Any]:
    from backend.agents.tools.crm_actions import tool_suggest_nav as _impl

    return _impl(**payload)


def bootstrap_tools() -> None:
    """注册全部 Agent 工具（幂等）。"""
    if _REGISTRY_BOOTSTRAPPED[0]:
        return
    from backend.agents.tools import extended as ext

    specs = [
        AgentTool(
            name="parse_requirement",
            title="需求解析 Agent",
            description="把海外礼品需求拆成品类、数量、预算、LOGO、交期等字段",
            when_to_use="刚收到海外邮件、还没理清需求时",
            handler=tool_parse_requirement,
        ),
        AgentTool(
            name="search_vendors",
            title="厂商匹配 Agent",
            description="检索国内厂商库：谁能做、能力与风险",
            when_to_use="需要找厂、查哪家适合做这个礼品时（可单独运行）",
            handler=tool_search_vendors,
        ),
        AgentTool(
            name="compare_quotes",
            title="比价建议 Agent",
            description="基于需求与厂商给出参考价、MOQ、交期与首选备选",
            when_to_use="已经有候选厂商，要做比价方案时",
            handler=tool_compare_quotes,
        ),
        AgentTool(
            name="rank_vendors",
            title="厂商排序",
            description="按 MOQ/交期/风险给候选厂商打分并排序短名单",
            when_to_use="已有候选厂，要排出优先级/短名单时",
            handler=ext.tool_rank_vendors,
        ),
        AgentTool(
            name="estimate_cost",
            title="成本粗算",
            description="基于比价或品类经验粗算 FOB/参考成本区间（非正式报价）",
            when_to_use="要心里有数报价区间、粗算金额时",
            handler=ext.tool_estimate_cost,
        ),
        AgentTool(
            name="vendor_risk_check",
            title="厂商风险检查",
            description="检查候选厂商停用/备注风险/认证缺口",
            when_to_use="定点前要过风险、看哪家有坑时",
            handler=ext.tool_vendor_risk_check,
        ),
        AgentTool(
            name="draft_client_reply",
            title="海外回复 Agent",
            description="起草给外国总部/客户的回复邮件",
            when_to_use="要把方案反馈给海外时",
            handler=tool_draft_client_reply,
        ),
        AgentTool(
            name="draft_factory_brief",
            title="询厂话术 Agent",
            description="起草发给国内工厂的中文询价微信/邮件",
            when_to_use="已经选定厂商，要去询价打样时",
            handler=tool_draft_factory_brief,
        ),
        AgentTool(
            name="polish_reply",
            title="回复润色",
            description="把已有海外回复改成更短/更正式/更强硬",
            when_to_use="已有草稿要改语气、压缩篇幅时",
            handler=ext.tool_polish_reply,
        ),
        AgentTool(
            name="extract_email_todos",
            title="邮件待办抽取",
            description="从询盘邮件抽出待办、风险与截止提示",
            when_to_use="邮件很长、要快速理清要做什么时",
            handler=ext.tool_extract_email_todos,
        ),
        AgentTool(
            name="draft_followup_mail",
            title="跟催邮件",
            description="客户未回复时起草跟催邮件",
            when_to_use="报价发出后要催确认时",
            handler=ext.tool_draft_followup_mail,
        ),
        AgentTool(
            name="list_samples",
            title="样品进度 Agent",
            description="查看样品进度列表",
            when_to_use="跟样品、看有没有超期时",
            handler=tool_list_samples,
        ),
        AgentTool(
            name="upsert_sample",
            title="样品登记 Agent",
            description="新建或更新一条样品进度",
            when_to_use="安排打样、寄样、海外确认节点时",
            handler=tool_upsert_sample,
        ),
        AgentTool(
            name="sample_overdue",
            title="逾期样品",
            description="列出 ETA 已过且未完成的样品",
            when_to_use="查哪些样品延期了",
            handler=ext.tool_sample_overdue,
        ),
        AgentTool(
            name="advance_sample_status",
            title="推进样品状态",
            description="按打样→寄样→确认流程推进状态",
            when_to_use="样品节点往前走、更新状态时",
            handler=ext.tool_advance_sample_status,
        ),
        AgentTool(
            name="sample_brief",
            title="打样简报",
            description="生成给工厂的打样要求简报",
            when_to_use="要发给工厂清晰打样要求时",
            handler=ext.tool_sample_brief,
        ),
        AgentTool(
            name="cert_checklist",
            title="认证检查 Agent",
            description="按品类给出出口常见认证/单证检查清单",
            when_to_use="涉及充电宝电池、食品接触、再生料宣传时",
            handler=tool_cert_checklist,
        ),
        AgentTool(
            name="market_cert_pack",
            title="市场认证包",
            description="按目的国（美/欧/英/澳/日）给出认证单证包",
            when_to_use="已知出口国家，要一次性列出单证时",
            handler=ext.tool_market_cert_pack,
        ),
        AgentTool(
            name="claim_risk_check",
            title="宣传风险检查",
            description="检查可降解/再生/抗菌等宣传用语风险",
            when_to_use="文案里有环保/医疗等宣称时",
            handler=ext.tool_claim_risk_check,
        ),
        AgentTool(
            name="shipping_doc_checklist",
            title="出货单证清单",
            description="发票箱单等出货单证核对清单",
            when_to_use="准备出货、核对单证时",
            handler=ext.tool_shipping_doc_checklist,
        ),
        AgentTool(
            name="parse_document",
            title="文档识别 Agent",
            description="识别 PDF/图片中的文字与表格（报价单、规格表、询价附件）",
            when_to_use="用户上传了 PDF、截图、表格图片，或说识别文档/OCR/读表格",
            handler=tool_parse_document,
        ),
        AgentTool(
            name="extract_quote_fields",
            title="报价字段抽取",
            description="从已识别文档抽取单价/MOQ/交期等",
            when_to_use="识别完报价单后要结构化字段时",
            handler=ext.tool_extract_quote_fields,
        ),
        AgentTool(
            name="doc_vs_requirement",
            title="文档需求对比",
            description="对比文档与客户需求缺口",
            when_to_use="工厂回的规格/报价是否满足询盘时",
            handler=ext.tool_doc_vs_requirement,
        ),
        AgentTool(
            name="crm_action",
            title="CRM 操作工具",
            description="根据用户话添加厂商/客户/跟进；信息不足则给出页面跳转",
            when_to_use="用户说添加厂商、新建客户、加跟进，或要打开某业务页面",
            handler=tool_crm_action,
        ),
        AgentTool(
            name="suggest_nav",
            title="页面跳转建议",
            description="返回业务页面跳转链接（厂商/客户/询盘等）",
            when_to_use="用户只要跳转去某页面、不想自动写入时",
            handler=tool_suggest_nav,
        ),
        AgentTool(
            name="search_crm",
            title="CRM 搜索",
            description="按关键词搜索客户与厂商档案",
            when_to_use="查找某客户/厂商是否已建档时",
            handler=ext.tool_search_crm,
        ),
        AgentTool(
            name="customer_360",
            title="客户360",
            description="汇总客户关联询盘/报价/订单/跟进",
            when_to_use="要看某客户全貌时",
            handler=ext.tool_customer_360,
        ),
        AgentTool(
            name="list_overdue_followups",
            title="逾期跟进",
            description="列出逾期未完成的跟进待办",
            when_to_use="今天有哪些跟进逾期了",
            handler=ext.tool_list_overdue_followups,
        ),
        AgentTool(
            name="kb_search",
            title="知识库检索",
            description="RAG 检索公司/厂商资料并组织答案",
            when_to_use="问口径、产品资料、MOQ 经验等",
            handler=ext.tool_kb_search,
        ),
        AgentTool(
            name="faq_lookup",
            title="FAQ 快查",
            description="MySQL FAQ / BM25 高频问答",
            when_to_use="常见问题想快速命中标准答时",
            handler=ext.tool_faq_lookup,
        ),
        # ─── 钱账链路：利润核算 Agent ───────────────────────
        AgentTool(
            name="profit_calc",
            title="真实毛利测算",
            description="收入 - 全成本 + 退税，按真实口径算清一笔单赚多少",
            when_to_use="用户问这个单能赚多少、毛利多少、划不划算",
            handler=ext.tool_profit_calc,
        ),
        AgentTool(
            name="margin_check",
            title="毛利达标检查",
            description="快速判断毛利率是否达到公司红线",
            when_to_use="只想知道这个价能不能接",
            handler=ext.tool_margin_check,
        ),
        AgentTool(
            name="rebate_estimate",
            title="出口退税估算",
            description="按退税率与采购额估算退税金额",
            when_to_use="核算成本、需要计入退税时",
            handler=ext.tool_rebate_estimate,
        ),
        AgentTool(
            name="fx_stress_test",
            title="汇率压力测试",
            description="人民币升值后毛利变化测算",
            when_to_use="担心汇率波动吃掉利润时",
            handler=ext.tool_fx_stress_test,
        ),
        AgentTool(
            name="quote_price_suggest",
            title="建议报价区间",
            description="按成本加成法给出建议报价与底价",
            when_to_use="要报价但不确定报多少合适",
            handler=ext.tool_quote_price_suggest,
        ),
        # ─── 报价守门 Agent ────────────────────────────────
        AgentTool(
            name="floor_price_check",
            title="底价红线校验",
            description="校验报价是否低于底价，是否需要特批",
            when_to_use="报出前确认有没有破底线",
            handler=ext.tool_floor_price_check,
        ),
        AgentTool(
            name="quote_version_diff",
            title="报价版本对比",
            description="对比报价历史版本，看每版改动",
            when_to_use="复盘改了哪几版、为什么改",
            handler=ext.tool_quote_version_diff,
        ),
        AgentTool(
            name="below_floor_review",
            title="待特批报价",
            description="列出低于底价、尚未特批的报价",
            when_to_use="经理/老板审核特批时",
            handler=ext.tool_below_floor_review,
        ),
        AgentTool(
            name="lost_deal_analysis",
            title="丢单归因",
            description="统计丢单原因分布",
            when_to_use="复盘为什么丢单",
            handler=ext.tool_lost_deal_analysis,
        ),
        # ─── 生产跟单 Agent ────────────────────────────────
        AgentTool(
            name="tracking_overview",
            title="生产跟单总览",
            description="各订单 6 节点进度与交期红绿灯",
            when_to_use="看所有在产订单进度时",
            handler=ext.tool_tracking_overview,
        ),
        AgentTool(
            name="delay_alert",
            title="交期预警",
            description="只挑出有延期风险的订单",
            when_to_use="今天哪些单要延期了",
            handler=ext.tool_delay_alert,
        ),
        AgentTool(
            name="milestone_advance",
            title="推进生产节点",
            description="把订单某个生产节点标记为完成",
            when_to_use="工厂反馈某节点做完了",
            handler=ext.tool_milestone_advance,
        ),
        AgentTool(
            name="chase_factory_script",
            title="催工厂话术",
            description="生成催工厂的具体话术",
            when_to_use="要催工厂但不知道怎么开口",
            handler=ext.tool_chase_factory_script,
        ),
        # ─── 收款催款 Agent ────────────────────────────────
        AgentTool(
            name="collection_board",
            title="应收看板",
            description="各订单收款进度与逾期情况",
            when_to_use="看该收的钱收了多少",
            handler=ext.tool_collection_board,
        ),
        AgentTool(
            name="overdue_aging",
            title="逾期账龄",
            description="按账龄分级列出逾期款项",
            when_to_use="谁欠我钱、欠多久了",
            handler=ext.tool_overdue_aging,
        ),
        AgentTool(
            name="payment_record",
            title="登记收款",
            description="登记一笔定金/尾款到账",
            when_to_use="客户打款了要记账",
            handler=ext.tool_payment_record,
        ),
        AgentTool(
            name="dunning_script",
            title="催款话术",
            description="按账龄生成对应力度的催款邮件",
            when_to_use="要催款但语气不好拿捏",
            handler=ext.tool_dunning_script,
        ),
        AgentTool(
            name="escalation_advice",
            title="逾期升级建议",
            description="逾期超 30 天的升级处理建议",
            when_to_use="催不回来了要不要升级",
            handler=ext.tool_escalation_advice,
        ),
        # ─── 客户雷达 Agent ────────────────────────────────
        AgentTool(
            name="customer_pool_scan",
            title="客户池扫描",
            description="公私海客户池现状总览",
            when_to_use="盘一下手里的客户",
            handler=ext.tool_customer_pool_scan,
        ),
        AgentTool(
            name="customer_radar_report",
            title="客户雷达报告",
            description="私海降温预警 + 公海可认领推荐",
            when_to_use="哪些客户要跑了、公海有什么好客户",
            handler=ext.tool_customer_radar_report,
        ),
        AgentTool(
            name="reachout_script",
            title="触达话术",
            description="按客户阶段生成跟进开场白",
            when_to_use="要联系客户但不知道说什么",
            handler=ext.tool_reachout_script,
        ),
        AgentTool(
            name="claim_advice",
            title="认领建议",
            description="判断某客户是否值得认领",
            when_to_use="公海里的客户要不要捞",
            handler=ext.tool_claim_advice,
        ),
    ]
    for t in specs:
        register_tool(t)
    _REGISTRY_BOOTSTRAPPED[0] = True


_REGISTRY_BOOTSTRAPPED = [False]
