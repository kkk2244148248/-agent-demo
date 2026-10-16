"""运行时状态：询盘状态、审批、审计（小团队本地 JSON，够用）。"""
from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.services.seed_data import (
    load_customers,
    load_followups,
    load_inquiries,
    load_orders,
    load_quotations,
    load_vendors,
)

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_SAMPLE_SPEC_FIELDS = (
    "color",
    "color_code",
    "material",
    "size_spec",
    "finish",
    "logo_process",
    "logo_position",
    "sample_qty",
    "sample_fee",
    "tracking_no",
)


def _normalize_sample(item: dict) -> None:
    for key in _SAMPLE_SPEC_FIELDS:
        item.setdefault(key, "")


# ---------------------------------------------------------------------------
# P0 跑单机制：客户公海私海 / 报价版本与底价 / 收款账期 / 生产跟单
# ---------------------------------------------------------------------------

DEFAULT_RECYCLE_DAYS = 30

# 客户生命周期阶段
CUSTOMER_STAGES = ("新询盘", "已报价", "已打样", "已下单", "复购", "沉睡")

# 生产跟单标准节点（顺序推进）
PRODUCTION_MILESTONES: tuple[tuple[str, str], ...] = (
    ("deposit", "定金到账"),
    ("po", "排产下单"),
    ("midcheck", "中期进度"),
    ("finalcheck", "尾期验货"),
    ("customs", "报关出货"),
    ("arrived", "到港签收"),
)

# 标准收款比例
DEFAULT_PAYMENT_PLAN: tuple[tuple[str, float], ...] = (
    ("定金", 0.3),
    ("尾款", 0.7),
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or default)
    except Exception:
        return default


def _add_days(date_str: str, days: int) -> str:
    """在 YYYY-MM-DD 上加减天数，解析失败返回空串。"""
    try:
        base = datetime.strptime((date_str or "")[:10], "%Y-%m-%d")
    except Exception:
        return ""
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _normalize_customer_ownership(item: dict) -> None:
    """公海/私海：owner 为空即公海；有 owner 即私海，带认领时间与回收倒计时。"""
    item.setdefault("owner", "")
    item.setdefault("owner_id", "")
    item.setdefault("claimed_at", "")
    item.setdefault("intake_at", item.get("created_at") or "")
    item.setdefault("last_follow_at", item.get("last_contact") or "")
    item.setdefault("recycle_days", DEFAULT_RECYCLE_DAYS)
    item.setdefault("stage", "新询盘")
    item.setdefault("source", item.get("channel") or "email")
    item.setdefault("blacklist", False)
    if not item.get("owner"):
        item["owner"] = ""
    item["pool"] = "private" if item.get("owner") else "public"


def _customer_recycle_deadline(item: dict) -> str:
    """私海客户按最近跟进日 + 回收天数算出应回收日期。"""
    if not item.get("owner"):
        return ""
    anchor = item.get("last_follow_at") or item.get("claimed_at") or item.get("intake_at") or ""
    if not anchor:
        return ""
    try:
        days = int(item.get("recycle_days") or DEFAULT_RECYCLE_DAYS)
    except Exception:
        days = DEFAULT_RECYCLE_DAYS
    return _add_days(anchor, days)


def _normalize_quotation(item: dict) -> None:
    """报价版本化 + 底价红线。"""
    item.setdefault("version", 1)
    item.setdefault("versions", [])
    item.setdefault("floor_price", "")
    item.setdefault("cost_price", "")
    item.setdefault("target_price", "")
    item.setdefault("below_floor", False)
    item.setdefault("boss_approved", False)
    item.setdefault("lost_reason", "")
    item.setdefault("sent_at", "")
    item.setdefault("last_action_at", item.get("updated_at") or "")
    for line in item.get("lines") or []:
        if isinstance(line, dict):
            line.setdefault("floor_price", "")
            line.setdefault("cost_price", "")
    _recompute_quote_floor(item)


def _recompute_quote_floor(item: dict) -> None:
    """按明细行重算是否低于底价（有底价才判定）。"""
    floor = _to_float(item.get("floor_price"), 0.0)
    below = False
    if floor > 0:
        for line in item.get("lines") or []:
            if not isinstance(line, dict):
                continue
            price = _to_float(line.get("unit_price"), 0.0)
            line_floor = _to_float(line.get("floor_price"), 0.0) or floor
            if price > 0 and price < line_floor:
                below = True
                break
    item["below_floor"] = bool(below)
    if not below:
        item["boss_approved"] = False


def _quote_total(item: dict) -> str:
    total = 0.0
    has = False
    for line in item.get("lines") or []:
        if not isinstance(line, dict):
            continue
        qty = _to_float(line.get("qty"), 0.0)
        price = _to_float(line.get("unit_price"), 0.0)
        if qty and price:
            total += qty * price
            has = True
    return str(round(total, 2)) if has else (item.get("total") or "")


def _normalize_order(item: dict) -> None:
    """生产跟单节点 + 收款计划。"""
    qty = _to_float(item.get("qty"), 0.0)
    price = _to_float(item.get("unit_price"), 0.0)
    total = round(qty * price, 2) if (qty and price) else _to_float(item.get("total_amount"), 0.0)
    if total:
        item["total_amount"] = str(total)

    deposit_raw = str(item.get("deposit") or "").strip().rstrip("%")
    ratio = 0.3
    if deposit_raw:
        try:
            ratio = float(deposit_raw) / 100.0
        except Exception:
            ratio = 0.3
    ratio = min(max(ratio, 0.0), 1.0)

    payments = item.get("payments")
    if not isinstance(payments, list) or not payments:
        payments = []
        for idx, (name, part) in enumerate((( "定金", ratio), ("尾款", round(1 - ratio, 4)))):
            amount = round(total * part, 2) if total else 0.0
            payments.append(
                {
                    "id": f"PAY-{idx + 1}",
                    "name": name,
                    "ratio": part,
                    "amount": amount,
                    "due_date": item.get("etd") if name == "尾款" else (item.get("deposit_due") or ""),
                    "status": "paid" if (name == "定金" and item.get("status") in ("生产中", "已出货", "已签收")) else "pending",
                    "paid_amount": amount if (name == "定金" and item.get("status") in ("生产中", "已出货", "已签收")) else 0.0,
                    "paid_at": "",
                    "method": "",
                    "note": "",
                }
            )
    item["payments"] = payments

    paid = 0.0
    for p in payments:
        if isinstance(p, dict):
            paid += _to_float(p.get("paid_amount"), 0.0)
    item["paid_amount"] = str(round(paid, 2))
    item["due_amount"] = str(round(max(total - paid, 0.0), 2)) if total else ""

    # 节点
    milestones = item.get("milestones")
    if not isinstance(milestones, list) or not milestones:
        etd = item.get("etd") or ""
        offsets = {"deposit": -30, "po": -25, "midcheck": -15, "finalcheck": -7, "customs": -2, "arrived": 0}
        milestones = []
        for key, name in PRODUCTION_MILESTONES:
            milestones.append(
                {
                    "key": key,
                    "name": name,
                    "planned_date": _add_days(etd, offsets[key]) if etd else "",
                    "actual_date": "",
                    "status": "pending",
                    "note": "",
                    "owner": "",
                }
            )
    item["milestones"] = milestones
    done = [m for m in milestones if isinstance(m, dict) and m.get("status") == "done"]
    item["current_milestone"] = done[-1]["name"] if done else (milestones[0]["name"] if milestones else "")
    item["milestone_progress"] = round(len(done) / len(milestones), 3) if milestones else 0.0

    # 交期风险：按未完成节点的计划日与今天比较
    today = datetime.now().strftime("%Y-%m-%d")
    overdue_nodes = [
        m for m in milestones
        if isinstance(m, dict) and m.get("status") != "done" and (m.get("planned_date") or "") and m["planned_date"] < today
    ]
    delivery = item.get("delivery_date") or item.get("etd") or ""
    risk = 0.0
    if item.get("status") not in ("已签收", "已取消", "已完成"):
        risk = min(len(overdue_nodes) * 22.0, 88.0)
        if delivery and delivery < today:
            risk = min(risk + 30.0, 99.0)
    item["delay_risk"] = round(risk, 1)
    item["delayed_nodes"] = len(overdue_nodes)


class RuntimeStore:
    def __init__(self) -> None:
        self.path = Path(get_settings().storage_dir) / "runtime.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_or_init()

    def _load_or_init(self) -> dict[str, Any]:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("samples", [])
            if "vendors" not in data or not data.get("vendors"):
                data["vendors"] = load_vendors()
            data.setdefault("customers", load_customers())
            data.setdefault("quotations", load_quotations())
            data.setdefault("orders", load_orders())
            data.setdefault("followups", load_followups())
            for inq in data.get("inquiries") or []:
                from backend.services.seed_data import normalize_inquiry

                normalize_inquiry(inq)
            self._normalize_customers(data["customers"])
            self._normalize_vendors(data["vendors"])
            self._normalize_quotations(data.setdefault("quotations", load_quotations()))
            self._normalize_orders(data.setdefault("orders", load_orders()))
            self._enrich_memo_from_seed(
                data["customers"],
                load_customers(),
                (
                    "preferences",
                    "memo",
                    "company_address",
                    "website",
                    "timezone",
                    "payment_terms",
                    "preferred_incoterms",
                    "preferred_colors",
                    "preferred_materials",
                ),
            )
            self._enrich_memo_from_seed(
                data["vendors"],
                load_vendors(),
                (
                    "preferences",
                    "memo",
                    "colors",
                    "materials",
                    "finishes",
                    "logo_processes",
                    "custom_color",
                    "sample_lead_days",
                    "payment_terms",
                    "certifications",
                    "bulk_lead_days",
                    "capacity_note",
                ),
            )
            sample_seed = {
                "S-001": {
                    "color": "哑光黑",
                    "color_code": "近似 Pantone Black 7 C",
                    "material": "304不锈钢内胆 + 喷塑外壳",
                    "size_spec": "500ml / 高约 22cm",
                    "finish": "哑光喷塑",
                    "logo_process": "激光雕刻",
                    "logo_position": "杯身正面居中",
                    "sample_qty": "2",
                    "sample_fee": "￥80（可扣大货）",
                },
                "S-002": {
                    "color": "商务蓝",
                    "color_code": "Pantone 2945 C",
                    "material": "ABS+PC 外壳 / 锂电池",
                    "size_spec": "约 140×70×15mm",
                    "finish": "细砂触感",
                    "logo_process": "丝印单色白",
                    "logo_position": "机身正面",
                    "sample_qty": "3",
                    "sample_fee": "￥120",
                },
            }
            for s in data.get("samples") or []:
                _normalize_sample(s)
                seed = sample_seed.get(s.get("id") or "")
                if not seed:
                    continue
                for k, v in seed.items():
                    if not (s.get(k) or "").strip():
                        s[k] = v
            self._write(data)
            return data
        inquiries = load_inquiries()
        for item in inquiries:
            item.setdefault("status", "pending")
            item.setdefault("assignee", "")
            item.setdefault("pipeline", None)
            item.setdefault("approved_reply", "")
        customers = load_customers()
        vendors = load_vendors()
        data = {
            "inquiries": inquiries,
            "customers": customers,
            "vendors": vendors,
            "followups": load_followups(),
            "quotations": load_quotations(),
            "orders": load_orders(),
            "approvals": [],
            "audit": [],
            "samples": [
                {
                    "id": "S-001",
                    "inquiry_id": "INQ-001",
                    "customer_name": "Nordic Retail Group HQ",
                    "vendor_id": "V-YH01",
                    "vendor_name": "义乌星海家居礼品有限公司",
                    "product": "500ml 保温杯",
                    "color": "哑光黑",
                    "color_code": "近似 Pantone Black 7 C",
                    "material": "304不锈钢内胆 + 喷塑外壳",
                    "size_spec": "500ml / 高约 22cm",
                    "finish": "哑光喷塑",
                    "logo_process": "激光雕刻",
                    "logo_position": "杯身正面居中",
                    "sample_qty": "2",
                    "sample_fee": "￥80（可扣大货）",
                    "tracking_no": "",
                    "status": "待打样",
                    "eta": "2026-09-10",
                    "notes": "等 LOGO 矢量文件",
                },
                {
                    "id": "S-002",
                    "inquiry_id": "INQ-002",
                    "customer_name": "BrightWave Marketing",
                    "vendor_id": "V-SZ03",
                    "vendor_name": "深圳能量数码礼品有限公司",
                    "product": "10000mAh 充电宝",
                    "color": "商务蓝",
                    "color_code": "Pantone 2945 C",
                    "material": "ABS+PC 外壳 / 锂电池",
                    "size_spec": "约 140×70×15mm",
                    "finish": "细砂触感",
                    "logo_process": "丝印单色白",
                    "logo_position": "机身正面",
                    "sample_qty": "3",
                    "sample_fee": "￥120",
                    "tracking_no": "",
                    "status": "打样中",
                    "eta": "2026-09-12",
                    "notes": "需确认 UN38.3",
                },
            ],
            "templates": [
                {
                    "id": "TPL-01",
                    "name": "向海外要LOGO与数量确认",
                    "body": "Dear {name},\n\nThanks for the brief. To proceed with factory matching, please share logo artwork, final quantity, and target delivery date.\n\nBest regards\nChina Sourcing Team",
                },
                {
                    "id": "TPL-02",
                    "name": "催厂商报价",
                    "body": "您好，关于上次礼品询价，麻烦今天内给到参考单价、MOQ与交期，我们好回复海外同事，谢谢！",
                },
                {
                    "id": "TPL-03",
                    "name": "样品安排通知海外",
                    "body": "Dear {name},\n\nWe have arranged sampling with the shortlisted factory. ETA for sample photos / dispatch will follow within 2 business days.\n\nBest regards\nChina Sourcing Team",
                },
            ],
        }
        self._normalize_customers(data["customers"])
        self._normalize_vendors(data["vendors"])
        self._normalize_quotations(data["quotations"])
        self._normalize_orders(data["orders"])
        self._write(data)
        return data

    @staticmethod
    def _enrich_memo_from_seed(
        rows: list[dict],
        seed_rows: list[dict],
        fields: tuple[str, ...],
    ) -> None:
        by_id = {r.get("id"): r for r in seed_rows if r.get("id")}
        for item in rows:
            seed = by_id.get(item.get("id"))
            if not seed:
                continue
            for f in fields:
                if not (item.get(f) or "").strip() and (seed.get(f) or "").strip():
                    item[f] = seed[f]

    @staticmethod
    def _normalize_customers(rows: list[dict]) -> None:
        for item in rows:
            item.setdefault("phone", "")
            item.setdefault("company_address", "")
            item.setdefault("website", "")
            item.setdefault("timezone", "")
            item.setdefault("payment_terms", "")
            item.setdefault("preferred_incoterms", "")
            item.setdefault("preferred_colors", "")
            item.setdefault("preferred_materials", "")
            item.setdefault("preferences", "")
            item.setdefault("memo", "")
            item.setdefault("notes", "")
            item.setdefault("email", "")
            item.setdefault("channel", "email")
            item.setdefault("priority", "medium")
            item.setdefault("last_contact", "")
            tags = item.get("tags")
            if isinstance(tags, str):
                item["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            elif not isinstance(tags, list):
                item["tags"] = []
            _normalize_customer_ownership(item)

    @staticmethod
    def _normalize_quotations(rows: list[dict]) -> None:
        for item in rows:
            _normalize_quotation(item)

    @staticmethod
    def _normalize_orders(rows: list[dict]) -> None:
        for item in rows:
            _normalize_order(item)

    @staticmethod
    def _normalize_vendors(rows: list[dict]) -> None:
        for item in rows:
            item.setdefault("email", "")
            item.setdefault("phone", "")
            item.setdefault("region", "")
            item.setdefault("contact", "")
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
            cats = item.get("categories")
            if isinstance(cats, str):
                item["categories"] = [t.strip() for t in cats.split(",") if t.strip()]
            elif not isinstance(cats, list):
                item["categories"] = []

    def _parse_tags(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(t).strip() for t in value if str(t).strip()]
        if isinstance(value, str):
            return [t.strip() for t in value.replace("，", ",").replace("/", ",").split(",") if t.strip()]
        return []

    def _write(self, data: dict[str, Any] | None = None) -> None:
        payload = data if data is not None else self.data
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def reload_seed(self) -> None:
        with _lock:
            if self.path.exists():
                self.path.unlink()
            self.data = self._load_or_init()

    def list_inquiries(self, status: str | None = None) -> list[dict]:
        from backend.services.seed_data import normalize_inquiry

        for item in self.data["inquiries"]:
            normalize_inquiry(item)
        items = self.data["inquiries"]
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def get_inquiry(self, inquiry_id: str) -> dict | None:
        from backend.services.seed_data import normalize_inquiry

        for item in self.data["inquiries"]:
            if item["id"] == inquiry_id:
                normalize_inquiry(item)
                return deepcopy(item)
        return None

    def create_inquiry(self, payload: dict) -> dict:
        from backend.services.seed_data import normalize_inquiry

        with _lock:
            iid = (payload.get("id") or "").strip() or f"INQ-{uuid.uuid4().hex[:6].upper()}"
            row = normalize_inquiry(
                {
                    "id": iid,
                    "customer_id": (payload.get("customer_id") or "").strip(),
                    "customer_name": (payload.get("customer_name") or "").strip(),
                    "country": (payload.get("country") or "").strip(),
                    "from_email": (payload.get("from_email") or "").strip(),
                    "subject": (payload.get("subject") or "").strip() or "新建询盘",
                    "body": (payload.get("body") or "").strip(),
                    "received_at": (payload.get("received_at") or "").strip() or _now(),
                    "status": (payload.get("status") or "pending").strip(),
                    "assignee": (payload.get("assignee") or "").strip(),
                    "pipeline": payload.get("pipeline"),
                    "approved_reply": "",
                    "qty": str(payload.get("qty") or "").strip(),
                    "target_price": str(payload.get("target_price") or "").strip(),
                    "currency": (payload.get("currency") or "USD").strip(),
                    "incoterms": (payload.get("incoterms") or "FOB").strip(),
                    "destination": (payload.get("destination") or "").strip(),
                    "deadline": (payload.get("deadline") or "").strip(),
                    "product_name": (payload.get("product_name") or "").strip(),
                    "color": (payload.get("color") or "").strip(),
                    "material": (payload.get("material") or "").strip(),
                    "size_spec": (payload.get("size_spec") or "").strip(),
                    "priority": (payload.get("priority") or "medium").strip(),
                    "source_channel": (payload.get("source_channel") or "email").strip(),
                    "updated_at": _now(),
                }
            )
            self.data["inquiries"].insert(0, row)
            self._write()
            return deepcopy(row)

    def update_inquiry(self, inquiry_id: str, patch: dict) -> dict | None:
        from backend.services.seed_data import normalize_inquiry

        with _lock:
            for item in self.data["inquiries"]:
                if item["id"] == inquiry_id:
                    # 不允许用空字典冲掉关键字段以外的扩展字段
                    clean = {k: v for k, v in patch.items() if k != "id"}
                    item.update(clean)
                    item["updated_at"] = _now()
                    normalize_inquiry(item)
                    self._write()
                    return deepcopy(item)
        return None

    def add_audit(self, employee: str, action: str, target: str, detail: str = "") -> None:
        with _lock:
            self.data["audit"].insert(
                0,
                {
                    "id": f"AUD-{uuid.uuid4().hex[:8]}",
                    "time": _now(),
                    "employee": employee or "未命名",
                    "action": action,
                    "target": target,
                    "detail": detail,
                },
            )
            self.data["audit"] = self.data["audit"][:200]
            self._write()

    def create_approval(self, inquiry_id: str, draft: str, employee: str, meta: dict | None = None) -> dict:
        with _lock:
            item = {
                "id": f"APR-{uuid.uuid4().hex[:8]}",
                "inquiry_id": inquiry_id,
                "draft": draft,
                "status": "pending",
                "created_by": employee,
                "created_at": _now(),
                "reviewed_by": "",
                "reviewed_at": "",
                "final_text": "",
                "meta": meta or {},
            }
            self.data["approvals"].insert(0, item)
            for inq in self.data["inquiries"]:
                if inq["id"] == inquiry_id:
                    inq["status"] = "awaiting_approval"
            self._write()
            return deepcopy(item)

    def decide_approval(self, approval_id: str, approve: bool, employee: str, final_text: str = "") -> dict | None:
        with _lock:
            for item in self.data["approvals"]:
                if item["id"] == approval_id:
                    item["status"] = "approved" if approve else "rejected"
                    item["reviewed_by"] = employee
                    item["reviewed_at"] = _now()
                    item["final_text"] = final_text or item["draft"]
                    for inq in self.data["inquiries"]:
                        if inq["id"] == item["inquiry_id"]:
                            if approve:
                                inq["status"] = "sent"
                                inq["approved_reply"] = item["final_text"]
                            else:
                                inq["status"] = "pending"
                    self._write()
                    return deepcopy(item)
        return None

    def list_approvals(self, status: str | None = "pending") -> list[dict]:
        items = self.data["approvals"]
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def list_audit(self, limit: int = 50) -> list[dict]:
        return deepcopy(self.data["audit"][:limit])

    def list_customers(self) -> list[dict]:
        self._normalize_customers(self.data.setdefault("customers", []))
        for item in self.data["customers"]:
            item["recycle_deadline"] = _customer_recycle_deadline(item)
        return deepcopy(self.data["customers"])

    def get_customer(self, customer_id: str) -> dict | None:
        for item in self.data.setdefault("customers", []):
            if item.get("id") == customer_id:
                _normalize_customer_ownership(item)
                item["recycle_deadline"] = _customer_recycle_deadline(item)
                return deepcopy(item)
        return None

    def upsert_customer(self, payload: dict) -> dict:
        with _lock:
            rows = self.data.setdefault("customers", [])
            cid = (payload.get("id") or "").strip() or f"C-{uuid.uuid4().hex[:6]}"
            row = {
                "id": cid,
                "name": (payload.get("name") or "").strip(),
                "country": (payload.get("country") or "").strip(),
                "contact": (payload.get("contact") or "").strip(),
                "email": (payload.get("email") or "").strip(),
                "phone": (payload.get("phone") or "").strip(),
                "channel": (payload.get("channel") or "email").strip(),
                "tags": self._parse_tags(payload.get("tags")),
                "priority": (payload.get("priority") or "medium").strip(),
                "last_contact": (payload.get("last_contact") or "").strip(),
                "preferences": (payload.get("preferences") or "").strip(),
                "memo": (payload.get("memo") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
                "company_address": (payload.get("company_address") or "").strip(),
                "website": (payload.get("website") or "").strip(),
                "timezone": (payload.get("timezone") or "").strip(),
                "payment_terms": (payload.get("payment_terms") or "").strip(),
                "preferred_incoterms": (payload.get("preferred_incoterms") or "").strip(),
                "preferred_colors": (payload.get("preferred_colors") or "").strip(),
                "preferred_materials": (payload.get("preferred_materials") or "").strip(),
                "owner": (payload.get("owner") or "").strip(),
                "stage": (payload.get("stage") or "").strip(),
                "source": (payload.get("source") or "").strip(),
                "blacklist": bool(payload.get("blacklist", False)),
                "updated_at": _now(),
            }
            if not row["name"]:
                raise ValueError("客户名称不能为空")
            for i, item in enumerate(rows):
                if item.get("id") == cid:
                    # 编辑时不丢归属 / 认领时间 / 回收设置
                    row["owner"] = row["owner"] or str(item.get("owner") or "")
                    row["owner_id"] = str(item.get("owner_id") or "") if row["owner"] == item.get("owner") else ""
                    row["claimed_at"] = str(item.get("claimed_at") or "")
                    row["last_follow_at"] = str(item.get("last_follow_at") or "")
                    row["intake_at"] = str(item.get("intake_at") or "")
                    row["recycle_note"] = str(item.get("recycle_note") or "")
                    row["transfer_note"] = str(item.get("transfer_note") or "")
                    row["recycle_days"] = item.get("recycle_days", DEFAULT_RECYCLE_DAYS)
                    if not row["stage"]:
                        row["stage"] = str(item.get("stage") or "新询盘")
                    if not row["source"]:
                        row["source"] = str(item.get("source") or "")
                    self._normalize_customers([row])
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            row["recycle_days"] = DEFAULT_RECYCLE_DAYS
            if not row["stage"]:
                row["stage"] = "新询盘"
            self._normalize_customers([row])
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def delete_customer(self, customer_id: str) -> bool:
        with _lock:
            rows = self.data.setdefault("customers", [])
            before = len(rows)
            self.data["customers"] = [r for r in rows if r.get("id") != customer_id]
            if len(self.data["customers"]) == before:
                return False
            self._write()
            return True

    def list_vendors(self, active_only: bool = False) -> list[dict]:
        self.data.setdefault("vendors", load_vendors())
        self._normalize_vendors(self.data["vendors"])
        items = self.data["vendors"]
        if active_only:
            items = [v for v in items if v.get("active", True)]
        return deepcopy(items)

    def get_vendor(self, vendor_id: str) -> dict | None:
        for item in self.data.setdefault("vendors", []):
            if item.get("id") == vendor_id:
                return deepcopy(item)
        return None

    def upsert_vendor(self, payload: dict) -> dict:
        with _lock:
            rows = self.data.setdefault("vendors", [])
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
                "updated_at": _now(),
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
        with _lock:
            rows = self.data.setdefault("vendors", [])
            before = len(rows)
            self.data["vendors"] = [r for r in rows if r.get("id") != vendor_id]
            if len(self.data["vendors"]) == before:
                return False
            self._write()
            return True

    def list_followups(self, status: str | None = None) -> list[dict]:
        self.data.setdefault("followups", [])
        items = self.data["followups"]
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def upsert_followup(self, payload: dict) -> dict:
        with _lock:
            rows = self.data.setdefault("followups", [])
            fid = (payload.get("id") or "").strip() or f"FU-{uuid.uuid4().hex[:6]}"
            row = {
                "id": fid,
                "customer_id": (payload.get("customer_id") or "").strip(),
                "customer_name": (payload.get("customer_name") or "").strip(),
                "inquiry_id": (payload.get("inquiry_id") or "").strip(),
                "due_date": (payload.get("due_date") or "").strip(),
                "reason": (payload.get("reason") or "").strip(),
                "suggested_action": (payload.get("suggested_action") or "").strip(),
                "priority": (payload.get("priority") or "medium").strip(),
                "status": (payload.get("status") or "open").strip(),
                "updated_at": _now(),
            }
            if not row["customer_name"] and not row["reason"]:
                raise ValueError("请填写客户或跟进原因")
            for i, item in enumerate(rows):
                if item.get("id") == fid:
                    # 保留完成信息
                    row["done_by"] = item.get("done_by", "")
                    row["done_at"] = item.get("done_at", "")
                    if row["status"] != "done":
                        row["done_by"] = ""
                        row["done_at"] = ""
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def delete_followup(self, followup_id: str) -> bool:
        with _lock:
            rows = self.data.setdefault("followups", [])
            before = len(rows)
            self.data["followups"] = [r for r in rows if r.get("id") != followup_id]
            if len(self.data["followups"]) == before:
                return False
            self._write()
            return True

    def complete_followup(self, followup_id: str, employee: str) -> dict | None:
        with _lock:
            for item in self.data.setdefault("followups", []):
                if item["id"] == followup_id:
                    item["status"] = "done"
                    item["done_by"] = employee
                    item["done_at"] = _now()
                    self._write()
                    return deepcopy(item)
        return None

    def list_quotations(self, inquiry_id: str | None = None, status: str | None = None) -> list[dict]:
        self.data.setdefault("quotations", [])
        items = self.data["quotations"]
        self._normalize_quotations(items)
        if inquiry_id:
            items = [q for q in items if q.get("inquiry_id") == inquiry_id]
        if status:
            items = [q for q in items if q.get("status") == status]
        return deepcopy(items)

    def get_quotation(self, quotation_id: str) -> dict | None:
        for item in self.data.setdefault("quotations", []):
            if item.get("id") == quotation_id:
                _normalize_quotation(item)
                return deepcopy(item)
        return None

    def upsert_quotation(self, payload: dict) -> dict:
        with _lock:
            rows = self.data.setdefault("quotations", [])
            qid = (payload.get("id") or "").strip() or f"QT-{uuid.uuid4().hex[:6].upper()}"
            lines = payload.get("lines") or []
            if isinstance(lines, str):
                lines = []
            norm_lines = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                norm_lines.append(
                    {
                        "product": str(line.get("product") or "").strip(),
                        "color": str(line.get("color") or "").strip(),
                        "material": str(line.get("material") or "").strip(),
                        "qty": str(line.get("qty") or "").strip(),
                        "unit_price": str(line.get("unit_price") or "").strip(),
                        "moq": str(line.get("moq") or "").strip(),
                        "lead_days": str(line.get("lead_days") or "").strip(),
                        "notes": str(line.get("notes") or "").strip(),
                        "cost_price": str(line.get("cost_price") or "").strip(),
                        "floor_price": str(line.get("floor_price") or "").strip(),
                    }
                )
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
                "updated_at": _now(),
            }
            if existing:
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
                row["versions"] = versions[-12:]
                row["version"] = version
                row["boss_approved"] = bool(existing.get("boss_approved")) and not changed
            _normalize_quotation(row)
            if row.get("below_floor") and payload.get("approve_below_floor"):
                row["boss_approved"] = True
            if row.get("status") == "sent" and not row.get("sent_at"):
                row["sent_at"] = _now()
            for i, item in enumerate(rows):
                if item.get("id") == qid:
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def new_quotation_version(self, quotation_id: str, lines: list | None, employee: str = "", note: str = "") -> dict | None:
        """把当前版本归档，基于新明细生成下一版（保留历史，便于复盘为什么没成）。"""
        with _lock:
            for i, item in enumerate(self.data.setdefault("quotations", [])):
                if item.get("id") != quotation_id:
                    continue
                _normalize_quotation(item)
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
                item["versions"] = versions[-12:]
                item["version"] = int(item.get("version") or 1) + 1
                if lines:
                    item["lines"] = [
                        {
                            "product": str(l.get("product") or "").strip() if isinstance(l, dict) else "",
                            "color": str(l.get("color") or "").strip() if isinstance(l, dict) else "",
                            "material": str(l.get("material") or "").strip() if isinstance(l, dict) else "",
                            "qty": str(l.get("qty") or "").strip() if isinstance(l, dict) else "",
                            "unit_price": str(l.get("unit_price") or "").strip() if isinstance(l, dict) else "",
                            "moq": str(l.get("moq") or "").strip() if isinstance(l, dict) else "",
                            "lead_days": str(l.get("lead_days") or "").strip() if isinstance(l, dict) else "",
                            "notes": str(l.get("notes") or "").strip() if isinstance(l, dict) else "",
                            "cost_price": str(l.get("cost_price") or "").strip() if isinstance(l, dict) else "",
                            "floor_price": str(l.get("floor_price") or "").strip() if isinstance(l, dict) else "",
                        }
                        for l in lines
                        if isinstance(l, dict)
                    ]
                item["total"] = _quote_total(item)
                if note:
                    item["notes"] = note
                item["status"] = "draft"
                item["boss_approved"] = False
                item["updated_by"] = employee or item.get("updated_by", "")
                item["updated_at"] = _now()
                _normalize_quotation(item)
                self.data["quotations"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def delete_quotation(self, quotation_id: str) -> bool:
        with _lock:
            rows = self.data.setdefault("quotations", [])
            before = len(rows)
            self.data["quotations"] = [r for r in rows if r.get("id") != quotation_id]
            if len(self.data["quotations"]) == before:
                return False
            self._write()
            return True

    def list_orders(self, status: str | None = None) -> list[dict]:
        self.data.setdefault("orders", [])
        items = self.data["orders"]
        self._normalize_orders(items)
        if status:
            items = [o for o in items if o.get("status") == status]
        return deepcopy(items)

    def get_order(self, order_id: str) -> dict | None:
        for item in self.data.setdefault("orders", []):
            if item.get("id") == order_id:
                _normalize_order(item)
                return deepcopy(item)
        return None

    def upsert_order(self, payload: dict) -> dict:
        with _lock:
            rows = self.data.setdefault("orders", [])
            oid = (payload.get("id") or "").strip() or f"PO-{uuid.uuid4().hex[:6].upper()}"
            existing = None
            for item in rows:
                if item.get("id") == oid:
                    existing = item
                    break
            row = {
                "id": oid,
                "inquiry_id": (payload.get("inquiry_id") or "").strip(),
                "quotation_id": (payload.get("quotation_id") or "").strip(),
                "customer_id": (payload.get("customer_id") or "").strip(),
                "customer_name": (payload.get("customer_name") or "").strip(),
                "vendor_id": (payload.get("vendor_id") or "").strip(),
                "vendor_name": (payload.get("vendor_name") or "").strip(),
                "product": (payload.get("product") or "").strip(),
                "color": (payload.get("color") or "").strip(),
                "material": (payload.get("material") or "").strip(),
                "qty": str(payload.get("qty") or "").strip(),
                "unit_price": str(payload.get("unit_price") or "").strip(),
                "currency": (payload.get("currency") or "USD").strip(),
                "deposit": (payload.get("deposit") or "").strip(),
                "deposit_due": (payload.get("deposit_due") or "").strip(),
                "delivery_date": (payload.get("delivery_date") or "").strip(),
                "status": (payload.get("status") or "待定金").strip(),
                "etd": (payload.get("etd") or "").strip(),
                "tracking_no": (payload.get("tracking_no") or "").strip(),
                "notes": (payload.get("notes") or "").strip(),
                "payments": payload.get("payments") if isinstance(payload.get("payments"), list) else [],
                "milestones": payload.get("milestones") if isinstance(payload.get("milestones"), list) else [],
                "owner": (payload.get("owner") or "").strip(),
                "updated_at": _now(),
            }
            if not row["product"] and not row["customer_name"]:
                raise ValueError("请填写产品或客户")
            if existing:
                if not row["payments"]:
                    row["payments"] = existing.get("payments") or []
                if not row["milestones"]:
                    row["milestones"] = existing.get("milestones") or []
                row["delivery_date"] = row["delivery_date"] or (existing.get("delivery_date") or "")
                row["deposit_due"] = row["deposit_due"] or (existing.get("deposit_due") or "")
                row["owner"] = row["owner"] or (existing.get("owner") or "")
            _normalize_order(row)
            for i, item in enumerate(rows):
                if item.get("id") == oid:
                    rows[i] = row
                    self._write()
                    return deepcopy(row)
            rows.insert(0, row)
            self._write()
            return deepcopy(row)

    def record_payment(
        self,
        order_id: str,
        payment_id: str,
        amount: float = 0.0,
        method: str = "",
        note: str = "",
        employee: str = "",
    ) -> dict | None:
        """登记一笔收款：更新该期收款状态与订单已收/未收金额。"""
        with _lock:
            for i, item in enumerate(self.data.setdefault("orders", [])):
                if item.get("id") != order_id:
                    continue
                _normalize_order(item)
                hit = False
                for p in item.get("payments") or []:
                    if not isinstance(p, dict):
                        continue
                    if payment_id and p.get("id") != payment_id:
                        continue
                    if payment_id == "" and p.get("status") == "paid":
                        continue
                    paid = _to_float(amount, 0.0) or _to_float(p.get("amount"), 0.0)
                    p["paid_amount"] = round(paid, 2)
                    p["status"] = "paid"
                    p["paid_at"] = _now()
                    p["method"] = method or p.get("method") or ""
                    p["note"] = note or p.get("note") or ""
                    p["recorded_by"] = employee
                    hit = True
                    break
                if not hit:
                    return None
                item["milestone_note"] = ""
                _normalize_order(item)
                # 定金到账自动推进第一个节点
                if item.get("payments") and str(item["payments"][0].get("status")) == "paid":
                    for m in item.get("milestones") or []:
                        if isinstance(m, dict) and m.get("key") == "deposit" and m.get("status") != "done":
                            m["status"] = "done"
                            m["actual_date"] = _now()[:10]
                            m["owner"] = employee
                    _normalize_order(item)
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def advance_milestone(
        self,
        order_id: str,
        key: str,
        employee: str = "",
        actual_date: str = "",
        note: str = "",
        status: str = "done",
    ) -> dict | None:
        """推进生产节点；推进后自动刷新交期风险与订单状态。"""
        with _lock:
            for i, item in enumerate(self.data.setdefault("orders", [])):
                if item.get("id") != order_id:
                    continue
                _normalize_order(item)
                for m in item.get("milestones") or []:
                    if not isinstance(m, dict) or m.get("key") != key:
                        continue
                    m["status"] = status
                    if status == "done":
                        m["actual_date"] = actual_date or _now()[:10]
                    m["owner"] = employee or m.get("owner") or ""
                    if note:
                        m["note"] = note
                _normalize_order(item)
                # 节点推进联动订单状态
                keys_done = {m.get("key") for m in item.get("milestones") or [] if isinstance(m, dict) and m.get("status") == "done"}
                if "arrived" in keys_done:
                    item["status"] = "已签收"
                elif "customs" in keys_done:
                    item["status"] = "已出货"
                elif "po" in keys_done:
                    item["status"] = "生产中"
                elif "deposit" in keys_done:
                    item["status"] = "生产中"
                _normalize_order(item)
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def update_order_meta(self, order_id: str, patch: dict) -> dict | None:
        """更新订单附加字段（交期、定金到期等）。"""
        with _lock:
            for i, item in enumerate(self.data.setdefault("orders", [])):
                if item.get("id") != order_id:
                    continue
                allowed = {"delivery_date", "deposit_due", "etd", "status", "notes", "owner", "tracking_no"}
                for k, v in (patch or {}).items():
                    if k in allowed:
                        item[k] = str(v or "").strip() if not isinstance(v, (int, float)) else v
                _normalize_order(item)
                item["updated_at"] = _now()
                self.data["orders"][i] = item
                self._write()
                return deepcopy(item)
        return None

    def collections_board(self) -> dict:
        """应收看板：按订单汇总已收/未收/逾期，并给出催款清单。"""
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        total_due = 0.0
        total_overdue = 0.0
        for o in self.list_orders():
            if o.get("status") in ("已取消",):
                continue
            due = _to_float(o.get("due_amount"), 0.0)
            if due <= 0 and _to_float(o.get("total_amount"), 0.0) <= 0:
                continue
            overdue_items = []
            overdue_amt = 0.0
            next_due = ""
            for p in o.get("payments") or []:
                if not isinstance(p, dict) or p.get("status") == "paid":
                    continue
                pd = p.get("due_date") or ""
                if pd and pd < today:
                    overdue_items.append(p)
                    overdue_amt += _to_float(p.get("amount"), 0.0) - _to_float(p.get("paid_amount"), 0.0)
                if pd and (not next_due or pd < next_due):
                    next_due = pd
            row = {
                "id": o.get("id"),
                "customer_name": o.get("customer_name"),
                "product": o.get("product"),
                "currency": o.get("currency"),
                "total_amount": o.get("total_amount") or "",
                "paid_amount": o.get("paid_amount") or "0",
                "due_amount": o.get("due_amount") or "0",
                "status": o.get("status"),
                "owner": o.get("owner") or "",
                "payments": o.get("payments") or [],
                "overdue_count": len(overdue_items),
                "overdue_amount": str(round(overdue_amt, 2)) if overdue_amt else "0",
                "next_due_date": next_due,
                "is_overdue": bool(overdue_items),
                "etd": o.get("etd") or "",
            }
            total_due += due
            total_overdue += overdue_amt
            rows.append(row)
        rows.sort(key=lambda r: (not r["is_overdue"], r["next_due_date"] or "9999"))
        return {
            "rows": rows,
            "summary": {
                "order_count": len(rows),
                "total_due": str(round(total_due, 2)),
                "total_overdue": str(round(total_overdue, 2)),
                "overdue_orders": sum(1 for r in rows if r["is_overdue"]),
            },
        }

    def tracking_board(self) -> dict:
        """生产跟单看板：在产订单 + 交期红绿灯。"""
        today = datetime.now().strftime("%Y-%m-%d")
        rows = []
        for o in self.list_orders():
            if o.get("status") in ("已签收", "已取消"):
                continue
            risk = _to_float(o.get("delay_risk"), 0.0)
            light = "green"
            if risk >= 60:
                light = "red"
            elif risk >= 25:
                light = "amber"
            nodes = o.get("milestones") or []
            rows.append(
                {
                    "id": o.get("id"),
                    "customer_name": o.get("customer_name"),
                    "product": o.get("product"),
                    "qty": o.get("qty"),
                    "vendor_name": o.get("vendor_name"),
                    "status": o.get("status"),
                    "etd": o.get("etd") or "",
                    "delivery_date": o.get("delivery_date") or "",
                    "current_milestone": o.get("current_milestone") or "",
                    "milestone_progress": o.get("milestone_progress") or 0,
                    "milestones": nodes,
                    "delay_risk": risk,
                    "delayed_nodes": o.get("delayed_nodes") or 0,
                    "light": light,
                }
            )
        order = {"red": 0, "amber": 1, "green": 2}
        rows.sort(key=lambda r: order.get(r["light"], 3))
        return {
            "rows": rows,
            "summary": {
                "in_production": len(rows),
                "red": sum(1 for r in rows if r["light"] == "red"),
                "amber": sum(1 for r in rows if r["light"] == "amber"),
                "green": sum(1 for r in rows if r["light"] == "green"),
                "today": today,
            },
        }

    # ------------------------------------------------------------------
    # 客户公海 / 私海
    # ------------------------------------------------------------------

    def customer_pool_board(self) -> dict:
        """公海私海看板：私海归属、回收倒计时、公海可认领。"""
        today = datetime.now().strftime("%Y-%m-%d")
        customers = self.list_customers()
        private, public = [], []
        for c in customers:
            deadline = _customer_recycle_deadline(c)
            days_left = ""
            if deadline:
                try:
                    d1 = datetime.strptime(deadline, "%Y-%m-%d")
                    d2 = datetime.strptime(today, "%Y-%m-%d")
                    days_left = (d1 - d2).days
                except Exception:
                    days_left = ""
            enriched = {
                **c,
                "recycle_deadline": deadline,
                "days_left": days_left,
                "need_attention": isinstance(days_left, int) and days_left <= 3,
                "is_public": not c.get("owner"),
            }
            (public if enriched["is_public"] else private).append(enriched)
        private.sort(key=lambda x: (x["days_left"] if isinstance(x["days_left"], int) else 9999))
        public.sort(key=lambda x: x.get("intake_at") or "", reverse=True)
        owners: dict[str, int] = {}
        for c in private:
            owners[c.get("owner") or "未分配"] = owners.get(c.get("owner") or "未分配", 0) + 1
        return {
            "private": private,
            "public": public,
            "summary": {
                "total": len(customers),
                "private_count": len(private),
                "public_count": len(public),
                "need_attention": sum(1 for c in private if c.get("need_attention")),
                "owners": owners,
                "today": today,
            },
        }

    def claim_customer(self, customer_id: str, employee: str, employee_id: str = "") -> dict | None:
        with _lock:
            for item in self.data.setdefault("customers", []):
                if item.get("id") != customer_id:
                    continue
                if item.get("owner"):
                    raise ValueError(f"该客户已归属 {item.get('owner')}，需由经理转移")
                item["owner"] = employee
                item["owner_id"] = employee_id
                item["claimed_at"] = _now()
                item["last_follow_at"] = _now()[:10]
                _normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def release_customer(self, customer_id: str, employee: str = "") -> dict | None:
        """把客户放回公海（业务员主动释放，或经理强制）。"""
        with _lock:
            for item in self.data.setdefault("customers", []):
                if item.get("id") != customer_id:
                    continue
                item["owner"] = ""
                item["owner_id"] = ""
                item["claimed_at"] = ""
                _normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def transfer_customer(self, customer_id: str, to_employee: str, by: str = "") -> dict | None:
        """经理把客户转移/分配给某个业务员。"""
        if not to_employee:
            raise ValueError("请指定接收的业务员")
        with _lock:
            for item in self.data.setdefault("customers", []):
                if item.get("id") != customer_id:
                    continue
                prev = item.get("owner") or "公海"
                item["owner"] = to_employee
                item["claimed_at"] = _now()
                item["last_follow_at"] = _now()[:10]
                item["transfer_note"] = f"{by or '系统'}：{prev} → {to_employee}"
                _normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def recycle_customers(self, days: int | None = None, by: str = "") -> dict:
        """扫描私海客户，超过回收天数且无新跟进的自动回公海。"""
        today = datetime.now().strftime("%Y-%m-%d")
        recycled = []
        with _lock:
            for item in self.data.setdefault("customers", []):
                if not item.get("owner"):
                    continue
                _normalize_customer_ownership(item)
                limit = days if days else int(item.get("recycle_days") or DEFAULT_RECYCLE_DAYS)
                anchor = item.get("last_follow_at") or item.get("claimed_at") or item.get("intake_at") or ""
                if not anchor:
                    continue
                deadline = _add_days(anchor, limit)
                if deadline and deadline < today:
                    recycled.append({"id": item.get("id"), "name": item.get("name"), "owner": item.get("owner")})
                    item["owner"] = ""
                    item["owner_id"] = ""
                    item["claimed_at"] = ""
                    item["recycle_note"] = f"{by or '系统'} 于 {today} 自动回收（{limit} 天未跟进）"
                    _normalize_customer_ownership(item)
            if recycled:
                self._write()
        return {"recycled": recycled, "count": len(recycled)}

    def touch_customer(self, customer_id: str, employee: str = "") -> dict | None:
        """刷新客户最近跟进时间（防止被回收）。"""
        with _lock:
            for item in self.data.setdefault("customers", []):
                if item.get("id") != customer_id:
                    continue
                item["last_follow_at"] = _now()[:10]
                item["last_contact"] = item.get("last_contact") or item["last_follow_at"]
                _normalize_customer_ownership(item)
                self._write()
                return deepcopy(item)
        return None

    def delete_order(self, order_id: str) -> bool:
        with _lock:
            rows = self.data.setdefault("orders", [])
            before = len(rows)
            self.data["orders"] = [r for r in rows if r.get("id") != order_id]
            if len(self.data["orders"]) == before:
                return False
            self._write()
            return True

    def related_for_customer(self, customer_id: str = "", customer_name: str = "") -> dict:
        def match(row: dict) -> bool:
            if customer_id and row.get("customer_id") == customer_id:
                return True
            if customer_name and row.get("customer_name") == customer_name:
                return True
            return False

        inqs = [i for i in self.list_inquiries() if match(i)]
        samples = [s for s in self.list_samples() if match(s)]
        quotes = [q for q in self.list_quotations() if match(q)]
        orders = [o for o in self.list_orders() if match(o)]
        return {
            "inquiries": inqs[:8],
            "samples": samples[:8],
            "quotations": quotes[:8],
            "orders": orders[:8],
            "counts": {
                "inquiries": len(inqs),
                "samples": len(samples),
                "quotations": len(quotes),
                "orders": len(orders),
            },
        }

    def related_for_vendor(self, vendor_id: str = "", vendor_name: str = "") -> dict:
        def match(row: dict) -> bool:
            if vendor_id and row.get("vendor_id") == vendor_id:
                return True
            if vendor_name and row.get("vendor_name") == vendor_name:
                return True
            return False

        samples = [s for s in self.list_samples() if match(s)]
        quotes = [q for q in self.list_quotations() if match(q)]
        orders = [o for o in self.list_orders() if match(o)]
        return {
            "samples": samples[:8],
            "quotations": quotes[:8],
            "orders": orders[:8],
            "counts": {
                "samples": len(samples),
                "quotations": len(quotes),
                "orders": len(orders),
            },
        }

    def list_templates(self) -> list[dict]:
        return deepcopy(self.data["templates"])

    def list_samples(self, status: str | None = None) -> list[dict]:
        self.data.setdefault("samples", [])
        for item in self.data["samples"]:
            _normalize_sample(item)
        items = self.data["samples"]
        if status:
            items = [i for i in items if i.get("status") == status]
        return deepcopy(items)

    def upsert_sample(self, payload: dict) -> dict:
        self.data.setdefault("samples", [])
        with _lock:
            sid = payload.get("id") or f"S-{uuid.uuid4().hex[:6]}"
            existing = None
            for item in self.data["samples"]:
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
                "color": (payload.get("color") or "").strip(),
                "color_code": (payload.get("color_code") or "").strip(),
                "material": (payload.get("material") or "").strip(),
                "size_spec": (payload.get("size_spec") or "").strip(),
                "finish": (payload.get("finish") or "").strip(),
                "logo_process": (payload.get("logo_process") or "").strip(),
                "logo_position": (payload.get("logo_position") or "").strip(),
                "sample_qty": str(payload.get("sample_qty") or "").strip(),
                "sample_fee": (payload.get("sample_fee") or "").strip(),
                "tracking_no": (payload.get("tracking_no") or "").strip(),
                "status": payload.get("status", "待打样"),
                "eta": payload.get("eta", ""),
                "notes": payload.get("notes", ""),
                "updated_at": _now(),
            }
            if existing:
                existing.update(row)
                self._write()
                return deepcopy(existing)
            self.data["samples"].insert(0, row)
            self._write()
            return deepcopy(row)

    def dashboard(self) -> dict:
        from datetime import datetime

        inquiries = self.data["inquiries"]
        followups = self.data.setdefault("followups", [])
        approvals = self.data["approvals"]
        samples = self.data.get("samples") or []
        quotations = self.data.get("quotations") or []
        orders = self.data.get("orders") or []
        today = datetime.now().strftime("%Y-%m-%d")

        def is_overdue(f: dict) -> bool:
            if f.get("status") == "done":
                return False
            due = (f.get("due_date") or "").strip()
            return bool(due and due < today)

        overdue_followups = [f for f in followups if is_overdue(f)]
        open_samples = [s for s in samples if s.get("status") not in ("已确认", "已取消", "海外已确认")]
        draft_quotes = [q for q in quotations if q.get("status") in ("draft", "sent")]
        active_orders = [o for o in orders if o.get("status") in ("待定金", "生产中", "已出货")]

        todos = []
        for f in overdue_followups[:5]:
            todos.append(
                {
                    "type": "followup",
                    "title": f"逾期跟进：{f.get('customer_name') or '-'}",
                    "detail": f.get("reason") or "",
                    "link": "/followups",
                    "id": f.get("id"),
                }
            )
        for i in sorted(
            [x for x in inquiries if x.get("status") == "pending"],
            key=lambda x: x.get("received_at", ""),
            reverse=True,
        )[:5]:
            todos.append(
                {
                    "type": "inquiry",
                    "title": f"待处理询盘：{i.get('subject') or i.get('id')}",
                    "detail": i.get("customer_name") or "",
                    "link": f"/inbox/{i.get('id')}",
                    "id": i.get("id"),
                }
            )
        for s in open_samples[:3]:
            todos.append(
                {
                    "type": "sample",
                    "title": f"样品进行中：{s.get('product') or s.get('id')}",
                    "detail": f"{s.get('status')} · ETA {s.get('eta') or '-'}",
                    "link": "/samples",
                    "id": s.get("id"),
                }
            )

        # P0 跑单指标
        pool = self.customer_pool_board()
        collections = self.collections_board()
        tracking = self.tracking_board()
        self._normalize_quotations(quotations)
        below_floor = [
            q for q in quotations
            if q.get("below_floor") and not q.get("boss_approved")
        ]

        return {
            "pending_inquiries": sum(1 for i in inquiries if i.get("status") == "pending"),
            "awaiting_approval": sum(1 for i in inquiries if i.get("status") == "awaiting_approval"),
            "sent_today": sum(1 for i in inquiries if i.get("status") == "sent"),
            "open_followups": sum(1 for f in followups if f.get("status") != "done"),
            "overdue_followups": len(overdue_followups),
            "pending_approvals": sum(1 for a in approvals if a.get("status") == "pending"),
            "open_samples": len(open_samples),
            "draft_quotations": len(draft_quotes),
            "active_orders": len(active_orders),
            "customers": len(self.data.get("customers") or []),
            "vendors": len(self.data.get("vendors") or []),
            "pool_public": pool["summary"]["public_count"],
            "pool_attention": pool["summary"]["need_attention"],
            "overdue_collections": collections["summary"]["overdue_orders"],
            "overdue_amount": collections["summary"]["total_overdue"],
            "delay_red": tracking["summary"]["red"],
            "delay_amber": tracking["summary"]["amber"],
            "below_floor_quotes": len(below_floor),
            "below_floor_items": deepcopy(below_floor[:5]),
            "recent_audit": deepcopy(self.data["audit"][:8]),
            "hot_inquiries": deepcopy(
                sorted(
                    [i for i in inquiries if i.get("status") in ("pending", "awaiting_approval", "processed")],
                    key=lambda x: x.get("received_at", ""),
                    reverse=True,
                )[:8]
            ),
            "todos": todos[:12],
            "overdue_followup_items": deepcopy(overdue_followups[:8]),
        }


_store: RuntimeStore | None = None


def get_store() -> RuntimeStore:
    global _store
    if _store is None:
        _store = RuntimeStore()
    return _store
