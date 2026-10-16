"""FastAPI 入口：应用装配 + 生命周期。

本文件刻意保持「薄」——只做四件事：

    1. 建 app、装中间件（CORS 白名单来自配置，不再 allow_origins=["*"]）；
    2. 启动时预热存储、鉴权、工具注册表，并异步构建知识库；
    3. 挂载各业务域 router（见 backend/api/routers/）；
    4. 提供 __main__ 直跑入口。

所有业务逻辑都在 routers / services / agents 三层里，
这样启动文件不会再随功能增长而膨胀。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.tools.handlers import bootstrap_tools
from backend.api.deps import build_kb_async, kb_status
from backend.api.routers import ALL_ROUTERS
from backend.config import get_settings
from backend.core.logger import get_logger
from backend.services.auth import get_auth
from backend.services.store import get_store

logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description="海贸工作台后端：外贸礼品出口跑单全流程（询盘 → 找厂 → 报价 → 订单 → 收款）。",
)

# CORS：只放行配置里列出的来源。原先 allow_origins=["*"] 配合
# allow_credentials=True 属于无效组合（浏览器会直接拒绝），
# 且等于对所有站点开放，因此改为显式白名单。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.resolved_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

for _router in ALL_ROUTERS:
    app.include_router(_router)


@app.on_event("startup")
def on_startup() -> None:
    """预热重资源，避免第一个用户请求承担冷启动成本。"""
    get_store()
    get_auth()
    bootstrap_tools()
    build_kb_async()
    logger.info(
        f"api.ready app={settings.app_name} cors={settings.resolved_cors_origins} "
        f"kb_building={kb_status['building']}"
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.api.app:app", host=settings.api_host, port=settings.api_port, reload=False
    )
