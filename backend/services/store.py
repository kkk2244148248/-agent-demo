"""运行时状态持久化：加锁 + 落盘 + 对外单例。

    RuntimeStore 的职责被刻意收窄成三件事：

    1. 决定数据存哪（`storage/runtime.json`）与首次如何播种；
    2. 提供一把进程内的写锁，保证「读-改-写」不会互相覆盖；
    3. 提供 `_write()` 把内存状态刷回磁盘。

    所有业务规则都在 `backend/services/repositories/` 下的各域仓储里。
    这样安排的原因：单机 JSON 存储的代价是「写是全局的」，但业务的复杂度
    在领域规则上。把规则抽到无 IO 的纯函数后，针对底价、回收倒计时的
    单元测试就不必真的去写文件。

升级路径：把 `_write()` 换成数据库事务、把 `_lock` 换成行级锁或乐观版本号，
各域仓储的业务代码可以原样保留。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.services.repositories import StoreMixin
from backend.services.repositories.customer_repo import CustomerRepo
from backend.services.repositories.normalizers import (
    SAMPLE_SPEC_FIELDS,
    customer_recycle_deadline,
    normalize_customer_ownership,
    normalize_order,
    normalize_quotation,
    normalize_sample,
    quote_total,
    recompute_quote_floor,
)
from backend.services.repositories.utils import add_days, now_str, to_float
from backend.services.repositories.vendor_repo import VendorRepo
from backend.services.seed_data import (
    load_customers,
    load_followups,
    load_inquiries,
    load_orders,
    load_quotations,
    load_vendors,
)

# 兼容旧引用：这些常量原先定义在本模块，外部可能直接从 store 导入
from backend.services.repositories.constants import (  # noqa: F401
    CUSTOMER_STAGES,
    DEFAULT_PAYMENT_PLAN,
    DEFAULT_RECYCLE_DAYS,
    PRODUCTION_MILESTONES,
)

# 首次运行时写入的样品种子（礼品打样最常出错的字段都留了示例值）
_SAMPLE_SEED_SPECS = {
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


class RuntimeStore(StoreMixin):
    """单机 JSON 存储。所有域仓储都通过本类暴露给上层。"""

    def __init__(self) -> None:
        self.path = Path(get_settings().storage_dir) / "runtime.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load_or_init()

    # ------------------------------------------------------------------
    # 基础设施：加载 / 播种 / 落盘
    # ------------------------------------------------------------------

    def _load_or_init(self) -> dict[str, Any]:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._migrate(data)
            self._write(data)
            return data
        data = self._seed()
        self._write(data)
        return data

    def _migrate(self, data: dict[str, Any]) -> None:
        """把历史 runtime.json 补齐成当前结构（幂等，可反复执行）。

        真实项目里这一步通常会被抽成 alembic 之类的迁移脚本；
        单机 JSON 场景下用「setdefault + 重算派生字段」已经够用。
        """
        data.setdefault("samples", [])
        if "vendors" not in data or not data.get("vendors"):
            data["vendors"] = load_vendors()
        data.setdefault("customers", load_customers())
        data.setdefault("quotations", load_quotations())
        data.setdefault("orders", load_orders())
        data.setdefault("followups", load_followups())

        from backend.services.seed_data import normalize_inquiry

        for inq in data.get("inquiries") or []:
            normalize_inquiry(inq)

        self._normalize_customers(data["customers"])
        self._normalize_vendors(data["vendors"])
        self._normalize_quotations(data.setdefault("quotations", load_quotations()))
        self._normalize_orders(data.setdefault("orders", load_orders()))

        # 种子里补充的备注类字段，回填到用户已有的记录上（用户手填的不覆盖）
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
        for s in data.get("samples") or []:
            normalize_sample(s)
            seed = _SAMPLE_SEED_SPECS.get(s.get("id") or "")
            if not seed:
                continue
            for k, v in seed.items():
                if not (s.get(k) or "").strip():
                    s[k] = v

    def _seed(self) -> dict[str, Any]:
        """首次运行：从 seed_data 播种一份可直接演示的数据集。"""
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
                    "tracking_no": "",
                    "status": "待打样",
                    "eta": "2026-09-10",
                    "notes": "等 LOGO 矢量文件",
                    **_SAMPLE_SEED_SPECS["S-001"],
                },
                {
                    "id": "S-002",
                    "inquiry_id": "INQ-002",
                    "customer_name": "BrightWave Marketing",
                    "vendor_id": "V-SZ03",
                    "vendor_name": "深圳能量数码礼品有限公司",
                    "product": "10000mAh 充电宝",
                    "tracking_no": "",
                    "status": "打样中",
                    "eta": "2026-09-12",
                    "notes": "需确认 UN38.3",
                    **_SAMPLE_SEED_SPECS["S-002"],
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

    # 注意：`_lock` 是类属性，所有实例共享同一把写锁。
    # 单进程部署下这正是我们要的；多进程部署需改为文件锁或外部存储。
    _lock = threading.Lock()

    # -- 各域规范化入口（薄委托，供本模块与旧调用方使用） ----------------

    @staticmethod
    def _normalize_customers(rows: list[dict]) -> None:
        CustomerRepo._normalize_many(rows)

    @staticmethod
    def _normalize_vendors(rows: list[dict]) -> None:
        VendorRepo._normalize_many(rows)

    @staticmethod
    def _normalize_quotations(rows: list[dict]) -> None:
        for item in rows:
            normalize_quotation(item)

    @staticmethod
    def _normalize_orders(rows: list[dict]) -> None:
        for item in rows:
            normalize_order(item)

    def _write(self, data: dict[str, Any] | None = None) -> None:
        payload = data if data is not None else self.data
        # 先写临时文件再原子替换，避免进程中断留下半截 JSON
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    def reload_seed(self) -> None:
        """清空运行时数据并从种子重建（演示/测试用）。"""
        with _lock:
            if self.path.exists():
                self.path.unlink()
            self.data = self._load_or_init()

    # ------------------------------------------------------------------
    # 兼容旧接口
    # ------------------------------------------------------------------

    def save(self) -> None:
        """显式落盘（旧代码可能直接调用）。"""
        with _lock:
            self._write()

    @property
    def updated_at(self) -> str:
        return now_str()


_store: RuntimeStore | None = None


def get_store() -> RuntimeStore:
    global _store
    if _store is None:
        _store = RuntimeStore()
    return _store


def reset_store() -> None:
    """丢弃单例，主要给测试用。"""
    global _store
    _store = None


# ---------------------------------------------------------------------------
# 向后兼容：这些私有辅助原先定义在本模块，现已迁到 repositories 下。
# 保留同名别名，避免任何历史脚本 import 时直接报错。
# ---------------------------------------------------------------------------
_now = now_str
_to_float = to_float
_add_days = add_days
_customer_recycle_deadline = customer_recycle_deadline
_normalize_customer_ownership = normalize_customer_ownership
_recompute_quote_floor = recompute_quote_floor
_quote_total = quote_total
_SAMPLE_SPEC_FIELDS = SAMPLE_SPEC_FIELDS

__all__ = [
    "RuntimeStore",
    "get_store",
    "reset_store",
    "CUSTOMER_STAGES",
    "DEFAULT_PAYMENT_PLAN",
    "DEFAULT_RECYCLE_DAYS",
    "PRODUCTION_MILESTONES",
]
