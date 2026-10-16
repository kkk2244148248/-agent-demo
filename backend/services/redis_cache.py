"""Redis 对话缓存：命中直接返回答案。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import redis

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


def normalize_query(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def cache_key(query: str, tenant_id: str = "") -> str:
    settings = get_settings()
    tenant = tenant_id or settings.default_tenant_id
    digest = hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()[:32]
    return f"{settings.redis_key_prefix}:{tenant}:qa:{digest}"


class RedisChatCache:
    _client: Optional[redis.Redis] = None
    _failed: bool = False

    def __init__(self) -> None:
        self.settings = get_settings()

    def _get_client(self) -> Optional[redis.Redis]:
        if RedisChatCache._failed:
            return None
        if RedisChatCache._client is not None:
            return RedisChatCache._client
        try:
            client = redis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                password=self.settings.redis_password or None,
                db=self.settings.redis_db,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            RedisChatCache._client = client
            logger.info(
                f"redis.connected host={self.settings.redis_host}:{self.settings.redis_port}"
            )
            return client
        except Exception as e:
            RedisChatCache._failed = True
            logger.warning(f"redis.unavailable err={e}")
            return None

    @classmethod
    def reset(cls) -> None:
        cls._client = None
        cls._failed = False

    def get(self, query: str) -> Optional[dict[str, Any]]:
        client = self._get_client()
        if not client:
            return None
        key = cache_key(query)
        try:
            raw = client.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("answer"):
                return data
        except Exception as e:
            logger.warning(f"redis.get_failed err={e}")
        return None

    def set(self, query: str, payload: dict[str, Any]) -> bool:
        client = self._get_client()
        if not client:
            return False
        key = cache_key(query)
        try:
            client.setex(
                key,
                int(self.settings.redis_ttl_seconds),
                json.dumps(payload, ensure_ascii=False),
            )
            return True
        except Exception as e:
            logger.warning(f"redis.set_failed err={e}")
            return False


def get_redis_cache() -> RedisChatCache:
    return RedisChatCache()
