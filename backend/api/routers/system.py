"""系统路由：健康检查、首页看板、审计日志。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.deps import current_user, kb_status
from backend.config import get_settings
from backend.services.store import get_store

router = APIRouter(tags=["system"])
settings = get_settings()


@router.get("/api/health")
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
            "ready": kb_status["ready"],
            "building": kb_status["building"],
            "backend": kb_status["backend"],
            "chunks": kb_status["chunks"],
            "parents": kb_status["parents"],
            "children": kb_status["children"],
        },
        "chat": {
            "faq_bm25_confidence": settings.faq_bm25_confidence,
            "redis": f"{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
            "mysql": f"{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}",
        },
        # 供账号管理页回填「初始密码」输入框，避免前端硬编码
        "default_user_password": settings.default_user_password,
    }


@router.get("/api/dashboard")
def dashboard(_: dict = Depends(current_user)) -> dict[str, Any]:
    return get_store().dashboard()


@router.get("/api/employees")
def employees(_: dict = Depends(current_user)) -> list[dict]:
    from backend.services.auth import get_auth

    return [u for u in get_auth().list_users() if u.get("active")]


@router.get("/api/audit")
def audit(limit: int = 50, _: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_audit(limit=limit)


@router.get("/api/templates")
def templates(_: dict = Depends(current_user)) -> list[dict]:
    return get_store().list_templates()
