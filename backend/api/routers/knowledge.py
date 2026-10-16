"""知识库与对话助手路由：RAG 检索、文档列表、分层缓存状态。

分层降级设计（逐层可独立失效）：
    Redis 缓存 → MySQL FAQ/BM25 → RAG 检索
任何一层挂掉都只是「慢一点」，不会让助手整体不可用。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import admin_user, build_kb_async, current_user
from backend.api.schemas import SearchBody
from backend.config import get_settings
from backend.core.knowledge_base import get_knowledge_base
from backend.services.faq_mysql import get_faq_store
from backend.services.store import get_store

router = APIRouter(tags=["knowledge"])
settings = get_settings()


@router.get("/api/knowledge/docs")
def knowledge_docs(_: dict = Depends(current_user)) -> list[dict]:
    return get_knowledge_base().list_documents()


@router.post("/api/knowledge/search")
def knowledge_search(body: SearchBody, _: dict = Depends(current_user)) -> dict:
    kb = get_knowledge_base()
    if not kb.ready:
        kb.build()
    hits = kb.search(body.query, top_k=body.top_k)
    return {
        "backend": kb.backend,
        "hits": [
            {"source_name": h.source_name, "score": h.score, "content": h.content} for h in hits
        ],
    }


@router.post("/api/knowledge/rebuild")
def knowledge_rebuild(admin: dict = Depends(admin_user)) -> dict:
    """重建向量库：只在换模型或批量加文档后需要，耗时较长故异步执行。"""
    build_kb_async()
    get_store().add_audit(admin["name"], "重建知识库", "-")
    return {"ok": True, "message": "知识库重建已开始"}


@router.get("/api/chat/status")
def chat_status(_: dict = Depends(current_user)) -> dict:
    """返回各层可用性，便于前端展示「助手降级中」提示。"""
    faq = get_faq_store()
    n = faq.reload()
    from backend.services.redis_cache import RedisChatCache

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
