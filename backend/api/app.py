"""FastAPI 入口：登录鉴权 + 业务 API。"""
from __future__ import annotations

import threading
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.agents.trade.graph import run_inquiry_pipeline
from backend.agents.orchestrator import orchestrate, run_selected_tools, route_tools
from backend.agents.skills.loader import list_skills
from backend.agents.domain_agents import list_domain_agents
from backend.agents.supervisor import run_supervisor_desk
from backend.agents.tools.handlers import bootstrap_tools
from backend.agents.tools.registry import call_tool, list_tools
from backend.config import get_settings
from backend.core.knowledge_base import KnowledgeBase, get_knowledge_base
from backend.core.chat_assistant import get_chat_assistant
from backend.core.logger import get_logger
from backend.services.auth import get_auth
from backend.services.store import get_store
from backend.services.faq_mysql import get_faq_store
from backend.services.redis_cache import RedisChatCache

logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_kb_status = {
    "ready": False,
    "building": False,
    "backend": "",
    "chunks": 0,
    "parents": 0,
    "children": 0,
    "error": "",
}


def _build_kb_async() -> None:
    global _kb_status
    if _kb_status["building"]:
        return
    _kb_status["building"] = True

    def _job():
        global _kb_status
        try:
            KnowledgeBase.reset()
            result = get_knowledge_base().build()
            _kb_status.update(
                {
                    "ready": True,
                    "building": False,
                    "backend": result.get("backend", ""),
                    "chunks": result.get("chunks", 0),
                    "parents": result.get("parents", 0),
                    "children": result.get("children", 0),
                    "error": result.get("error", ""),
                }
            )
            logger.info(
                f"kb.ready backend={_kb_status['backend']} "
                f"parents={_kb_status['parents']} children={_kb_status['children']}"
            )
        except Exception as e:
            _kb_status.update({"ready": False, "building": False, "error": str(e)})
            logger.error(f"kb.build_failed err={e}")

    threading.Thread(target=_job, daemon=True).start()


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    token = ""
    if authorization:
        parts = authorization.split(" ", 1)
        token = parts[1].strip() if len(parts) == 2 else parts[0].strip()
    user = get_auth().resolve_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效，请重新登录")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@app.on_event("startup")
def on_startup() -> None:
    get_store()
    get_auth()
    bootstrap_tools()
    _build_kb_async()


class LoginBody(BaseModel):
    username: str
    password: str


class ProcessBody(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_name: Optional[str] = None
    country: Optional[str] = None
    user_goal: Optional[str] = None
    tools: Optional[list[str]] = None


class RecommendReplyBody(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_name: Optional[str] = None
    country: Optional[str] = None
    note: Optional[str] = None
    save: bool = True


class AgentRunBody(BaseModel):
    inquiry_id: Optional[str] = None
    user_goal: str = ""
    tools: Optional[list[str]] = None
    query: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""
    # 透传已有中间结果，便于单独跑下游 Agent
    requirement: Optional[dict] = None
    vendor_match: Optional[dict] = None
    compare: Optional[dict] = None
    pipeline: Optional[dict] = None


class SampleBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    product: str = ""
    # 规格明细（礼品打样常踩坑的字段）
    color: str = ""
    color_code: str = ""
    material: str = ""
    size_spec: str = ""
    finish: str = ""
    logo_process: str = ""
    logo_position: str = ""
    sample_qty: str = ""
    sample_fee: str = ""
    tracking_no: str = ""
    status: str = "待打样"
    eta: str = ""
    notes: str = ""


class ApprovalDecideBody(BaseModel):
    approve: bool
    final_text: str = ""


class SearchBody(BaseModel):
    query: str
    top_k: int = Field(default=4, ge=1, le=12)


class ChatAskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    inquiry_id: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""


class AssistantChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    inquiry_id: str = ""
    subject: str = ""
    body: str = ""
    customer_name: str = ""
    country: str = ""
    file_path: str = ""
    force_vision: bool = False


class CustomerBody(BaseModel):
    id: Optional[str] = None
    name: str
    country: str = ""
    contact: str = ""
    email: str = ""
    phone: str = ""
    channel: str = "email"
    tags: Any = ""
    priority: str = "medium"
    last_contact: str = ""
    preferences: str = ""
    memo: str = ""
    notes: str = ""
    company_address: str = ""
    website: str = ""
    timezone: str = ""
    payment_terms: str = ""
    preferred_incoterms: str = ""
    preferred_colors: str = ""
    preferred_materials: str = ""
    owner: Optional[str] = None
    stage: str = ""
    source: str = ""
    blacklist: bool = False


class VendorBody(BaseModel):
    id: Optional[str] = None
    name: str
    region: str = ""
    contact: str = ""
    phone: str = ""
    email: str = ""
    categories: Any = ""
    colors: str = ""
    materials: str = ""
    finishes: str = ""
    logo_processes: str = ""
    custom_color: str = ""
    sample_lead_days: str = ""
    payment_terms: str = ""
    certifications: str = ""
    quality_score: int = 3
    bulk_lead_days: str = ""
    capacity_note: str = ""
    strengths: str = ""
    moq_note: str = ""
    price_note: str = ""
    preferences: str = ""
    memo: str = ""
    notes: str = ""
    active: bool = True


class InquiryBody(BaseModel):
    id: Optional[str] = None
    customer_id: str = ""
    customer_name: str = ""
    country: str = ""
    from_email: str = ""
    subject: str = ""
    body: str = ""
    status: str = "pending"
    qty: str = ""
    target_price: str = ""
    currency: str = "USD"
    incoterms: str = "FOB"
    destination: str = ""
    deadline: str = ""
    product_name: str = ""
    color: str = ""
    material: str = ""
    size_spec: str = ""
    priority: str = "medium"
    source_channel: str = "email"


class QuoteLine(BaseModel):
    product: str = ""
    color: str = ""
    material: str = ""
    qty: str = ""
    unit_price: str = ""
    moq: str = ""
    lead_days: str = ""
    notes: str = ""
    cost_price: str = ""
    floor_price: str = ""


class QuotationBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    customer_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    currency: str = "USD"
    incoterms: str = "FOB"
    valid_until: str = ""
    status: str = "draft"
    total: str = ""
    notes: str = ""
    lines: list[QuoteLine] = Field(default_factory=list)
    floor_price: str = ""
    cost_price: str = ""
    target_price: str = ""
    lost_reason: str = ""
    approve_below_floor: bool = False
    updated_by: str = ""


class QuotationVersionBody(BaseModel):
    lines: list[QuoteLine] = Field(default_factory=list)
    note: str = ""


class QuotationLostBody(BaseModel):
    reason: str = ""


class QuotationStatusBody(BaseModel):
    status: str


class OrderBody(BaseModel):
    id: Optional[str] = None
    inquiry_id: str = ""
    quotation_id: str = ""
    customer_id: str = ""
    customer_name: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    product: str = ""
    color: str = ""
    material: str = ""
    qty: str = ""
    unit_price: str = ""
    currency: str = "USD"
    deposit: str = ""
    status: str = "待定金"
    etd: str = ""
    tracking_no: str = ""
    notes: str = ""
    delivery_date: str = ""
    deposit_due: str = ""
    owner: str = ""


class PaymentBody(BaseModel):
    payment_id: str = ""
    amount: str = ""
    method: str = ""
    note: str = ""


class MilestoneBody(BaseModel):
    key: str
    status: str = "done"
    actual_date: str = ""
    note: str = ""


class OrderMetaBody(BaseModel):
    delivery_date: Optional[str] = None
    deposit_due: Optional[str] = None
    etd: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    owner: Optional[str] = None
    tracking_no: Optional[str] = None


class TransferBody(BaseModel):
    to_employee: str = ""


class RecycleBody(BaseModel):
    days: Optional[int] = None


class FollowupBody(BaseModel):
    id: Optional[str] = None
    customer_id: str = ""
    customer_name: str = ""
    inquiry_id: str = ""
    due_date: str = ""
    reason: str = ""
    suggested_action: str = ""
    priority: str = "medium"
    status: str = "open"


class ActiveBody(BaseModel):
    active: bool


class PasswordBody(BaseModel):
    new_password: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    name: str
    role: str = "外贸业务员"
    email: str = ""
    is_admin: bool = False
    can_approve: bool = False


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "company": settings.company_name,
        "llm": {
            "mock": not settings.use_real_llm,
            "model": settings.resolved_llm_model,
            "base_url": settings.llm_base_url,
            "has_key": bool(settings.resolved_api_key),
        },
        "kb": {
            "ready": _kb_status["ready"],
            "building": _kb_status["building"],
            "backend": _kb_status["backend"],
            "chunks": _kb_status["chunks"],
            "parents": _kb_status["parents"],
            "children": _kb_status["children"],
        },
        "chat": {
            "faq_bm25_confidence": settings.faq_bm25_confidence,
            "redis": f"{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
            "mysql": f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}",
        },
    }


@app.post("/api/auth/login")
def login(body: LoginBody) -> dict:
    try:
        result = get_auth().login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_store().add_audit(result["user"]["name"], "登录系统", result["user"]["username"])
    return result


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(default=None), user: dict = Depends(current_user)) -> dict:
    token = ""
    if authorization:
        parts = authorization.split(" ", 1)
        token = parts[1].strip() if len(parts) == 2 else parts[0].strip()
    get_auth().logout(token)
    get_store().add_audit(user["name"], "退出登录", user["username"])
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@app.get("/api/users")
def users(_: dict = Depends(admin_user)) -> list[dict]:
    return get_auth().list_users()


@app.post("/api/users")
def create_user(body: CreateUserBody, admin: dict = Depends(admin_user)) -> dict:
    try:
        item = get_auth().create_user(
            username=body.username,
            password=body.password,
            name=body.name,
            role=body.role,
            email=body.email,
            is_admin=body.is_admin,
            can_approve=body.can_approve,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    get_store().add_audit(admin["name"], "添加账号", item["username"], item["name"])
    return item


@app.post("/api/users/{user_id}/active")
def set_user_active(user_id: str, body: ActiveBody, admin: dict = Depends(admin_user)) -> dict:
    try:
        item = get_auth().set_active(user_id, body.active)
    except ValueError as e:
        raise HTTPException(400, str(e))
    action = "启用账号" if body.active else "停用账号（离职）"
    get_store().add_audit(admin["name"], action, item["username"], item["name"])
    return item


@app.post("/api/users/{user_id}/password")
def reset_password(user_id: str, body: PasswordBody, admin: dict = Depends(admin_user)) -> dict:
    try:
        get_auth().change_password(user_id, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    target = get_auth().find_by_id(user_id)
    get_store().add_audit(admin["name"], "重置密码", (target or {}).get("username", user_id))
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(current_user)) -> dict[str, Any]:
    return get_store().dashboard()


@app.get("/api/employees")
def employees(_: dict = Depends(current_user)) -> list[dict]:
    return [u for u in get_auth().list_users() if u.get("active")]


@app.get("/api/inquiries")
def inquiries(status: Optional[str] = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_inquiries(status=status)


@app.post("/api/inquiries")
def inquiry_create(body: InquiryBody, user: dict = Depends(current_user)) -> dict:
    item = get_store().create_inquiry(body.model_dump())
    get_store().add_audit(user["name"], "新建询盘", item["id"], item.get("subject", ""))
    return item


@app.patch("/api/inquiries/{inquiry_id}")
def inquiry_patch(inquiry_id: str, body: InquiryBody, user: dict = Depends(current_user)) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.pop("id", None)
    item = get_store().update_inquiry(inquiry_id, data)
    if not item:
        raise HTTPException(404, "询盘不存在")
    get_store().add_audit(user["name"], "更新询盘", inquiry_id, item.get("subject", ""))
    return item


@app.get("/api/inquiries/{inquiry_id}")
def inquiry_detail(inquiry_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_inquiry(inquiry_id)
    if not item:
        raise HTTPException(404, "询盘不存在")
    return item


@app.get("/api/agents")
def agents_catalog(_: dict = Depends(current_user)) -> list[dict]:
    bootstrap_tools()
    return list_tools()


@app.get("/api/skills")
def skills_catalog(_: dict = Depends(current_user)) -> list[dict]:
    """Skill 目录：意图 → 工具链。"""
    bootstrap_tools()
    return list_skills()


@app.get("/api/assistant/agents")
def assistant_agents_catalog(_: dict = Depends(current_user)) -> list[dict]:
    """子 Agent 目录（总控可调度）。"""
    return list_domain_agents()


@app.post("/api/documents/upload")
async def documents_upload(
    file: UploadFile = File(...),
    hint: str = Form(default=""),
    force_vision: bool = Form(default=False),
    parse_now: bool = Form(default=True),
    user: dict = Depends(current_user),
) -> dict:
    """上传 PDF/图片，可选立刻解析文字与表格。"""
    from pathlib import Path

    from backend.services.doc_parser import parse_document_file, save_upload_bytes

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(400, "文件过大（上限 25MB）")
    dest = Path(get_settings().storage_dir) / "uploads"
    path = save_upload_bytes(raw, file.filename or "upload.bin", dest)
    resp: dict[str, Any] = {
        "ok": True,
        "file_path": str(path),
        "filename": path.name,
        "size": len(raw),
    }
    if parse_now:
        bootstrap_tools()
        try:
            parsed = parse_document_file(path, hint=hint, force_vision=force_vision)
            resp["document"] = parsed
            resp["summary"] = parsed.get("summary")
        except Exception as e:
            resp["parse_error"] = str(e)
    get_store().add_audit(user["name"], "上传文档", path.name, resp.get("summary") or "")
    return resp


@app.post("/api/documents/parse")
def documents_parse(body: dict[str, Any], user: dict = Depends(current_user)) -> dict:
    """对已上传文件路径执行解析工具。"""
    bootstrap_tools()
    path = (body.get("file_path") or "").strip()
    if not path:
        raise HTTPException(400, "缺少 file_path")
    result = call_tool(
        "parse_document",
        file_path=path,
        hint=body.get("hint") or body.get("query") or "",
        force_vision=bool(body.get("force_vision")),
        query=body.get("query") or "",
    )
    get_store().add_audit(user["name"], "文档识别", path, result.get("summary") or "")
    return result


@app.post("/api/assistant/chat")
def assistant_chat(body: AssistantChatBody, user: dict = Depends(current_user)) -> dict:
    """
    大对话助手：总控 Agent 意图识别 → Skill 选子 Agent → 子 Agent 选工具并执行。
    """
    ctx: dict = {
        "inquiry_id": body.inquiry_id,
        "subject": body.subject,
        "body": body.body,
        "customer_name": body.customer_name,
        "country": body.country,
        "file_path": body.file_path,
        "force_vision": body.force_vision,
        "pipeline": {},
    }
    if body.file_path:
        ctx["pipeline"] = {
            "document": {"file_path": body.file_path},
        }
        # 有附件时，若用户只说「识别一下」也走文档 Skill
        if not any(k in body.message for k in ["找厂", "比价", "回海外", "询厂", "样品", "认证"]):
            ctx["prefer_doc"] = True
    if body.inquiry_id:
        inquiry = get_store().get_inquiry(body.inquiry_id)
        if inquiry:
            ctx.update(
                {
                    "subject": body.subject or inquiry.get("subject", ""),
                    "body": body.body or inquiry.get("body", ""),
                    "customer_name": body.customer_name or inquiry.get("customer_name", ""),
                    "country": body.country or inquiry.get("country", ""),
                    "pipeline": {
                        **(inquiry.get("pipeline") or {}),
                        **(ctx.get("pipeline") or {}),
                    },
                }
            )
    # 有上传文件时，优先走文档识别（仍可由总控改派）
    message = body.message
    if body.file_path and ("识别" in message or "pdf" in message.lower() or "表格" in message or "ocr" in message.lower() or message in ("看看这个", "帮我看看", "解析附件")):
        message = f"{message}（请识别上传的 PDF/图片文字与表格）"

    result = run_supervisor_desk(message, ctx)
    # 若绑定询盘且跑了业务工具，写回 pipeline
    if body.inquiry_id and result.get("pipeline") and result.get("invoked_tools"):
        inquiry = get_store().get_inquiry(body.inquiry_id)
        if inquiry:
            pipe = {
                **(inquiry.get("pipeline") or {}),
                **(result.get("pipeline") or {}),
                "agent_trace": result.get("agent_trace") or [],
                "invoked_tools": result.get("invoked_tools") or [],
                "route": result.get("route") or {},
                "supervisor": result.get("supervisor") or {},
            }
            get_store().update_inquiry(
                body.inquiry_id,
                {"pipeline": pipe, "assignee": user["name"], "status": "processed"},
            )
    get_store().add_audit(
        user["name"],
        "总控对话",
        f"skill={result.get('supervisor', {}).get('skill')} "
        f"agent={result.get('supervisor', {}).get('agent')} "
        f"q={body.message[:40]}",
    )
    return result


@app.post("/api/agents/route")
def agents_route(body: AgentRunBody, _: dict = Depends(current_user)) -> dict:
    hint = body.subject or body.body or body.user_goal
    plan = route_tools(body.user_goal or body.query or "找厂", hint or "")
    return plan


@app.post("/api/agents/run")
def agents_run(body: AgentRunBody, user: dict = Depends(current_user)) -> dict:
    bootstrap_tools()
    store = get_store()
    inquiry = store.get_inquiry(body.inquiry_id) if body.inquiry_id else None
    context = {
        "inquiry_id": (inquiry or {}).get("id") or body.inquiry_id or "",
        "id": (inquiry or {}).get("id") or body.inquiry_id or "",
        "customer_name": body.customer_name or (inquiry or {}).get("customer_name", ""),
        "country": body.country or (inquiry or {}).get("country", ""),
        "subject": body.subject or (inquiry or {}).get("subject", ""),
        "body": body.body or (inquiry or {}).get("body", ""),
        "query": body.query,
        "requirement": body.requirement,
        "vendor_match": body.vendor_match,
        "compare": body.compare,
        "pipeline": body.pipeline or ((inquiry or {}).get("pipeline") or {}),
    }
    if body.tools:
        result = run_selected_tools(body.tools, context)
        result["route"] = {
            "tools": body.tools,
            "reason": "手动指定工具",
            "intents": [],
            "skill": "manual",
            "skill_title": "手动勾选",
            "skill_mode": "agents",
        }
    else:
        goal = body.user_goal or body.query or "根据当前需求按需调用合适的 Skill，不要无故全跑"
        result = orchestrate(goal, context)

    if inquiry:
        pipe = result.get("pipeline") or {}
        store.update_inquiry(
            inquiry["id"],
            {
                "status": "processed",
                "assignee": user["name"],
                "pipeline": {
                    **(inquiry.get("pipeline") or {}),
                    **pipe,
                    "agent_trace": result.get("agent_trace") or [],
                    "invoked_tools": result.get("invoked_tools") or [],
                    "route": result.get("route") or {},
                    "needs_human_approval": True,
                },
            },
        )
        store.add_audit(
            user["name"],
            "按需调度Agent",
            inquiry["id"],
            ",".join(result.get("invoked_tools") or []),
        )
    return result


@app.post("/api/agents/{tool_name}")
def agents_one(tool_name: str, body: AgentRunBody, user: dict = Depends(current_user)) -> dict:
    bootstrap_tools()
    store = get_store()
    inquiry = store.get_inquiry(body.inquiry_id) if body.inquiry_id else None
    payload = {
        "inquiry_id": (inquiry or {}).get("id") or body.inquiry_id or "",
        "customer_name": body.customer_name or (inquiry or {}).get("customer_name", ""),
        "country": body.country or (inquiry or {}).get("country", ""),
        "subject": body.subject or (inquiry or {}).get("subject", ""),
        "body": body.body or (inquiry or {}).get("body", ""),
        "query": body.query,
        "requirement": body.requirement,
        "vendor_match": body.vendor_match,
        "compare": body.compare,
        "pipeline": body.pipeline or ((inquiry or {}).get("pipeline") or {}),
    }
    try:
        result = call_tool(tool_name, **payload)
    except KeyError:
        raise HTTPException(404, f"未知 Agent: {tool_name}")
    except Exception as e:
        raise HTTPException(400, str(e))

    if inquiry:
        skip = {"summary", "agent", "agent_title", "error"}
        pipe = {
            **(inquiry.get("pipeline") or {}),
            **{k: v for k, v in result.items() if k not in skip},
        }
        store.update_inquiry(
            inquiry["id"],
            {"status": "processed", "assignee": user["name"], "pipeline": pipe},
        )
        store.add_audit(user["name"], f"单独运行:{tool_name}", inquiry["id"], result.get("summary", ""))
    return result


@app.get("/api/samples")
def samples(status: Optional[str] = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_samples(status=status)


@app.post("/api/samples")
def save_sample(body: SampleBody, user: dict = Depends(current_user)) -> dict:
    item = get_store().upsert_sample(body.model_dump())
    get_store().add_audit(user["name"], "更新样品进度", item["id"], item.get("status", ""))
    return item


@app.post("/api/inquiries/{inquiry_id}/process")
def process_inquiry(
    inquiry_id: str,
    body: ProcessBody,
    user: dict = Depends(current_user),
) -> dict:
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
    if not _kb_status["ready"]:
        try:
            get_knowledge_base().build()
            _kb_status["ready"] = True
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


@app.post("/api/inquiries/{inquiry_id}/recommend-reply")
def recommend_reply(
    inquiry_id: str,
    body: RecommendReplyBody,
    user: dict = Depends(current_user),
) -> dict:
    """信件推荐回信：直接 LLM，不走 Agent 工具链。"""
    import json

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


@app.post("/api/inquiries/{inquiry_id}/submit-approval")
def submit_approval(
    inquiry_id: str,
    body: ApprovalDecideBody,
    user: dict = Depends(current_user),
) -> dict:
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


@app.get("/api/approvals")
def approvals(status: Optional[str] = "pending", _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_approvals(status=status)


@app.post("/api/approvals/{approval_id}/decide")
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


@app.get("/api/customers")
def customers(_: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_customers()


@app.get("/api/customers/pool")
def customers_pool(_: dict = Depends(current_user)) -> dict:
    """公海私海看板：私海归属与回收倒计时、公海可认领。"""
    return get_store().customer_pool_board()


@app.post("/api/customers/recycle")
def customers_recycle(body: RecycleBody, user: dict = Depends(current_user)) -> dict:
    """扫描并自动回收超期未跟进的私海客户。"""
    result = get_store().recycle_customers(days=body.days, by=user["name"])
    get_store().add_audit(user["name"], "执行客户回收", f"{result['count']} 个客户回到公海")
    return result


@app.post("/api/customers/{customer_id}/claim")
def customers_claim(customer_id: str, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().claim_customer(customer_id, user["name"], user.get("id", ""))
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "认领客户", item["id"], item.get("name", ""))
    return item


@app.post("/api/customers/{customer_id}/release")
def customers_release(customer_id: str, user: dict = Depends(current_user)) -> dict:
    item = get_store().release_customer(customer_id, user["name"])
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "释放客户回公海", item["id"], item.get("name", ""))
    return item


@app.post("/api/customers/{customer_id}/transfer")
def customers_transfer(customer_id: str, body: TransferBody, user: dict = Depends(current_user)) -> dict:
    if not (user.get("can_approve") or user.get("is_admin")):
        raise HTTPException(403, "只有经理/老板可以转移客户归属")
    try:
        item = get_store().transfer_customer(customer_id, body.to_employee, user["name"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not item:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "转移客户", item["id"], f"{item.get('name','')} → {body.to_employee}")
    return item


@app.post("/api/customers/{customer_id}/touch")
def customers_touch(customer_id: str, user: dict = Depends(current_user)) -> dict:
    """刷新最近跟进时间，避免被自动回收。"""
    item = get_store().touch_customer(customer_id, user["name"])
    if not item:
        raise HTTPException(404, "客户不存在")
    return item


@app.get("/api/customers/{customer_id}")
def customer_detail(customer_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_customer(customer_id)
    if not item:
        raise HTTPException(404, "客户不存在")
    return item


@app.post("/api/customers")
def customer_upsert(body: CustomerBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    is_new = not (payload.get("id") or "").strip()
    if is_new and not (payload.get("owner") or "").strip():
        # 业务员自建的客户直接进自己的私海
        payload["owner"] = user["name"]
    try:
        item = get_store().upsert_customer(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    action = "新建客户" if is_new else "保存客户"
    get_store().add_audit(user["name"], action, item["id"], item.get("name", ""))
    return item


@app.delete("/api/customers/{customer_id}")
def customer_delete(customer_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_customer(customer_id)
    if not ok:
        raise HTTPException(404, "客户不存在")
    get_store().add_audit(user["name"], "删除客户", customer_id)
    return {"ok": True}


@app.get("/api/followups")
def followups(status: Optional[str] = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_followups(status=status)


@app.post("/api/followups")
def followup_upsert(body: FollowupBody, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().upsert_followup(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存跟进", item["id"], item.get("customer_name", ""))
    return item


@app.delete("/api/followups/{followup_id}")
def followup_delete(followup_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_followup(followup_id)
    if not ok:
        raise HTTPException(404, "跟进不存在")
    get_store().add_audit(user["name"], "删除跟进", followup_id)
    return {"ok": True}


@app.post("/api/followups/{followup_id}/done")
def followup_done(followup_id: str, user: dict = Depends(current_user)) -> dict:
    item = get_store().complete_followup(followup_id, user["name"])
    if not item:
        raise HTTPException(404, "跟进不存在")
    get_store().add_audit(user["name"], "完成跟进", followup_id)
    return item


@app.get("/api/quotations")
def quotations(
    inquiry_id: Optional[str] = None,
    status: Optional[str] = None,
    _: dict = Depends(current_user),
) -> list[dict]:
    return get_store().list_quotations(inquiry_id=inquiry_id, status=status)


@app.post("/api/quotations")
def quotation_upsert(body: QuotationBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    payload["lines"] = [x if isinstance(x, dict) else x.model_dump() for x in (body.lines or [])]
    payload["updated_by"] = (payload.get("updated_by") or "").strip() or user["name"]
    item = get_store().upsert_quotation(payload)
    get_store().add_audit(user["name"], "保存报价", item["id"], f"v{item.get('version')} {item.get('customer_name','')}")
    return item


@app.post("/api/quotations/{quotation_id}/status")
def quotation_status(quotation_id: str, body: QuotationStatusBody, user: dict = Depends(current_user)) -> dict:
    existing = get_store().get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["status"] = body.status
    item = get_store().upsert_quotation(existing)
    get_store().add_audit(user["name"], "更新报价状态", quotation_id, body.status)
    return item


@app.delete("/api/quotations/{quotation_id}")
def quotation_delete(quotation_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_quotation(quotation_id)
    if not ok:
        raise HTTPException(404, "报价不存在")
    get_store().add_audit(user["name"], "删除报价", quotation_id)
    return {"ok": True}


@app.post("/api/quotations/from-inquiry/{inquiry_id}")
def quotation_from_inquiry(inquiry_id: str, user: dict = Depends(current_user)) -> dict:
    """从询盘比价结果一键生成草稿报价。"""
    store = get_store()
    inquiry = store.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "询盘不存在")
    pipe = inquiry.get("pipeline") or {}
    compare = pipe.get("compare") or pipe.get("quote_draft") or {}
    options = compare.get("options") or []
    vendors = (pipe.get("vendor_match") or {}).get("matched_vendors") or []
    top = options[0] if options else (vendors[0] if vendors else {})
    lines = [
        {
            "product": inquiry.get("product_name")
            or (pipe.get("requirement") or {}).get("product_summary")
            or inquiry.get("subject")
            or "",
            "color": inquiry.get("color") or "",
            "material": inquiry.get("material") or "",
            "qty": str(inquiry.get("qty") or (pipe.get("requirement") or {}).get("quantity") or ""),
            "unit_price": str(top.get("ref_unit_price_foreign") or top.get("ref_unit_price_cny") or ""),
            "moq": str(top.get("moq") or ""),
            "lead_days": str(top.get("lead_time_days") or top.get("lead_days") or ""),
            "notes": top.get("recommend_level") or top.get("fit_reason") or "",
        }
    ]
    item = store.upsert_quotation(
        {
            "inquiry_id": inquiry_id,
            "customer_id": inquiry.get("customer_id") or "",
            "customer_name": inquiry.get("customer_name") or "",
            "vendor_id": top.get("vendor_id") or "",
            "vendor_name": top.get("vendor_name") or "",
            "currency": inquiry.get("currency") or top.get("foreign_currency") or "USD",
            "incoterms": inquiry.get("incoterms") or "FOB",
            "status": "draft",
            "notes": "由比价结果自动生成",
            "lines": lines,
        }
    )
    store.add_audit(user["name"], "从询盘生成报价", item["id"], inquiry_id)
    return item


@app.post("/api/quotations/{quotation_id}/new-version")
def quotation_new_version(quotation_id: str, body: QuotationVersionBody, user: dict = Depends(current_user)) -> dict:
    """基于当前报价生成下一版（历史版本自动归档，可复盘为什么没成）。"""
    lines = [x if isinstance(x, dict) else x.model_dump() for x in (body.lines or [])]
    item = get_store().new_quotation_version(quotation_id, lines, user["name"], body.note)
    if not item:
        raise HTTPException(404, "报价不存在")
    get_store().add_audit(user["name"], "报价改版", quotation_id, f"升至 v{item.get('version')}")
    return item


@app.post("/api/quotations/{quotation_id}/approve-below-floor")
def quotation_approve_below_floor(quotation_id: str, user: dict = Depends(current_user)) -> dict:
    """低于底价需老板特批；只有老板/管理员可放行。"""
    if not (user.get("is_admin") or user.get("can_approve")):
        raise HTTPException(403, "低于底价的报价需老板特批")
    existing = get_store().get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["approve_below_floor"] = True
    existing["updated_by"] = user["name"]
    item = get_store().upsert_quotation(existing)
    get_store().add_audit(user["name"], "特批低价报价", quotation_id, f"底价 {existing.get('floor_price')}")
    return item


@app.post("/api/quotations/{quotation_id}/lost")
def quotation_lost(quotation_id: str, body: QuotationLostBody, user: dict = Depends(current_user)) -> dict:
    """记录丢单原因，用于后续复盘。"""
    existing = get_store().get_quotation(quotation_id)
    if not existing:
        raise HTTPException(404, "报价不存在")
    existing["status"] = "rejected"
    existing["lost_reason"] = body.reason
    item = get_store().upsert_quotation(existing)
    get_store().add_audit(user["name"], "记录丢单", quotation_id, body.reason)
    return item


@app.get("/api/quotations/{quotation_id}/versions")
def quotation_versions(quotation_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_quotation(quotation_id)
    if not item:
        raise HTTPException(404, "报价不存在")
    history = list(item.get("versions") or [])
    current = {
        "version": item.get("version") or 1,
        "at": item.get("updated_at") or "",
        "by": item.get("updated_by") or "",
        "total": item.get("total") or "",
        "currency": item.get("currency") or "",
        "valid_until": item.get("valid_until") or "",
        "status": item.get("status") or "",
        "note": item.get("notes") or "",
        "lines": item.get("lines") or [],
        "is_current": True,
    }
    return {
        "id": quotation_id,
        "floor_price": item.get("floor_price") or "",
        "below_floor": bool(item.get("below_floor")),
        "boss_approved": bool(item.get("boss_approved")),
        "lost_reason": item.get("lost_reason") or "",
        "versions": [*history, current],
    }


@app.get("/api/orders")
def orders(status: Optional[str] = None, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_orders(status=status)


@app.post("/api/orders")
def order_upsert(body: OrderBody, user: dict = Depends(current_user)) -> dict:
    payload = body.model_dump()
    if not (payload.get("owner") or "").strip():
        payload["owner"] = user["name"]
    try:
        item = get_store().upsert_order(payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存订单", item["id"], item.get("product", ""))
    return item


@app.delete("/api/orders/{order_id}")
def order_delete(order_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_order(order_id)
    if not ok:
        raise HTTPException(404, "订单不存在")
    get_store().add_audit(user["name"], "删除订单", order_id)
    return {"ok": True}


@app.post("/api/orders/from-quotation/{quotation_id}")
def order_from_quotation(quotation_id: str, user: dict = Depends(current_user)) -> dict:
    store = get_store()
    qt = store.get_quotation(quotation_id)
    if not qt:
        raise HTTPException(404, "报价不存在")
    line = (qt.get("lines") or [{}])[0]
    item = store.upsert_order(
        {
            "inquiry_id": qt.get("inquiry_id") or "",
            "quotation_id": quotation_id,
            "customer_id": qt.get("customer_id") or "",
            "customer_name": qt.get("customer_name") or "",
            "vendor_id": qt.get("vendor_id") or "",
            "vendor_name": qt.get("vendor_name") or "",
            "product": line.get("product") or "",
            "color": line.get("color") or "",
            "material": line.get("material") or "",
            "qty": line.get("qty") or "",
            "unit_price": line.get("unit_price") or "",
            "currency": qt.get("currency") or "USD",
            "deposit": "30%",
            "status": "待定金",
            "notes": f"由报价 {quotation_id} 生成",
        }
    )
    if qt.get("status") != "accepted":
        qt["status"] = "accepted"
        store.upsert_quotation(qt)
    store.add_audit(user["name"], "从报价生成订单", item["id"], quotation_id)
    return item


@app.post("/api/orders/from-sample/{sample_id}")
def order_from_sample(sample_id: str, user: dict = Depends(current_user)) -> dict:
    store = get_store()
    samples = store.list_samples()
    sample = next((s for s in samples if s.get("id") == sample_id), None)
    if not sample:
        raise HTTPException(404, "样品不存在")
    item = store.upsert_order(
        {
            "inquiry_id": sample.get("inquiry_id") or "",
            "customer_name": sample.get("customer_name") or "",
            "vendor_id": sample.get("vendor_id") or "",
            "vendor_name": sample.get("vendor_name") or "",
            "product": sample.get("product") or "",
            "color": sample.get("color") or "",
            "material": sample.get("material") or "",
            "qty": sample.get("sample_qty") or "",
            "status": "待定金",
            "notes": f"由样品 {sample_id} 生成",
        }
    )
    store.add_audit(user["name"], "从样品生成订单", item["id"], sample_id)
    return item


@app.get("/api/collections")
def collections_board(_: dict = Depends(current_user)) -> dict:
    """收款账期看板：已收 / 未收 / 逾期催款清单。"""
    return get_store().collections_board()


@app.get("/api/tracking")
def tracking_board(_: dict = Depends(current_user)) -> dict:
    """生产跟单看板：在产订单与交期红绿灯。"""
    return get_store().tracking_board()


@app.post("/api/orders/{order_id}/record-payment")
def order_record_payment(
    order_id: str,
    body: PaymentBody,
    user: dict = Depends(current_user),
) -> dict:
    """登记一笔收款（定金/尾款），自动刷新应收与首节点。"""
    item = get_store().record_payment(
        order_id,
        body.payment_id,
        amount=float(body.amount or 0),
        method=body.method,
        note=body.note,
        employee=user["name"],
    )
    if not item:
        raise HTTPException(404, "订单或收款期不存在")
    get_store().add_audit(user["name"], "登记收款", order_id, f"{body.payment_id} {body.amount}")
    return item


@app.post("/api/orders/{order_id}/milestones/advance")
def order_advance_milestone(
    order_id: str,
    body: MilestoneBody,
    user: dict = Depends(current_user),
) -> dict:
    """推进生产节点（定金到账→排产→中期→验货→报关→签收）。"""
    item = get_store().advance_milestone(
        order_id,
        body.key,
        employee=user["name"],
        actual_date=body.actual_date,
        note=body.note,
        status=body.status,
    )
    if not item:
        raise HTTPException(404, "订单或节点不存在")
    get_store().add_audit(user["name"], "推进生产节点", order_id, body.key)
    return item


@app.post("/api/orders/{order_id}/meta")
def order_update_meta(order_id: str, body: OrderMetaBody, user: dict = Depends(current_user)) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    item = get_store().update_order_meta(order_id, patch)
    if not item:
        raise HTTPException(404, "订单不存在")
    get_store().add_audit(user["name"], "更新订单交期", order_id, str(patch))
    return item


@app.get("/api/customers/{customer_id}/related")
def customer_related(customer_id: str, _: dict = Depends(current_user)) -> dict:
    cust = get_store().get_customer(customer_id)
    if not cust:
        raise HTTPException(404, "客户不存在")
    return get_store().related_for_customer(customer_id=customer_id, customer_name=cust.get("name", ""))


@app.get("/api/vendors/{vendor_id}/related")
def vendor_related(vendor_id: str, _: dict = Depends(current_user)) -> dict:
    vend = get_store().get_vendor(vendor_id)
    if not vend:
        raise HTTPException(404, "厂商不存在")
    return get_store().related_for_vendor(vendor_id=vendor_id, vendor_name=vend.get("name", ""))


@app.get("/api/templates")
def templates(_: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_templates()


@app.get("/api/audit")
def audit(limit: int = 50, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_audit(limit=limit)


@app.get("/api/knowledge/docs")
def knowledge_docs(_: dict = Depends(current_user)) -> list[dict]:
    return get_knowledge_base().list_documents()


@app.post("/api/knowledge/search")
def knowledge_search(body: SearchBody, _: dict = Depends(current_user)) -> dict:
    kb = get_knowledge_base()
    if not kb.ready:
        kb.build()
    hits = kb.search(body.query, top_k=body.top_k)
    return {
        "backend": kb.backend,
        "hits": [
            {"source_name": h.source_name, "score": h.score, "content": h.content}
            for h in hits
        ],
    }


@app.post("/api/chat/ask")
def chat_ask(body: ChatAskBody, user: dict = Depends(current_user)) -> dict:
    """悬浮助手：Redis → MySQL FAQ → 业务 Skill → RAG。"""
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
    result = get_chat_assistant().ask(
        body.question, user_name=user.get("name", ""), context=ctx
    )
    detail = f"source={result.get('source')}"
    if result.get("skill"):
        detail += f" skill={result.get('skill')}"
    detail += f" q={body.question[:40]}"
    get_store().add_audit(user["name"], "对话助手", detail)
    return result


@app.get("/api/chat/status")
def chat_status(_: dict = Depends(current_user)) -> dict:
    faq = get_faq_store()
    n = faq.reload()
    RedisChatCache.reset()
    cache_ok = False
    try:
        from backend.services.redis_cache import get_redis_cache

        cache_ok = get_redis_cache()._get_client() is not None
    except Exception:
        cache_ok = False
    return {
        "redis_ok": cache_ok,
        "mysql_ok": faq.ready,
        "faq_count": n,
        "faq_error": faq.error,
        "confidence_threshold": settings.faq_bm25_confidence,
    }


@app.post("/api/knowledge/rebuild")
def knowledge_rebuild(admin: dict = Depends(admin_user)) -> dict:
    _build_kb_async()
    get_store().add_audit(admin["name"], "重建知识库", "-")
    return {"ok": True, "message": "知识库重建已开始"}


@app.get("/api/products")
def products(_: dict = Depends(current_user)) -> list[dict]:
    """兼容旧路由：返回结构化厂商名录。"""
    return get_store().list_vendors()


@app.get("/api/vendors")
def vendors(active_only: bool = False, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_vendors(active_only=active_only)


@app.get("/api/vendors/{vendor_id}")
def vendor_detail(vendor_id: str, _: dict = Depends(current_user)) -> dict:
    item = get_store().get_vendor(vendor_id)
    if not item:
        raise HTTPException(404, "厂商不存在")
    return item


@app.post("/api/vendors")
def vendor_upsert(body: VendorBody, user: dict = Depends(current_user)) -> dict:
    try:
        item = get_store().upsert_vendor(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    get_store().add_audit(user["name"], "保存厂商", item["id"], item.get("name", ""))
    return item


@app.delete("/api/vendors/{vendor_id}")
def vendor_delete(vendor_id: str, user: dict = Depends(current_user)) -> dict:
    ok = get_store().delete_vendor(vendor_id)
    if not ok:
        raise HTTPException(404, "厂商不存在")
    get_store().add_audit(user["name"], "删除厂商", vendor_id)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.api.app:app", host=settings.api_host, port=settings.api_port, reload=False)
