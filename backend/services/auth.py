"""简易登录鉴权：账号密码 + Token；开除后停用即可立刻进不来。"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from backend.config import get_settings
from backend.services.seed_data import load_employees

_lock = threading.Lock()
TOKEN_DAYS = 14


def _hash_password(password: str, salt: str) -> str:
    raw = f"{salt}:{password}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "name": user["name"],
        "role": user.get("role", ""),
        "email": user.get("email", ""),
        "is_admin": bool(user.get("is_admin")),
        "can_approve": bool(user.get("can_approve")),
        "active": bool(user.get("active", True)),
    }


class AuthStore:
    def __init__(self) -> None:
        root = Path(get_settings().storage_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.users_path = root / "users.json"
        self.sessions_path = root / "sessions.json"
        self.users = self._load_users()
        self.sessions = self._load_sessions()

    def _load_users(self) -> list[dict]:
        if self.users_path.exists():
            return json.loads(self.users_path.read_text(encoding="utf-8"))
        users = []
        for item in load_employees():
            salt = secrets.token_hex(8)
            password = item.get("password") or "123456"
            users.append(
                {
                    "id": item["id"],
                    "username": item.get("username") or item["id"].lower(),
                    "name": item["name"],
                    "role": item.get("role", ""),
                    "email": item.get("email", ""),
                    "is_admin": bool(item.get("is_admin")),
                    "can_approve": bool(item.get("can_approve")),
                    "active": bool(item.get("active", True)),
                    "salt": salt,
                    "password_hash": _hash_password(password, salt),
                }
            )
        self._write_users(users)
        return users

    def _load_sessions(self) -> dict[str, dict]:
        if self.sessions_path.exists():
            return json.loads(self.sessions_path.read_text(encoding="utf-8"))
        return {}

    def _write_users(self, users: list[dict] | None = None) -> None:
        payload = users if users is not None else self.users
        self.users_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_sessions(self) -> None:
        self.sessions_path.write_text(
            json.dumps(self.sessions, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_users(self) -> list[dict]:
        return [_public_user(u) for u in self.users]

    def find_by_username(self, username: str) -> Optional[dict]:
        username = (username or "").strip().lower()
        for u in self.users:
            if u.get("username", "").lower() == username:
                return u
        return None

    def find_by_id(self, user_id: str) -> Optional[dict]:
        for u in self.users:
            if u.get("id") == user_id:
                return u
        return None

    def login(self, username: str, password: str) -> dict[str, Any]:
        user = self.find_by_username(username)
        if not user:
            raise ValueError("账号或密码错误")
        if not user.get("active", True):
            raise ValueError("账号已停用，请联系管理员（可能已离职）")
        expect = user.get("password_hash", "")
        got = _hash_password(password, user.get("salt", ""))
        if not secrets.compare_digest(expect, got):
            raise ValueError("账号或密码错误")

        token = secrets.token_urlsafe(32)
        expire_at = (datetime.now() + timedelta(days=TOKEN_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            self.sessions[token] = {
                "user_id": user["id"],
                "name": user["name"],
                "expire_at": expire_at,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._write_sessions()
        return {"token": token, "user": _public_user(user), "expire_at": expire_at}

    def logout(self, token: str) -> None:
        with _lock:
            if token in self.sessions:
                del self.sessions[token]
                self._write_sessions()

    def resolve_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        sess = self.sessions.get(token)
        if not sess:
            return None
        try:
            exp = datetime.strptime(sess["expire_at"], "%Y-%m-%d %H:%M:%S")
            if exp < datetime.now():
                with _lock:
                    self.sessions.pop(token, None)
                    self._write_sessions()
                return None
        except Exception:
            return None
        user = self.find_by_id(sess["user_id"])
        if not user or not user.get("active", True):
            # 开除/停用后，旧 Token 立刻失效
            with _lock:
                self.sessions.pop(token, None)
                self._write_sessions()
            return None
        return _public_user(user)

    def set_active(self, user_id: str, active: bool) -> dict:
        with _lock:
            user = self.find_by_id(user_id)
            if not user:
                raise ValueError("用户不存在")
            user["active"] = bool(active)
            self._write_users()
            if not active:
                # 踢掉该用户所有会话
                drop = [t for t, s in self.sessions.items() if s.get("user_id") == user_id]
                for t in drop:
                    self.sessions.pop(t, None)
                self._write_sessions()
            return _public_user(user)

    def change_password(self, user_id: str, new_password: str) -> None:
        if len(new_password) < 4:
            raise ValueError("密码至少 4 位")
        with _lock:
            user = self.find_by_id(user_id)
            if not user:
                raise ValueError("用户不存在")
            salt = secrets.token_hex(8)
            user["salt"] = salt
            user["password_hash"] = _hash_password(new_password, salt)
            self._write_users()
            drop = [t for t, s in self.sessions.items() if s.get("user_id") == user_id]
            for t in drop:
                self.sessions.pop(t, None)
            self._write_sessions()

    def create_user(
        self,
        *,
        username: str,
        password: str,
        name: str,
        role: str = "外贸业务员",
        email: str = "",
        is_admin: bool = False,
        can_approve: bool = False,
    ) -> dict:
        username = (username or "").strip().lower()
        name = (name or "").strip()
        if not username or not name:
            raise ValueError("账号和姓名不能为空")
        if len(password or "") < 4:
            raise ValueError("密码至少 4 位")
        if not all(c.isalnum() or c in "._-" for c in username):
            raise ValueError("账号只能用英文、数字、点、下划线、横线")
        if self.find_by_username(username):
            raise ValueError("该账号已存在")

        with _lock:
            idx = len(self.users) + 1
            salt = secrets.token_hex(8)
            user = {
                "id": f"E{idx:02d}-{secrets.token_hex(2)}",
                "username": username,
                "name": name,
                "role": role or "外贸业务员",
                "email": email or "",
                "is_admin": bool(is_admin),
                "can_approve": bool(can_approve or is_admin),
                "active": True,
                "salt": salt,
                "password_hash": _hash_password(password, salt),
            }
            self.users.append(user)
            self._write_users()
            return _public_user(user)


_auth: AuthStore | None = None


def get_auth() -> AuthStore:
    global _auth
    if _auth is None:
        _auth = AuthStore()
    return _auth
