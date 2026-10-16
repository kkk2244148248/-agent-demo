"""样品仓储：打样进度跟踪（含礼品打样最容易踩坑的规格字段）。"""
from __future__ import annotations

import uuid
from copy import deepcopy

from backend.services.repositories.normalizers import normalize_sample
from backend.services.repositories.utils import now_str


class SampleRepo:
    """样品域。

    打样是礼品单最常见的翻车点（颜色/工艺/LOGO 位置说不清），
    所以样品记录刻意比订单多留了 color_code / finish / logo_position 等字段，
    并在写回时统一 trim，避免同一样品出现「哑光黑」「哑光黑 」两个版本。
    """

    _SPEC_TEXT_FIELDS = (
        "color",
        "color_code",
        "material",
        "size_spec",
        "finish",
        "logo_process",
        "logo_position",
        "sample_fee",
        "tracking_no",
    )

    def _samples(self) -> list[dict]:
        return self.data.setdefault("samples", [])

    def list_samples(self, status: str | None = None) -> list[dict]:
        for item in self._samples():
            normalize_sample(item)
        items = self._samples()
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def get_sample(self, sample_id: str) -> dict | None:
        for item in self._samples():
            if item.get("id") == sample_id:
                return deepcopy(item)
        return None

    def upsert_sample(self, payload: dict) -> dict:
        with self._lock:
            sid = payload.get("id") or f"S-{uuid.uuid4().hex[:6]}"
            existing = None
            for item in self._samples():
                if item.get("id") == sid:
                    existing = item
                    break
            row = {
                "id": sid,
                "inquiry_id": payload.get("inquiry_id", ""),
                "customer_name": payload.get("customer_name", ""),
                "vendor_id": payload.get("vendor_id", ""),
                "vendor_name": payload.get("vendor_name", ""),
                "product": payload.get("product", ""),
                "sample_qty": str(payload.get("sample_qty") or "").strip(),
                "status": payload.get("status", "待打样"),
                "eta": payload.get("eta", ""),
                "notes": payload.get("notes", ""),
                "updated_at": now_str(),
            }
            for f in self._SPEC_TEXT_FIELDS:
                row[f] = (payload.get(f) or "").strip()
            if existing:
                existing.update(row)
                self._write()
                return deepcopy(existing)
            self._samples().insert(0, row)
            self._write()
            return deepcopy(row)
