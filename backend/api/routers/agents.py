"""Agent 路由：总控对话、大助手对话、目录查询、文档上传解析。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.agents.domain_agents import list_domain_agents
from backend.agents.orchestrator import orchestrate, run_selected_tools, route_tools
from backend.agents.skills.loader import list_skills
from backend.agents.supervisor import run_supervisor_desk
from backend.agents.tools.handlers import bootstrap_tools
from backend.agents.tools.registry import call_tool, list_tools
from backend.api.deps import current_user
from backend.api.schemas import AgentRunBody, AssistantChatBody
from backend.config import get_settings
from backend.services.store import get_store

router = APIRouter(tags=["agents"])
settings = get_settings()

# 用户提到这些词时，即便带了附件也仍然走业务工具链而不是文档识别
_BUSINESS_INTENT_WORDS = ("找厂", "比价", "回海外", "询厂", "样品", "认证")
# 明确的文档处理意图
_DOC_INTENT_WORDS = ("识别", "pdf", "表格", "ocr", "看看这个", "帮我看看", "解析附件")


@router.get("/api/agents")
def agents_catalog(_: dict = Depends(current_user)) -> list[dict]:
    bootstrap_tools()
    return list_tools()


@router.get("/api/skills")
def skills_catalog(_: dict = Depends(current_user)) -> list[dict]:
    """Skill 目录：意图 → 工具链。"""
    bootstrap_tools()
    return list_skills()


@router.get("/api/assistant/agents")
def assistant_agents_catalog(_: dict = Depends(current_user)) -> list[dict]:
    """子 Agent 目录（总控可调度）。"""
    return list_domain_agents()


@router.post("/api/agents/route")
def agents_route(body: AgentRunBody, _: dict = Depends(current_user)) -> dict:
    """只做路由预演，不真正执行工具（前端用来解释「为什么选这些工具」）。"""
    hint = body.subject or body.body or body.user_goal
    return route_tools(body.user_goal or body.query or "找厂", hint or "")


@router.post("/api/agents/run")
def agents_run(body: AgentRunBody, user: dict = Depends(current_user)) -> dict:
    """按需调度：优先用户手选工具，否则交给编排器自己决定。"""
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
        store.update_inquiry(
            inquiry["id"],
            {
                "status": "processed",
                "assignee": user["name"],
                "pipeline": {
                    **(inquiry.get("pipeline") or {}),
                    **(result.get("pipeline") or {}),
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


@router.post("/api/agents/{tool_name}")
def agents_one(tool_name: str, body: AgentRunBody, user: dict = Depends(current_user)) -> dict:
    """单独跑某个工具/子 Agent，便于调试与人工补跑。"""
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


@router.post("/api/assistant/chat")
def assistant_chat(body: AssistantChatBody, user: dict = Depends(current_user)) -> dict:
    """大对话助手：总控 Agent 意图识别 → Skill 选子 Agent → 子 Agent 选工具并执行。"""
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
        ctx["pipeline"] = {"document": {"file_path": body.file_path}}
        # 有附件但用户没提业务动作时，默认意图就是识别这份文件
        if not any(k in body.message for k in _BUSINESS_INTENT_WORDS):
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
    message = body.message
    if body.file_path and any(k in message.lower() for k in _DOC_INTENT_WORDS):
        message = f"{message}（请识别上传的 PDF/图片文字与表格）"

    result = run_supervisor_desk(message, ctx)
    # 若绑定询盘且跑了业务工具，把中间结果写回询盘 pipeline
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


@router.post("/api/documents/upload")
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
    dest = Path(settings.storage_dir) / "uploads"
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
            # 解析失败不影响上传结果，前端可稍后重试解析
            resp["parse_error"] = str(e)
    get_store().add_audit(user["name"], "上传文档", path.name, resp.get("summary") or "")
    return resp


@router.post("/api/documents/parse")
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
