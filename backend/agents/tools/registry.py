"""
MCP 风格 Agent 工具注册表。
每个 Agent = 一个可独立调用的工具（像 MCP tool），互不绑死流水线。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AgentTool:
    name: str
    title: str
    description: str
    when_to_use: str
    handler: Callable[..., dict[str, Any]]


_REGISTRY: dict[str, AgentTool] = {}


def register_tool(tool: AgentTool) -> AgentTool:
    _REGISTRY[tool.name] = tool
    return tool


def list_tools() -> list[dict[str, str]]:
    return [
        {
            "name": t.name,
            "title": t.title,
            "description": t.description,
            "when_to_use": t.when_to_use,
        }
        for t in _REGISTRY.values()
    ]


def get_tool(name: str) -> AgentTool | None:
    return _REGISTRY.get(name)


def call_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    tool = get_tool(name)
    if not tool:
        raise KeyError(f"未知 Agent 工具: {name}")
    result = tool.handler(**kwargs)
    if not isinstance(result, dict):
        raise TypeError(f"{name} 必须返回 dict")
    result.setdefault("agent", name)
    result.setdefault("agent_title", tool.title)
    return result
