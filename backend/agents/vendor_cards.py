"""把匹配到的厂商补全为档案卡片 + 可跳转 actions。"""
from __future__ import annotations

from typing import Any


def _store_vendor(vendor_id: str) -> dict[str, Any] | None:
    if not vendor_id:
        return None
    try:
        from backend.services.store import get_store

        return get_store().get_vendor(vendor_id)
    except Exception:
        return None


def enrich_vendor_card(match: dict[str, Any]) -> dict[str, Any]:
    """合并匹配结果与名录档案，产出聊天可用的厂商卡片。"""
    vid = (match.get("vendor_id") or match.get("id") or "").strip()
    profile = _store_vendor(vid) or {}
    name = match.get("vendor_name") or profile.get("name") or vid or "未知厂商"
    cats = profile.get("categories") or []
    if isinstance(cats, str):
        cats = [x.strip() for x in cats.split(",") if x.strip()]

    card = {
        "vendor_id": vid,
        "vendor_name": name,
        "fit_reason": match.get("fit_reason") or match.get("strengths") or profile.get("strengths") or "",
        "can_do": match.get("can_do", True),
        "risks": match.get("risks") or profile.get("memo") or "",
        "region": profile.get("region") or "",
        "contact": profile.get("contact") or "",
        "phone": profile.get("phone") or "",
        "email": profile.get("email") or "",
        "categories": cats,
        "colors": profile.get("colors") or "",
        "materials": profile.get("materials") or "",
        "finishes": profile.get("finishes") or "",
        "logo_processes": profile.get("logo_processes") or "",
        "custom_color": profile.get("custom_color") or "",
        "sample_lead_days": profile.get("sample_lead_days") or "",
        "bulk_lead_days": profile.get("bulk_lead_days") or "",
        "moq_note": profile.get("moq_note") or "",
        "price_note": profile.get("price_note") or "",
        "certifications": profile.get("certifications") or "",
        "quality_score": profile.get("quality_score") or "",
        "strengths": profile.get("strengths") or "",
        "preferences": profile.get("preferences") or "",
        "memo": profile.get("memo") or "",
        "notes": profile.get("notes") or "",
        "payment_terms": profile.get("payment_terms") or "",
        "capacity_note": profile.get("capacity_note") or "",
        "active": profile.get("active", True) if profile else True,
        "profile": profile or None,
    }
    return card


def enrich_matched_vendors(matched: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in matched or []:
        if isinstance(m, dict):
            out.append(enrich_vendor_card(m))
    return out


def vendor_actions(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为每家厂商生成可点击跳转/后续操作。"""
    actions: list[dict[str, Any]] = []
    for c in cards[:6]:
        vid = c.get("vendor_id") or ""
        name = c.get("vendor_name") or vid
        if not vid:
            continue
        actions.append(
            {
                "type": "link",
                "path": f"/vendors?id={vid}",
                "label": f"查看 {name}",
                "id": vid,
                "entity": "vendor",
            }
        )
        actions.append(
            {
                "type": "chat",
                "label": f"询厂 · {name}",
                "message": f"给 {vid} {name} 写一段询厂微信",
                "id": vid,
            }
        )
    if cards:
        actions.append({"type": "link", "path": "/vendors", "label": "打开厂商名录"})
    return actions
