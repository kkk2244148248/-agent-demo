"""API 路由包：按业务域拆分，统一在 app.py 里 include_router。

    system.py     健康检查、看板、审计、模板
    auth.py       登录鉴权与账号管理
    inquiries.py  询盘 + Agent 流水线 + 审批闸门
    agents.py     Agent 总控、工具目录、文档解析
    customers.py  客户公海私海 + 跟进单
    vendors.py    厂商名录
    quotations.py 报价版本化与底价特批
    orders.py     订单、收款、生产跟单
    samples.py    打样台账
    knowledge.py  RAG 知识库与助手状态
"""
from backend.api.routers import (
    agents,
    auth,
    customers,
    inquiries,
    knowledge,
    orders,
    quotations,
    samples,
    system,
    vendors,
)

# include_router 的顺序即 OpenAPI 文档里的分组顺序
ALL_ROUTERS = (
    system.router,
    auth.router,
    inquiries.router,
    agents.router,
    customers.router,
    vendors.router,
    quotations.router,
    orders.router,
    samples.router,
    knowledge.router,
)

__all__ = ["ALL_ROUTERS"]
