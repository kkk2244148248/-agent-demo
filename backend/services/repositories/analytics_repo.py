"""聚合看板与跨域关联查询：首页指标、客户/厂商 360° 视图。"""
from __future__ import annotations

from copy import deepcopy

from backend.services.repositories.utils import now_str, today_str


class AnalyticsRepo:
    """只读聚合层。

    刻意不放任何写逻辑：看板数字不对时，问题一定出在
    它依赖的 customer_repo / order_repo / quotation_repo，
    而不是「看板自己算错了」——这是排查成本最低的切法。
    """

    def _inquiries(self) -> list[dict]:
        return self.data.setdefault("inquiries", [])

    def dashboard(self) -> dict:
        inquiries = self._inquiries()
        followups = self.data.setdefault("followups", [])
        approvals = self.data.setdefault("approvals", [])
        samples = self.data.get("samples") or []
        quotations = self.data.get("quotations") or []
        orders = self.data.get("orders") or []
        today = today_str()

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

        # P0 跑单指标复用各域看板，避免同一套口径写两遍
        pool = self.customer_pool_board()
        collections = self.collections_board()
        tracking = self.tracking_board()
        self._normalize_quotations(quotations)
        below_floor = [q for q in quotations if q.get("below_floor") and not q.get("boss_approved")]

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

    # ------------------------------------------------------------------
    # 跨域关联（客户/厂商 360° 视图）
    # ------------------------------------------------------------------

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
        return deepcopy(self.data.setdefault("templates", []))
