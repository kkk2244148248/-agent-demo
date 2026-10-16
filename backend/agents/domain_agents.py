"""
领域子 Agent 定义：总控选中某个 Agent 后，由该 Agent 再按 Skill 挑选工具。

覆盖业务员跑单的完整闭环（询盘 → 找厂 → 报价 → 打样 → 下单 → 生产 → 收款 → 复购）。
Agent 清单（11 个）：
  寻源链路  sourcing_agent / communication_agent
  交付链路  sample_agent / compliance_agent / document_agent
  资产链路  crm_agent / radar_agent
  钱账链路  profit_agent / sales_guard_agent
  履约链路  tracking_agent / collection_agent
  支撑      knowledge_agent
"""
from __future__ import annotations

from typing import Any

# 子 Agent 目录（总控可选）
DOMAIN_AGENTS: dict[str, dict[str, Any]] = {
    # ─── 寻源链路 ───────────────────────────────────────────
    "sourcing_agent": {
        "id": "sourcing_agent",
        "title": "寻源 Agent",
        "description": "解析需求、匹配厂商、排序短名单、比价与成本粗算、厂商风险",
        "stage": "询盘",
        "skills": [
            "parse_requirement",
            "find_vendor",
            "compare_quotes",
            "cost_estimate",
            "vendor_risk",
            "full_rfq",
        ],
        "tools": [
            "parse_requirement",
            "search_vendors",
            "rank_vendors",
            "compare_quotes",
            "estimate_cost",
            "vendor_risk_check",
        ],
    },
    "communication_agent": {
        "id": "communication_agent",
        "title": "沟通 Agent",
        "description": "海外回复、润色、跟催、询厂话术、邮件待办抽取",
        "stage": "触达",
        "skills": ["reply_overseas", "ask_factory", "followup_mail", "email_todos"],
        "tools": [
            "draft_client_reply",
            "polish_reply",
            "draft_followup_mail",
            "extract_email_todos",
            "draft_factory_brief",
            "search_vendors",
        ],
    },
    # ─── 交付链路 ───────────────────────────────────────────
    "sample_agent": {
        "id": "sample_agent",
        "title": "样品 Agent",
        "description": "样品登记、进度、逾期、状态推进、打样简报",
        "stage": "打样",
        "skills": ["sample_track"],
        "tools": [
            "sample_overdue",
            "advance_sample_status",
            "sample_brief",
            "upsert_sample",
            "list_samples",
        ],
    },
    "compliance_agent": {
        "id": "compliance_agent",
        "title": "合规 Agent",
        "description": "品类认证、目的市场单证包、宣传风险、出货单证",
        "stage": "合规",
        "skills": ["cert_check"],
        "tools": [
            "cert_checklist",
            "market_cert_pack",
            "claim_risk_check",
            "shipping_doc_checklist",
        ],
    },
    "document_agent": {
        "id": "document_agent",
        "title": "文档识别 Agent",
        "description": "OCR/表格、报价字段抽取、文档与需求对比",
        "stage": "录入",
        "skills": ["doc_parse"],
        "tools": ["parse_document", "extract_quote_fields", "doc_vs_requirement"],
    },
    # ─── 资产链路 ───────────────────────────────────────────
    "crm_agent": {
        "id": "crm_agent",
        "title": "CRM Agent",
        "description": "建档写入、搜索档案、客户360、逾期跟进、页面跳转",
        "stage": "客户资产",
        "skills": ["crm_action"],
        "tools": [
            "crm_action",
            "suggest_nav",
            "search_crm",
            "customer_360",
            "list_overdue_followups",
        ],
    },
    "radar_agent": {
        "id": "radar_agent",
        "title": "客户雷达 Agent",
        "description": "私海客户降温预警、公海可认领推荐、跟进节奏与触达话术",
        "stage": "客户资产",
        "skills": ["customer_radar"],
        "tools": [
            "customer_pool_scan",
            "customer_radar_report",
            "reachout_script",
            "claim_advice",
        ],
    },
    # ─── 钱账链路 ───────────────────────────────────────────
    "profit_agent": {
        "id": "profit_agent",
        "title": "利润核算 Agent",
        "description": "真实毛利测算（含退税/汇率/港杂）、盈亏平衡价、底价建议、可接判定",
        "stage": "报价",
        "skills": ["profit_check"],
        "tools": [
            "profit_calc",
            "quote_price_suggest",
            "margin_check",
            "rebate_estimate",
            "fx_stress_test",
        ],
    },
    "sales_guard_agent": {
        "id": "sales_guard_agent",
        "title": "报价守门 Agent",
        "description": "底价红线校验、低于底价特批、报价版本复盘、丢单归因",
        "stage": "报价",
        "skills": ["floor_price_guard"],
        "tools": [
            "floor_price_check",
            "quote_version_diff",
            "below_floor_review",
            "lost_deal_analysis",
        ],
    },
    # ─── 履约链路 ───────────────────────────────────────────
    "tracking_agent": {
        "id": "tracking_agent",
        "title": "生产跟单 Agent",
        "description": "6 节点进度、交期红绿灯、延期根因与催办话术、节点推进",
        "stage": "生产",
        "skills": ["tracking_board"],
        "tools": [
            "tracking_overview",
            "delay_alert",
            "milestone_advance",
            "chase_factory_script",
        ],
    },
    "collection_agent": {
        "id": "collection_agent",
        "title": "收款催款 Agent",
        "description": "定金尾款账期、逾期账龄分级、催款话术、升级建议",
        "stage": "收款",
        "skills": ["collection_chase"],
        "tools": [
            "collection_board",
            "overdue_aging",
            "payment_record",
            "dunning_script",
            "escalation_advice",
        ],
    },
    # ─── 支撑 ───────────────────────────────────────────────
    "knowledge_agent": {
        "id": "knowledge_agent",
        "title": "知识 Agent",
        "description": "FAQ 快查 + 知识库 RAG 检索问答",
        "stage": "支撑",
        "skills": ["kb_qa"],
        "tools": ["faq_lookup", "kb_search"],
    },
}

# Skill → 默认子 Agent（规则兜底）
SKILL_TO_AGENT: dict[str, str] = {
    # 寻源
    "parse_requirement": "sourcing_agent",
    "find_vendor": "sourcing_agent",
    "compare_quotes": "sourcing_agent",
    "cost_estimate": "sourcing_agent",
    "vendor_risk": "sourcing_agent",
    "full_rfq": "sourcing_agent",
    # 沟通
    "reply_overseas": "communication_agent",
    "ask_factory": "communication_agent",
    "followup_mail": "communication_agent",
    "email_todos": "communication_agent",
    # 交付
    "sample_track": "sample_agent",
    "cert_check": "compliance_agent",
    "doc_parse": "document_agent",
    # 资产
    "crm_action": "crm_agent",
    "customer_radar": "radar_agent",
    # 钱账
    "profit_check": "profit_agent",
    "floor_price_guard": "sales_guard_agent",
    # 履约
    "tracking_board": "tracking_agent",
    "collection_chase": "collection_agent",
    # 支撑
    "kb_qa": "knowledge_agent",
}


def list_domain_agents() -> list[dict[str, Any]]:
    return [dict(v) for v in DOMAIN_AGENTS.values()]


def get_domain_agent(agent_id: str) -> dict[str, Any] | None:
    item = DOMAIN_AGENTS.get(agent_id)
    return dict(item) if item else None


def agent_for_skill(skill_id: str) -> dict[str, Any]:
    aid = SKILL_TO_AGENT.get(skill_id) or "knowledge_agent"
    return get_domain_agent(aid) or DOMAIN_AGENTS["knowledge_agent"]


def agents_by_stage() -> dict[str, list[dict[str, Any]]]:
    """按跑单阶段分组，供前端/管理页展示。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for a in DOMAIN_AGENTS.values():
        out.setdefault(a.get("stage") or "其他", []).append(dict(a))
    return out
