"""询盘路由：询盘 CRUD、Agent 流水线、推荐回信、发送审批。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from backend.agents.trade.graph import run_inquiry_pipeline
from backend.api.deps import current_user, kb_status
from backend.api.schemas import (
    ApprovalDecideBody,
    ChatAskBody,
    InquiryBody,
    ProcessBody,
    RecommendReplyBody,
)
from backend.core.knowledge_base import get_knowledge_base
from backend.core.logger import get_logger
from backend.config import get_settings
from backend.services.store import get_store

router = APIRouter(tags=["inquiries"])
logger = get_logger(__name__)
settings = get_settings()


@router.get("/api/inquiries")
def inquiries(status: str | None = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_inquiries(status=status)


@router.post("/api/inquiries")
def inquiry_create(body: InquiryBody, user: dict = Depends(current_user)) -> dict:
    item = get_store().create_inquiry(body.model_dump())
    get_store().add_audit(user["name"], "新建询盘", item["id"], item.get("subject", ""))
    return item


@router.get("/api/inquiries/{inquiry_id}")
def inquiry_detail(inquiry_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_inquiry(inquiry_id)
    if not item:
        raise HTTPException(404, "询盘不存在")
    return item


@router.patch("/api/inquiries/{inquiry_id}")
def inquiry_patch(inquiry_id: str, body: InquiryBody, user: dict = Depends(current_user)) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.pop("id", None)
    item = get_store().update_inquiry(inquiry_id, data)
    if not item:
        raise HTTPException(404, "询盘不存在")
    get_store().add_audit(user["name"], "更新询盘", inquiry_id, item.get("subject", ""))
    return item


@router.post("/api/inquiries/{inquiry_id}/process")
def process_inquiry(
    inquiry_id: str,
    body: ProcessBody,
    user: dict = Depends(current_user),
) -> dict:
    """跑完整流水线：意图识别 → 需求提取 → 找厂 → 比价 → 起草报价与回信。"""
    store = get_store()
    inquiry = store.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "询盘不存在")

    payload = {
        **inquiry,
        "subject": body.subject or inquiry.get("subject", ""),
        "body": body.body or inquiry.get("body", ""),
        "customer_name": body.customer_name or inquiry.get("customer_name", ""),
        "country": body.country or inquiry.get("country", ""),
        "pipeline": inquiry.get("pipeline") or {},
    }
    # 知识库未就绪时就地构建一次（首次请求会慢，之后走缓存）
    if not kb_status["ready"]:
        try:
            get_knowledge_base().build()
            kb_status["ready"] = True
        except Exception:
            pass

    result = run_inquiry_pipeline(payload, user_goal=body.user_goal, tools=body.tools)
    store.update_inquiry(
        inquiry_id,
        {
            "status": "processed",
            "assignee": user["name"],
            "pipeline": {
                **(inquiry.get("pipeline") or {}),
                "intent": result.get("intent"),
                "intent_detail": result.get("intent_detail"),
                "requirement": result.get("requirement"),
                "retrieved_sources": result.get("retrieved_sources"),
                "retrieved_context": result.get("retrieved_context"),
                "vendor_match": result.get("vendor_match"),
                "compare": result.get("compare"),
                "quote_draft": result.get("quote_draft"),
                "reply_draft": result.get("reply_draft"),
                "factory_brief": result.get("factory_brief"),
                "agent_trace": result.get("agent_trace"),
                "invoked_tools": result.get("invoked_tools"),
                "route": result.get("route"),
                # 默认仍需人工确认后才允许发出
                "needs_human_approval": result.get("needs_human_approval", True),
            },
        },
    )
    store.add_audit(
        user["name"],
        "智能调度Agent",
        inquiry_id,
        ",".join(result.get("invoked_tools") or []),
    )
    return result


@router.post("/api/inquiries/{inquiry_id}/recommend-reply")
def recommend_reply(
    inquiry_id: str,
    body: RecommendReplyBody,
    user: dict = Depends(current_user),
) -> dict:
    """信件推荐回信：直接 LLM，不走 Agent 工具链（更快、更贴合信里语气）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.agents.trade.prompts import RECOMMEND_REPLY_SYSTEM, RECOMMEND_REPLY_USER
    from backend.core.llm_factory import get_llm

    store = get_store()
    inquiry = store.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "询盘不存在")

    subject = (body.subject or inquiry.get("subject") or "").strip()
    letter = (body.body or inquiry.get("body") or "").strip()
    if not letter and not subject:
        raise HTTPException(400, "来信主题/正文为空，无法推荐回信")

    customer = body.customer_name or inquiry.get("customer_name") or ""
    country = body.country or inquiry.get("country") or ""
    pipe = inquiry.get("pipeline") or {}
    spec = {
        "product_name": inquiry.get("product_name") or "",
        "qty": inquiry.get("qty") or "",
        "target_price": inquiry.get("target_price") or "",
        "currency": inquiry.get("currency") or "",
        "incoterms": inquiry.get("incoterms") or "",
        "destination": inquiry.get("destination") or "",
        "deadline": inquiry.get("deadline") or "",
        "color": inquiry.get("color") or "",
        "material": inquiry.get("material") or "",
        "size_spec": inquiry.get("size_spec") or "",
    }
    context = {
        "requirement": pipe.get("requirement") or {},
        "matched_vendors": (pipe.get("vendor_match") or {}).get("matched_vendors") or [],
        "compare": pipe.get("compare") or {},
    }

    llm = get_llm("reply", temperature=0.4)
    prompt = RECOMMEND_REPLY_USER.format(
        company=settings.company_name,
        customer=customer,
        country=country,
        subject=subject,
        body=letter,
        spec_json=json.dumps(spec, ensure_ascii=False),
        context_json=json.dumps(context, ensure_ascii=False),
        note=(body.note or "").strip() or "无",
    )
    try:
        resp = llm.invoke(
            [SystemMessage(content=RECOMMEND_REPLY_SYSTEM), HumanMessage(content=prompt)]
        )
        draft = (getattr(resp, "content", None) or str(resp)).strip()
    except Exception as e:
        logger.error(f"recommend_reply.failed err={e}")
        raise HTTPException(502, f"推荐回信生成失败：{e}") from e

    if not draft:
        raise HTTPException(502, "模型未返回回信内容")

    if body.save:
        store.update_inquiry(
            inquiry_id,
            {
                "status": "processed",
                "assignee": user["name"],
                "pipeline": {
                    **pipe,
                    "reply_draft": draft,
                    "recommend_reply_meta": {
                        "source": "llm_direct",
                        "model": settings.resolved_llm_model,
                    },
                },
            },
        )
    store.add_audit(user["name"], "推荐回信", inquiry_id, f"len={len(draft)}")
    return {
        "inquiry_id": inquiry_id,
        "reply_draft": draft,
        "source": "llm_direct",
        "model": settings.resolved_llm_model,
    }


@router.post("/api/inquiries/{inquiry_id}/submit-approval")
def submit_approval(
    inquiry_id: str,
    body: ApprovalDecideBody,
    user: dict = Depends(current_user),
) -> dict:
    """把草稿送进审批队列，批准前不可发出（风控闸门）。"""
    store = get_store()
    inquiry = store.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "询盘不存在")
    draft = body.final_text or ((inquiry.get("pipeline") or {}).get("reply_draft") or "")
    if not draft:
        raise HTTPException(400, "没有可提交的草稿")
    item = store.create_approval(
        inquiry_id,
        draft,
        user["name"],
        meta={"intent": (inquiry.get("pipeline") or {}).get("intent")},
    )
    store.add_audit(user["name"], "提交发送审批", item["id"], inquiry_id)
    return item


@router.get("/api/approvals")
def approvals(status: str | None = "pending", _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_approvals(status=status)


@router.post("/api/approvals/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    body: ApprovalDecideBody,
    user: dict = Depends(current_user),
) -> dict:
    if not user.get("can_approve") and not user.get("is_admin"):
        raise HTTPException(403, "您没有审批权限，请让经理或老板操作")
    item = get_store().decide_approval(approval_id, body.approve, user["name"], body.final_text)
    if not item:
        raise HTTPException(404, "审批单不存在")
    get_store().add_audit(
        user["name"],
        "确认发送" if body.approve else "驳回草稿",
        approval_id,
        item.get("inquiry_id", ""),
    )
    return item


@router.post("/api/chat/ask")
def chat_ask(body: ChatAskBody, user: dict = Depends(current_user)) -> dict:
    """悬浮助手：Redis → MySQL FAQ → 业务 Skill → RAG。"""
    from backend.core.chat_assistant import get_chat_assistant

    ctx: dict = {
        "inquiry_id": body.inquiry_id,
        "subject": body.subject,
        "body": body.body,
        "customer_name": body.customer_name,
        "country": body.country,
    }
    if body.inquiry_id:
        inquiry = get_store().get_inquiry(body.inquiry_id)
        if inquiry:
            ctx.update(
                {
                    "subject": body.subject or inquiry.get("subject", ""),
                    "body": body.body or inquiry.get("body", ""),
                    "customer_name": body.customer_name or inquiry.get("customer_name", ""),
                    "country": body.country or inquiry.get("country", ""),
                    "pipeline": inquiry.get("pipeline") or {},
                }
            )
    result = get_chat_assistant().ask(body.question, user_name=user.get("name", ""), context=ctx)
    detail = f"source={result.get('source')}"
    if result.get("skill"):
        detail += f" skill={result.get('skill')}"
    detail += f" q={body.question[:40]}"
    get_store().add_audit(user["name"], "对话助手", detail)
    return result
