"""把各业务域仓储组合成一个 `StoreMixin`，供 `RuntimeStore` 继承。

这里只做组装，不写业务逻辑。每个 Repo 都依赖宿主提供的三样东西：
`self.data`（内存数据）、`self._lock`（写锁）、`self._write()`（落盘）。
"""
from __future__ import annotations

from backend.services.repositories.analytics_repo import AnalyticsRepo
from backend.services.repositories.audit_repo import ApprovalRepo, AuditRepo
from backend.services.repositories.customer_repo import CustomerRepo
from backend.services.repositories.followup_repo import FollowupRepo
from backend.services.repositories.inquiry_repo import InquiryRepo
from backend.services.repositories.order_repo import OrderRepo
from backend.services.repositories.quotation_repo import QuotationRepo
from backend.services.repositories.sample_repo import SampleRepo
from backend.services.repositories.vendor_repo import VendorRepo


class StoreMixin(
    InquiryRepo,
    CustomerRepo,
    VendorRepo,
    FollowupRepo,
    QuotationRepo,
    OrderRepo,
    SampleRepo,
    ApprovalRepo,
    AuditRepo,
    AnalyticsRepo,
):
    """所有域仓储的并集。MRO 中各域方法名互不冲突，组合安全。"""

    def _parse_tags(self, value):
        """跨域共用的小工具：客户与厂商的标签/品类字段解析。"""
        from backend.services.repositories.utils import parse_tags

        return parse_tags(value)
