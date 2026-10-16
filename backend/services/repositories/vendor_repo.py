"""厂商仓储：供应商名录 CRUD 与筛选。"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.utils import now_str
from backend.services.seed_data import load_vendors

_VENDOR_DEFAULTS: dict[str, object] = {
    "email": "",
    "phone": "",
    "region": "",
    "contact": "",
    "strengths": "",
    "moq_note": "",
    "price_note": "",
    "colors": "",
    "materials": "",
    "finishes": "",
    "logo_processes": "",
    "custom_color": "",
    "sample_lead_days": "",
    "payment_terms": "",
    "certifications": "",
    "quality_score": 3,
    "bulk_lead_days": "",
    "capacity_note": "",
    "preferences": "",
    "memo": "",
    "notes": "",
    "active": True,
}


class VendorRepo:
    """厂商域。

    礼品出口的选厂核心是「工艺能力匹配」，所以名录里刻意细分了
    colors / materials / finishes / logo_processes / custom_color
    等字段——比价时按这些字段做硬过滤，而不是只按品类。
    """

    @staticmethod
    def _normalize_many(rows: list[dict]) -> None:
        for item in rows:
            for k, v in _VENDOR_DEFAULTS.items():
                item.setdefault(k, v)
            cats = item.get("categories")
            if isinstance(cats, str):
                item["categories"] = [t.strip() for t in cats.split(",") if t.strip()]
            elif not isinstance(cats, list):
                item["categories"] = []

    def _vendors(self) -> list[dict]:
        return self.data.setdefault("vendors", load_vendors())

    @staticmethod
    def to_seed_form(categories) -> str:
        """把列表形式的品类还原成逗号串（给表单回填用）。"""
        if isinstance(categories, list):
            return ", ".join(str(c) for c in categories)
        return str(categories or "")

    def list_vendors(self, active_only: bool = False) -> list[dict]:
        self._normalize_many(self._vendors())
        items = self._vendors()
        if active_only:
            items = [v for v in items if v.get("active", True)]
        return deepcopy(items)

    def get_vendor(self, vendor_id: str) -> dict | None:
        for item in self._vendors():
            if item.get("id") == vendor_id:
                return deepcopy(item)
        return None

    def upsert_vendor(self, payload: dict) -> dict:
        with self._lock:
            rows = self._vendors()
            vid = (payload.get("id") or "").strip() or f"V-{uuid.uuid4().hex[:6]}"
            row = {
                "id": vid,
                "name": (payload.get("name") or "").strip(),
                "region": (payload.get("region") or "").strip(),
                "contact": (payload.get("contact") or "").strip(),
                "phone": (payload.get("phone") or "").strip(),
                "email": (payload.get("email") or "").strip(),
                "categories": self._parse_tags(payload.get("categories")),
                "colors": (payload.get("colors") or "").strip(),
                "materials": (payload.get("materials") or "").strip(),
                "finishes": (payload.get("finishes") or "").strip(),
                "logo_processes": (payload.get("logo_processes") or "").strip(),
                "custom_color": (payload.get("custom_color") or "").strip(),
                "sample_lead_days": (payload.get("sample_lead_days") or "").strip(),
                "payment_terms": (payload.get("payment_terms") or "").strip(),
                "certifications": (payload.get("certifications") or "").strip(),
                "quality_score": int(payload.get("quality_score") or 3),
                "bulk_lead_days": (payload.get("bulk_lead_days") or "").strip(),
                "capacity_note": (payload.get("capacity_note") or "").strip(),
                "strengths": (payload.get("strengths") or "").strip(),
                "moq_note": (payload.get("moq_note") or "").strip(),
                "price_note": (payload.get("price_note") or "").strip(),
                "preferences": (payload.get("preferences") or "").strip(),
                "memo": (payload.get("memo") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
                "active": bool(payload.get("active", True)),
                "updated_at": now_str(),
            }
            if not row["name"]:
                raise ValueError("厂商名称不能为空")
            for i, item in enumerate(rows):
                if item.get("id") == vid:
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def delete_vendor(self, vendor_id: str) -> bool:
        with self._lock:
            rows = self._vendors()
            before = len(rows)
            self.data["vendors"] = [r for r in rows if r.get("id") != vendor_id]
            if len(self.data["vendors"]) == before:
                return False
            self._write()
            return True
