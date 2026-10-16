"""仓储层纯函数工具：不做 IO、不持锁、可单测。

这里刻意保持无副作用，底价判定、回收倒计时等业务规则都在此实现，
方便 `tests/` 直接构造字典调用，不必启动整个 RuntimeStore。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.services.repositories.constants import DEFAULT_RECYCLE_DAYS


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def to_float(value: Any, default: float = 0.0) -> float:
    """宽松数字解析：允许 "1,200" / "$12.5" / None。"""
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or default)
    except Exception:
        return default


def add_days(date_str: str, days: int) -> str:
    """在 YYYY-MM-DD 上加减天数，解析失败返回空串。"""
    try:
        base = datetime.strptime((date_str or "")[:10], "%Y-%m-%d")
    except Exception:
        return ""
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def days_between(later: str, earlier: str) -> int | None:
    """计算 YYYY-MM-DD 相差天数（later - earlier），解析失败返回 None。"""
    try:
        d1 = datetime.strptime((later or "")[:10], "%Y-%m-%d")
        d2 = datetime.strptime((earlier or "")[:10], "%Y-%m-%d")
    except Exception:
        return None
    return (d1 - d2).days


def parse_tags(value: Any) -> list[str]:
    """把 "a,b/c，d" 这类输入统一成去重前的字符串列表。"""
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    if isinstance(value, str):
        return [
            t.strip()
            for t in value.replace("，", ",").replace("/", ",").split(",")
            if t.strip()
        ]
    return []
