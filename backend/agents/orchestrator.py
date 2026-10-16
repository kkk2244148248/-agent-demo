"""
智能调度器：识别意图 → 匹配 Skill → 按工具链调用 Agent。
编排主路径走 LangGraph（route → tools → end）。
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.agents.skills.router import match_skill
from backend.agents.tools.handlers import bootstrap_tools
from backend.agents.tools.registry import call_tool
from backend.core.logger import get_logger

logger = get_logger(__name__)


def route_tools(user_goal: str, inquiry_hint: str = "") -> dict[str, Any]:
    """兼容旧接口：内部走 Skill 匹配。"""
    return match_skill(user_goal, inquiry_hint)


def merge_pipeline(base: dict[str, Any], piece: dict[str, Any]) -> dict[str, Any]:
    out = dict(base or {})
    for k in (
        "requirement",
        "intent",
        "intent_detail",
        "vendor_match",
        "retrieved_context",
        "retrieved_sources",
        "compare",
        "quote_draft",
        "reply_draft",
        "factory_brief",
        "samples",
        "checklist",
        "document",
        "document_text",
        "document_tables",
        "document_fields",
        "crm",
        "actions",
        "nav_links",
        "vendor",
        "customer",
        "followup",
        "vendor_ranking",
        "vendor_shortlist",
        "cost_estimate",
        "risk_report",
        "email_todos",
        "email_risks",
        "deadline_hints",
        "followup_mail_draft",
        "samples_overdue",
        "sample",
        "sample_status_change",
        "sample_brief",
        "market_cert_pack",
        "claim_risks",
        "shipping_docs",
        "quote_fields",
        "gaps",
        "doc_gap_analysis",
        "crm_customers",
        "crm_vendors",
        "customer_360",
        "overdue_followups",
        "kb_hits",
        "kb_answer",
        "faq_hit",
        "reply_polish_meta",
        "vendors",
        # ── 钱账 / 履约 / 客户资产链路（新增） ──
        "profit",
        "margin_check",
        "rebate",
        "fx",
        "price_suggest",
        "floor_check",
        "version_diff",
        "below_floor_review",
        "lost_deals",
        "tracking",
        "order_tracking",
        "delay_alerts",
        "order",
        "chase_script",
        "collections",
        "overdue",
        "dunning",
        "escalations",
        "customer_pool",
        "customer_radar",
        "reachout",
        "claim_advice",
    ):
        if k in piece and piece[k] is not None:
            out[k] = piece[k]
    return out


def run_selected_tools(
    tool_names: list[str],
    context: dict[str, Any],
) -> dict[str, Any]:
    """按给定列表执行工具；后者可读前者产出（状态累积），但不会自动追加未点名的工具。"""
    bootstrap_tools()
    pipeline = dict(context.get("pipeline") or {})
    traces: list[str] = []
    outputs: dict[str, Any] = {}
    ctx = {
        **context,
        "pipeline": pipeline,
        "requirement": pipeline.get("requirement"),
        "vendor_match": pipeline.get("vendor_match"),
        "compare": pipeline.get("compare"),
        "retrieved_context": pipeline.get("retrieved_context"),
        "retrieved_sources": pipeline.get("retrieved_sources"),
    }

    for name in tool_names:
        try:
            result = call_tool(name, **ctx)
        except Exception as e:
            traces.append(f"{name} → 失败:{e}")
            outputs[name] = {"error": str(e)}
            continue
        outputs[name] = result
        pipeline = merge_pipeline(pipeline, result)
        ctx.update(
            {
                "pipeline": pipeline,
                "requirement": pipeline.get("requirement"),
                "vendor_match": pipeline.get("vendor_match"),
                "compare": pipeline.get("compare"),
                "retrieved_context": pipeline.get("retrieved_context"),
                "retrieved_sources": pipeline.get("retrieved_sources"),
            }
        )
        title = result.get("agent_title") or name
        traces.append(f"{title} → {result.get('summary') or '完成'}")

    pipeline["agent_trace"] = traces
    pipeline["invoked_tools"] = tool_names
    return {
        "pipeline": pipeline,
        "outputs": outputs,
        "agent_trace": traces,
        "invoked_tools": tool_names,
    }


class OrchestrateState(TypedDict, total=False):
    user_goal: str
    context: dict[str, Any]
    route: dict[str, Any]
    tools: list[str]
    pipeline: dict[str, Any]
    outputs: dict[str, Any]
    agent_trace: list[str]
    invoked_tools: list[str]


def _orch_route(state: OrchestrateState) -> dict[str, Any]:
    ctx = state.get("context") or {}
    hint = f"{ctx.get('subject', '')}\n{ctx.get('body', '')[:300]}"
    plan = match_skill(state.get("user_goal") or "", hint)
    tools = list(plan.get("tools") or [])
    logger.info(
        "orchestrate(langgraph) skill=%s tools=%s reason=%s",
        plan.get("skill"),
        tools,
        plan.get("reason"),
    )
    return {"route": plan, "tools": tools}


def _orch_after_route(state: OrchestrateState) -> Literal["run_tools", "kb_end"]:
    route = state.get("route") or {}
    tools = state.get("tools") or []
    if route.get("skill_mode") == "kb" or not tools:
        return "kb_end"
    return "run_tools"


def _orch_run_tools(state: OrchestrateState) -> dict[str, Any]:
    result = run_selected_tools(list(state.get("tools") or []), dict(state.get("context") or {}))
    return {
        "pipeline": result.get("pipeline") or {},
        "outputs": result.get("outputs") or {},
        "agent_trace": result.get("agent_trace") or [],
        "invoked_tools": result.get("invoked_tools") or [],
    }


def _orch_kb_end(state: OrchestrateState) -> dict[str, Any]:
    route = state.get("route") or {}
    ctx = state.get("context") or {}
    return {
        "pipeline": dict(ctx.get("pipeline") or {}),
        "outputs": {},
        "agent_trace": [
            f"Skill「{route.get('skill_title') or route.get('skill')}」无需调用 Agent 工具"
        ],
        "invoked_tools": [],
    }


def build_orchestrate_graph():
    g = StateGraph(OrchestrateState)
    g.add_node("route", _orch_route)
    g.add_node("run_tools", _orch_run_tools)
    g.add_node("kb_end", _orch_kb_end)
    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        _orch_after_route,
        {"run_tools": "run_tools", "kb_end": "kb_end"},
    )
    g.add_edge("run_tools", END)
    g.add_edge("kb_end", END)
    return g.compile()


_orchestrate_graph = None


def get_orchestrate_graph():
    global _orchestrate_graph
    if _orchestrate_graph is None:
        _orchestrate_graph = build_orchestrate_graph()
    return _orchestrate_graph


def orchestrate(user_goal: str, context: dict[str, Any]) -> dict[str, Any]:
    final = get_orchestrate_graph().invoke(
        {
            "user_goal": user_goal,
            "context": context,
            "pipeline": {},
            "outputs": {},
            "agent_trace": [],
            "invoked_tools": [],
        }
    )
    return {
        "pipeline": final.get("pipeline") or {},
        "outputs": final.get("outputs") or {},
        "agent_trace": final.get("agent_trace") or [],
        "invoked_tools": final.get("invoked_tools") or [],
        "route": final.get("route") or {},
    }
