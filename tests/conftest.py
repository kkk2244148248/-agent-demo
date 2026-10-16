"""pytest 公共夹具。

设计原则：测试不碰真实的 storage/runtime.json。
每个用例拿到的都是一个指向临时目录的全新 store，
这样断言里出现「共 3 条订单」这类数字时不会被种子数据干扰。

注意：工具模块用的是 `from backend.services.store import get_store`
这种「直接引用函数」的写法，patch 模块内的 `_store` 单例不够，
必须同时替换各模块命名空间里的 `get_store` 名字。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 所有 import 了 get_store 的业务模块，需要逐个替换其命名空间内的引用
_STORE_CONSUMERS = (
    "backend.agents.tools.extended",
    "backend.agents.tools.handlers",
    "backend.agents.tools.registry",
    "backend.agents.orchestrator",
    "backend.agents.supervisor",
    "backend.core.chat_assistant",
)


def _install(monkeypatch, tmp_path, *, wipe: bool) -> object:
    from backend.config import get_settings

    settings = get_settings()
    # 只改 storage_dir，其余配置（LLM/Redis 等）保持不动
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path), raising=False)

    from backend.services import store as store_module

    fresh = store_module.RuntimeStore()
    if wipe:
        for key in (
            "inquiries", "customers", "vendors", "followups",
            "quotations", "orders", "samples", "approvals", "audit",
        ):
            fresh.data[key] = []
        fresh._write()

    # 1) 替换单例本身
    monkeypatch.setattr(store_module, "_store", fresh, raising=False)

    # 2) 替换各消费模块里已被解析的名字绑定
    for mod_name in _STORE_CONSUMERS:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "get_store"):
            monkeypatch.setattr(mod, "get_store", lambda _f=fresh: _f, raising=False)

    return fresh


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """带种子数据的全新 RuntimeStore（隔离到临时目录）。"""
    return _install(monkeypatch, tmp_path, wipe=False)


@pytest.fixture()
def empty_store(tmp_path, monkeypatch):
    """空数据集 store：清掉所有种子行，用于边界与数值断言。"""
    return _install(monkeypatch, tmp_path, wipe=True)
