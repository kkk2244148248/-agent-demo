"""LangGraph 询盘流水线：路由 Skill → 按需执行工具 → 汇总结果。"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.orchestrator import run_selected_tools
from backend.agents.skills.router import match_skill
from backend.agents.tools.handlers import bootstrap_tools
from backend.core.logger import get_logger

logger = get_logger(__name__)


class InquiryState(TypedDict, total=False):
    inquiry: dict[str, Any]
    user_goal: str
    tools: list[str]
    manual_tools: bool
    context: dict[str, Any]
    route: dict[str, Any]
    pipeline: dict[str, Any]
    outputs: dict[str, Any]
    agent_trace: list[str]
    invoked_tools: list[str]
    result: dict[str, Any]


def _prepare(state: InquiryState) -> dict[str, Any]:
    bootstrap_tools()
    inquiry = state.get("inquiry") or {}
    context = {
        "inquiry_id": inquiry.get("id"),
        "id": inquiry.get("id"),
        "customer_name": inquiry.get("customer_name", ""),
        "country": inquiry.get("country", ""),
        "subject": inquiry.get("subject", ""),
        "body": inquiry.get("body", ""),
        "pipeline": dict(inquiry.get("pipeline") or {}),
    }
    return {"context": context}


def _route(state: InquiryState) -> dict[str, Any]:
    tools = list(state.get("tools") or [])
    if tools:
        return {
            "manual_tools": True,
            "tools": tools,
            "route": {"tools": tools, "reason": "用户手动指定 Agent", "intents": []},
        }

    ctx = state.get("context") or {}
    goal = (state.get("user_goal") or "").strip() or (
        "先解析需求并找合适厂商（不要自动写完全部回复，除非必要）"
    )
    hint = f"{ctx.get('subject', '')}\n{ctx.get('body', '')[:300]}"
    plan = match_skill(goal, hint)
    selected = list(plan.get("tools") or [])
    logger.info(
        "langgraph route skill=%s tools=%s reason=%s",
        plan.get("skill"),
        selected,
        plan.get("reason"),
    )
    return {
        "manual_tools": False,
        "user_goal": goal,
        "tools": selected,
        "route": plan,
    }


def _after_route(state: InquiryState) -> Literal["run_tools", "assemble"]:
    route = state.get("route") or {}
    tools = state.get("tools") or []
    if state.get("manual_tools"):
        return "run_tools" if tools else "assemble"
    if route.get("skill_mode") == "kb" or not tools:
        return "assemble"
    return "run_tools"


def _run_tools(state: InquiryState) -> dict[str, Any]:
    ctx = dict(state.get("context") or {})
    tools = list(state.get("tools") or [])
    result = run_selected_tools(tools, ctx)
    return {
        "pipeline": result.get("pipeline") or {},
        "outputs": result.get("outputs") or {},
        "agent_trace": result.get("agent_trace") or [],
        "invoked_tools": result.get("invoked_tools") or tools,
    }


def _assemble(state: InquiryState) -> dict[str, Any]:
    inquiry = state.get("inquiry") or {}
    route = state.get("route") or {}
    pipeline = dict(state.get("pipeline") or (state.get("context") or {}).get("pipeline") or {})
    agent_trace = list(state.get("agent_trace") or [])
    invoked = list(state.get("invoked_tools") or [])
    if not invoked and not agent_trace and not state.get("manual_tools"):
        agent_trace = [
            f"Skill「{route.get('skill_title') or route.get('skill')}」无需调用 Agent 工具"
        ]

    result = {
        **pipeline,
        "inquiry_id": inquiry.get("id"),
        "agent_trace": agent_trace,
        "invoked_tools": invoked,
        "route": route,
        "needs_human_approval": True,
        "status": "awaiting_approval",
        "customer_name": inquiry.get("customer_name", ""),
        "customer_country": inquiry.get("country", ""),
        "subject": inquiry.get("subject", ""),
        "email_body": inquiry.get("body", ""),
    }
    return {
        "pipeline": pipeline,
        "agent_trace": agent_trace,
        "invoked_tools": invoked,
        "result": result,
    }


def build_inquiry_graph():
    g = StateGraph(InquiryState)
    g.add_node("prepare", _prepare)
    g.add_node("route", _route)
    g.add_node("run_tools", _run_tools)
    g.add_node("assemble", _assemble)
    g.add_edge(START, "prepare")
    g.add_edge("prepare", "route")
    g.add_conditional_edges(
        "route",
        _after_route,
        {"run_tools": "run_tools", "assemble": "assemble"},
    )
    g.add_edge("run_tools", "assemble")
    g.add_edge("assemble", END)
    return g.compile()


_inquiry_graph = None


def get_inquiry_graph():
    global _inquiry_graph
    if _inquiry_graph is None:
        _inquiry_graph = build_inquiry_graph()
    return _inquiry_graph


def run_inquiry_pipeline(
    inquiry: dict[str, Any],
    user_goal: str | None = None,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    """询盘处理入口（LangGraph）。"""
    final = get_inquiry_graph().invoke(
        {
            "inquiry": inquiry,
            "user_goal": user_goal or "",
            "tools": list(tools or []),
            "pipeline": {},
            "outputs": {},
            "agent_trace": [],
            "invoked_tools": [],
        }
    )
    return final.get("result") or {}
