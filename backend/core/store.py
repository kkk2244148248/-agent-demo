"""运行时状态持久化：询盘状态、审批、审计（小团队本地 JSON 够用）。"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import get_settings

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _path() -> Path:
    p = Path(get_settings().storage_dir) / "runtime_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _default() -> dict[str, Any]:
    return {
        "inquiry_status": {},
        "drafts": {},
        "approvals": [],
        "audit": [],
        "followup_done": [],
        "current_employee": "张敏",
    }


def load_state() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        data = _default()
        save_state(data)
        return data
    with _lock:
        return json.loads(path.read_text(encoding="utf-8"))


def save_state(data: dict[str, Any]) -> None:
    with _lock:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_audit(actor: str, action: str, detail: str, ref_id: str = "") -> dict:
    state = load_state()
    item = {
        "id": f"AUD-{uuid.uuid4().hex[:8]}",
        "at": _now(),
        "actor": actor,
        "action": action,
        "detail": detail,
        "ref_id": ref_id,
    }
    state.setdefault("audit", []).insert(0, item)
    state["audit"] = state["audit"][:200]
    save_state(state)
    return item


def upsert_draft(inquiry_id: str, payload: dict, actor: str) -> dict:
    state = load_state()
    draft = {
        **payload,
        "inquiry_id": inquiry_id,
        "updated_at": _now(),
        "updated_by": actor,
        "status": payload.get("status", "awaiting_approval"),
    }
    state.setdefault("drafts", {})[inquiry_id] = draft
    state.setdefault("inquiry_status", {})[inquiry_id] = draft["status"]
    save_state(state)
    add_audit(actor, "save_draft", f"保存询盘草稿 {inquiry_id}", inquiry_id)
    return draft


def decide_draft(inquiry_id: str, decision: str, reply_text: str, actor: str, note: str = "") -> dict:
    state = load_state()
    draft = state.get("drafts", {}).get(inquiry_id)
    if not draft:
        raise ValueError("草稿不存在，请先跑 Agent 流水线")
    status = "sent" if decision == "approve" else "rejected"
    draft["status"] = status
    draft["reply_draft"] = reply_text
    draft["decided_at"] = _now()
    draft["decided_by"] = actor
    draft["decision_note"] = note
    state["drafts"][inquiry_id] = draft
    state["inquiry_status"][inquiry_id] = status
    approval = {
        "id": f"AP-{uuid.uuid4().hex[:8]}",
        "inquiry_id": inquiry_id,
        "decision": decision,
        "actor": actor,
        "at": _now(),
        "note": note,
    }
    state.setdefault("approvals", []).insert(0, approval)
    save_state(state)
    add_audit(actor, decision, f"{decision} {inquiry_id}", inquiry_id)
    return draft


def mark_followup_done(followup_id: str, actor: str) -> None:
    state = load_state()
    done = set(state.get("followup_done", []))
    done.add(followup_id)
    state["followup_done"] = list(done)
    save_state(state)
    add_audit(actor, "followup_done", f"完成跟进 {followup_id}", followup_id)
