"""报价仓储：报价 CRUD、版本归档、底价红线与老板特批。"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from backend.services.repositories.normalizers import (
    normalize_quotation,
    quote_total,
)
from backend.services.repositories.utils import now_str

_LINE_FIELDS = (
    "product",
    "color",
    "material",
    "qty",
    "unit_price",
    "moq",
    "lead_days",
    "notes",
    "cost_price",
    "floor_price",
)

# 版本历史最多保留的条数（防 JSON 无限膨胀）
MAX_KEPT_VERSIONS = 12


def _clean_lines(lines: Any) -> list[dict]:
    """把任意输入的行明细统一成标准结构（非 dict 直接丢弃）。"""
    if isinstance(lines, str) or not isinstance(lines, list):
        return []
    return [
        {f: str((line or {}).get(f) or "").strip() for f in _LINE_FIELDS}
        for line in lines
        if isinstance(line, dict)
    ]


class QuotationRepo:
    """报价域。

    两条不可妥协的规则：
    1. 改价必留痕 —— 只要明细或总额变化，旧版自动进 `versions`；
    2. 低于底价必须老板特批 —— 特批标记在改价后自动失效，不能一次批永久用。
    """

    def _quotations(self) -> list[dict]:
        return self.data.setdefault("quotations", [])

    # -- 读 ---------------------------------------------------------------

    def list_quotations(self, inquiry_id: str | None = None, status: str | None = None) -> list[dict]:
        items = self._quotations()
        for item in items:
            normalize_quotation(item)
        if inquiry_id:
            items = [q for q in items if q.get("inquiry_id") == inquiry_id]
        if status:
            items = [q for q in items if q.get("status") == status]
        return deepcopy(items)

    def get_quotation(self, quotation_id: str) -> dict | None:
        for item in self._quotations():
            if item.get("id") == quotation_id:
                normalize_quotation(item)
                return deepcopy(item)
        return None

    # -- 写 ---------------------------------------------------------------

    def upsert_quotation(self, payload: dict) -> dict:
        with self._lock:
            rows = self._quotations()
            qid = (payload.get("id") or "").strip() or f"QT-{uuid.uuid4().hex[:6].upper()}"
            norm_lines = _clean_lines(payload.get("lines"))

            computed = ""
            if norm_lines:
                acc = 0.0
                has_calc = False
                for x in norm_lines:
                    try:
                        q_ = float(x["qty"] or 0)
                        p_ = float(x["unit_price"] or 0)
                    except Exception:
                        continue
                    if q_ and p_:
                        acc += q_ * p_
                        has_calc = True
                if has_calc:
                    computed = str(round(acc, 2))
            total = computed or str(payload.get("total") or "").strip()

            existing = None
            for item in rows:
                if item.get("id") == qid:
                    existing = item
                    break

            row = {
                "id": qid,
                "inquiry_id": (payload.get("inquiry_id") or "").strip(),
                "customer_id": (payload.get("customer_id") or "").strip(),
                "customer_name": (payload.get("customer_name") or "").strip(),
                "vendor_id": (payload.get("vendor_id") or "").strip(),
                "vendor_name": (payload.get("vendor_name") or "").strip(),
                "currency": (payload.get("currency") or "USD").strip(),
                "incoterms": (payload.get("incoterms") or "FOB").strip(),
                "valid_until": (payload.get("valid_until") or "").strip(),
                "status": (payload.get("status") or "draft").strip(),
                "total": total,
                "notes": (payload.get("notes") or "").strip(),
                "lines": norm_lines,
                "floor_price": str(payload.get("floor_price") or "").strip(),
                "cost_price": str(payload.get("cost_price") or "").strip(),
                "target_price": str(payload.get("target_price") or "").strip(),
                "lost_reason": str(payload.get("lost_reason") or "").strip(),
                "version": 1,
                "versions": [],
                "below_floor": False,
                "boss_approved": False,
                "sent_at": "",
                "updated_by": str(payload.get("updated_by") or "").strip(),
                "updated_at": now_str(),
            }
            if existing:
                # 关键风控字段：调用方没给就沿用旧值，避免被空值抹掉
                row["floor_price"] = row["floor_price"] or str(existing.get("floor_price") or "")
                row["cost_price"] = row["cost_price"] or str(existing.get("cost_price") or "")
                row["target_price"] = row["target_price"] or str(existing.get("target_price") or "")
                row["lost_reason"] = row["lost_reason"] or str(existing.get("lost_reason") or "")
                row["sent_at"] = existing.get("sent_at") or ""
                row["updated_by"] = row["updated_by"] or str(existing.get("updated_by") or "")
                versions = list(existing.get("versions") or [])
                version = int(existing.get("version") or 1)
                changed = (
                    json.dumps(existing.get("lines") or [], ensure_ascii=False, sort_keys=True)
                    != json.dumps(norm_lines, ensure_ascii=False, sort_keys=True)
                ) or str(existing.get("total") or "") != total
                if changed:
                    versions.append(
                        {
                            "version": version,
                            "at": existing.get("updated_at") or "",
                            "by": existing.get("updated_by") or "",
                            "total": existing.get("total") or "",
                            "currency": existing.get("currency") or "",
                            "valid_until": existing.get("valid_until") or "",
                            "status": existing.get("status") or "",
                            "note": existing.get("notes") or "",
                            "lines": existing.get("lines") or [],
                        }
                    )
                    version += 1
                row["versions"] = versions[-MAX_KEPT_VERSIONS:]
                row["version"] = version
                # 改价即作废旧特批，必须重新走老板审批
                row["boss_approved"] = bool(existing.get("boss_approved")) and not changed
            normalize_quotation(row)
            if row.get("below_floor") and payload.get("approve_below_floor"):
                row["boss_approved"] = True
            if row.get("status") == "sent" and not row.get("sent_at"):
                row["sent_at"] = now_str()
            for i, item in enumerate(rows):
                if item.get("id") == qid:
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def new_quotation_version(
        self, quotation_id: str, lines: list | None, employee: str = "", note: str = ""
    ) -> dict | None:
        """把当前版本归档，基于新明细生成下一版（保留历史，便于复盘为什么没成）。"""
        with self._lock:
            for i, item in enumerate(self._quotations()):
                if item.get("id") != quotation_id:
                    continue
                normalize_quotation(item)
                versions = list(item.get("versions") or [])
                versions.append(
                    {
                        "version": int(item.get("version") or 1),
                        "at": item.get("updated_at") or "",
                        "by": item.get("updated_by") or employee,
                        "total": item.get("total") or "",
                        "currency": item.get("currency") or "",
                        "valid_until": item.get("valid_until") or "",
                        "status": item.get("status") or "",
                        "note": item.get("notes") or "",
                        "lines": item.get("lines") or [],
                    }
                )
                item["versions"] = versions[-MAX_KEPT_VERSIONS:]
                item["version"] = int(item.get("version") or 1) + 1
                if lines:
                    item["lines"] = _clean_lines(lines)
                item["total"] = quote_total(item)
                if note:
                    item["notes"] = note
                item["status"] = "draft"
                item["boss_approved"] = False
                item["updated_by"] = employee or item.get("updated_by", "")
                item["updated_at"] = now_str()
                normalize_quotation(item)
                self._quotations()[i] = item
                self._write()
                return deepcopy(item)
        return None

    def delete_quotation(self, quotation_id: str) -> bool:
        with self._lock:
            rows = self._quotations()
            before = len(rows)
            self.data["quotations"] = [r for r in rows if r.get("id") != quotation_id]
            if len(self.data["quotations"]) == before:
                return False
            self._write()
            return True

    def quotation_versions(self, quotation_id: str) -> dict | None:
        """当前版本 + 历史版本合并返回，供前端做时间线复盘。"""
        item = self.get_quotation(quotation_id)
        if not item:
            return None
        history = list(item.get("versions") or [])
        current = {
            "version": item.get("version") or 1,
            "at": item.get("updated_at") or "",
            "by": item.get("updated_by") or "",
            "total": item.get("total") or "",
            "currency": item.get("currency") or "",
            "valid_until": item.get("valid_until") or "",
            "status": item.get("status") or "",
            "note": item.get("notes") or "",
            "lines": item.get("lines") or [],
            "is_current": True,
        }
        return {
            "id": quotation_id,
            "floor_price": item.get("floor_price") or "",
            "below_floor": bool(item.get("below_floor")),
            "boss_approved": bool(item.get("boss_approved")),
            "lost_reason": item.get("lost_reason") or "",
            "versions": [*history, current],
        }
