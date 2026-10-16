"""账号路由：登录、登出、用户与密码管理。

登录接口路径是 `/api/auth/login`（不是 `/api/login`），
前端与压测脚本都依赖这个路径，改动需同步。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.deps import admin_user, current_user, extract_token
from backend.api.schemas import ActiveBody, CreateUserBody, LoginBody, PasswordBody
from backend.services.auth import get_auth
from backend.services.store import get_store

router = APIRouter(tags=["auth"])


@router.post("/api/auth/login")
def login(body: LoginBody) -> dict:
    try:
        result = get_auth().login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    get_store().add_audit(result["user"]["name"], "登录系统", result["user"]["username"])
    return result


@router.post("/api/auth/logout")
def logout(
    authorization: Optional[str] = Header(default=None),
    user: dict = Depends(current_user),
) -> dict:
    get_auth().logout(extract_token(authorization))
    get_store().add_audit(user["name"], "退出登录", user["username"])
    return {"ok": True}


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@router.get("/api/users")
def users(_: dict = Depends(admin_user)) -> list[dict]:
    return get_auth().list_users()


@router.post("/api/users")
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


@router.post("/api/users/{user_id}/active")
def set_user_active(user_id: str, body: ActiveBody, admin: dict = Depends(admin_user)) -> dict:
    """启用/停用账号。停用即离职交接，不删数据。"""
    try:
        item = get_auth().set_active(user_id, body.active)
    except ValueError as e:
        raise HTTPException(400, str(e))
    action = "启用账号" if body.active else "停用账号（离职）"
    get_store().add_audit(admin["name"], action, item["username"], item["name"])
    return item


@router.post("/api/users/{user_id}/password")
def reset_password(user_id: str, body: PasswordBody, admin: dict = Depends(admin_user)) -> dict:
    try:
        get_auth().change_password(user_id, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    target = get_auth().find_by_id(user_id)
    get_store().add_audit(admin["name"], "重置密码", (target or {}).get("username", user_id))
    return {"ok": True}
