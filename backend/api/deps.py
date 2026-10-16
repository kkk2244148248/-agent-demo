"""路由层共享依赖：鉴权、知识库状态与请求体模型。

所有 router 都从这里取依赖，避免各文件自己 new 一套鉴权逻辑
（多套实现走偏是权限漏洞最常见的来源）。
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from fastapi import Depends, HTTPException, Header

from backend.core.knowledge_base import KnowledgeBase, get_knowledge_base
from backend.core.logger import get_logger
from backend.services.auth import get_auth

logger = get_logger(__name__)

# 知识库构建状态（进程内共享，供 /api/health 与重建接口读写）
kb_status: dict[str, Any] = {
    "ready": False,
    "building": False,
    "backend": "",
    "chunks": 0,
    "parents": 0,
    "children": 0,
    "error": "",
}


def build_kb_async() -> None:
    """后台线程重建知识库，避免阻塞接口响应。"""
    if kb_status["building"]:
        return
    kb_status["building"] = True

    def _job() -> None:
        try:
            KnowledgeBase.reset()
            result = get_knowledge_base().build()
            kb_status.update(
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
                f"kb.ready backend={kb_status['backend']} "
                f"parents={kb_status['parents']} children={kb_status['children']}"
            )
        except Exception as e:
            kb_status.update({"ready": False, "building": False, "error": str(e)})
            logger.error(f"kb.build_failed err={e}")

    threading.Thread(target=_job, daemon=True).start()


def extract_token(authorization: Optional[str]) -> str:
    """从 Authorization 头取裸 token，兼容带/不带 Bearer 前缀两种写法。"""
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    return parts[1].strip() if len(parts) == 2 else parts[0].strip()


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """校验登录态，返回当前用户；失败抛 401。"""
    user = get_auth().resolve_token(extract_token(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效，请重新登录")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    """要求管理员身份；失败抛 403。"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def approver_user(user: dict = Depends(current_user)) -> dict:
    """要求审批权限（经理/老板）。低于底价特批、客户归属转移等用它。"""
    if not (user.get("can_approve") or user.get("is_admin")):
        raise HTTPException(status_code=403, detail="需要经理或老板权限")
    return user
