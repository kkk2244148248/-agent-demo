from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import get_settings

_INQUIRY_EXTRA = (
    "qty",
    "target_price",
    "currency",
    "incoterms",
    "destination",
    "deadline",
    "product_name",
    "color",
    "material",
    "size_spec",
    "priority",
    "source_channel",
)


def _read_json(name: str) -> list[dict[str, Any]]:
    path = Path(get_settings().seed_dir) / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_inquiry(item: dict[str, Any]) -> dict[str, Any]:
    item.setdefault("customer_id", "")
    item.setdefault("customer_name", "")
    item.setdefault("country", "")
    item.setdefault("from_email", "")
    item.setdefault("subject", "")
    item.setdefault("body", "")
    item.setdefault("status", "pending")
    item.setdefault("assignee", "")
    item.setdefault("pipeline", None)
    item.setdefault("approved_reply", "")
    for k in _INQUIRY_EXTRA:
        item.setdefault(k, "")
    if not item.get("currency"):
        item["currency"] = "USD"
    if not item.get("incoterms"):
        item["incoterms"] = "FOB"
    if not item.get("priority"):
        item["priority"] = "medium"
    if not item.get("source_channel"):
        item["source_channel"] = "email"
    return item


def load_customers() -> list[dict[str, Any]]:
    items = _read_json("customers.json")
    for item in items:
        item.setdefault("phone", "")
        item.setdefault("preferences", "")
        item.setdefault("memo", "")
        item.setdefault("notes", "")
        item.setdefault("company_address", "")
        item.setdefault("website", "")
        item.setdefault("timezone", "")
        item.setdefault("payment_terms", "")
        item.setdefault("preferred_incoterms", "")
        item.setdefault("preferred_colors", "")
        item.setdefault("preferred_materials", "")
        if isinstance(item.get("tags"), str):
            item["tags"] = [t.strip() for t in item["tags"].split(",") if t.strip()]
    return items


def load_vendors() -> list[dict[str, Any]]:
    items = _read_json("vendors.json")
    for item in items:
        item.setdefault("email", "")
        item.setdefault("phone", "")
        item.setdefault("strengths", "")
        item.setdefault("moq_note", "")
        item.setdefault("price_note", "")
        item.setdefault("colors", "")
        item.setdefault("materials", "")
        item.setdefault("finishes", "")
        item.setdefault("logo_processes", "")
        item.setdefault("custom_color", "")
        item.setdefault("sample_lead_days", "")
        item.setdefault("payment_terms", "")
        item.setdefault("certifications", "")
        item.setdefault("quality_score", 3)
        item.setdefault("bulk_lead_days", "")
        item.setdefault("capacity_note", "")
        item.setdefault("preferences", "")
        item.setdefault("memo", "")
        item.setdefault("notes", "")
        item.setdefault("active", True)
        if isinstance(item.get("categories"), str):
            item["categories"] = [t.strip() for t in item["categories"].split(",") if t.strip()]
    return items


def load_inquiries() -> list[dict[str, Any]]:
    return [normalize_inquiry(dict(x)) for x in _read_json("inquiries.json")]


def load_followups() -> list[dict[str, Any]]:
    items = _read_json("followups.json")
    for item in items:
        item.setdefault("status", "open")
        item.setdefault("inquiry_id", "")
        item.setdefault("priority", "medium")
        item.setdefault("suggested_action", "")
    return items


def load_quotations() -> list[dict[str, Any]]:
    items = _read_json("quotations.json")
    for item in items:
        item.setdefault("status", "draft")
        item.setdefault("lines", [])
        item.setdefault("currency", "USD")
        item.setdefault("incoterms", "FOB")
        item.setdefault("notes", "")
        item.setdefault("total", "")
    return items


def load_orders() -> list[dict[str, Any]]:
    items = _read_json("orders.json")
    for item in items:
        item.setdefault("status", "待定金")
        item.setdefault("currency", "USD")
        item.setdefault("deposit", "")
        item.setdefault("etd", "")
        item.setdefault("tracking_no", "")
        item.setdefault("notes", "")
    return items


def load_employees() -> list[dict[str, Any]]:
    return _read_json("employees.json")


def get_inquiry(inquiry_id: str) -> dict[str, Any] | None:
    for item in load_inquiries():
        if item["id"] == inquiry_id:
            return item
    return None
