"""Skill 定义加载：每个 YAML 描述意图 → 工具链。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SKILLS_DIR = Path(__file__).resolve().parent


def _normalize(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    sid = (raw.get("id") or fallback_id or "").strip()
    tools = raw.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    triggers = raw.get("triggers") or []
    if not isinstance(triggers, list):
        triggers = []
    return {
        "id": sid,
        "title": (raw.get("title") or sid).strip(),
        "description": (raw.get("description") or "").strip(),
        "when": (raw.get("when") or "").strip(),
        "triggers": [str(t).strip() for t in triggers if str(t).strip()],
        "tools": [str(t).strip() for t in tools if str(t).strip()],
        "requires": list(raw.get("requires") or []),
        "parallel_ok": bool(raw.get("parallel_ok", False)),
        "mode": (raw.get("mode") or "agents").strip(),  # agents | kb
    }


@lru_cache(maxsize=1)
def load_skills() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(SKILLS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        items.append(_normalize(data, path.stem))
    return items


def list_skills() -> list[dict[str, Any]]:
    return [dict(s) for s in load_skills()]


def get_skill(skill_id: str) -> dict[str, Any] | None:
    for s in load_skills():
        if s["id"] == skill_id:
            return dict(s)
    return None


def reload_skills() -> list[dict[str, Any]]:
    load_skills.cache_clear()
    return list_skills()
