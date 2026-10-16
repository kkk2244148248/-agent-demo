"""
总控对话编排：

用户输入
  → 总控 Agent（意图识别）按 Skill 选择子 Agent
  → 子 Agent 按 Skill / 上下文选择工具
  → 执行工具并汇总回复
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from backend.agents.domain_agents import (
    SKILL_TO_AGENT,
    agent_for_skill,
    get_domain_agent,
    list_domain_agents,
)
from backend.agents.orchestrator import run_selected_tools
from backend.agents.skills.loader import get_skill, list_skills
from backend.agents.skills.router import match_skill
from backend.agents.tools.handlers import bootstrap_tools
from backend.core.logger import get_logger

logger = get_logger(__name__)


class SupervisorState(TypedDict, total=False):
    user_message: str
    context: dict[str, Any]
    hint: str
    supervisor: dict[str, Any]
    agent_plan: dict[str, Any]
    layers: list[dict[str, Any]]
    run_result: dict[str, Any]
    kb_answer: str
    kb_source: str
    answer: str
    actions: list[dict[str, Any]]
    result: dict[str, Any]


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}


def _use_llm() -> bool:
    try:
        from backend.config import get_settings

        return bool(get_settings().use_real_llm)
    except Exception:
        return False


def supervisor_select(user_message: str, hint: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    总控 Agent：识别意图 → 选 Skill → 选子 Agent。
    """
    bootstrap_tools()
    ctx = context or {}

    # 有上传文件且非明确其它业务意图 → 文档识别
    if ctx.get("file_path") or ctx.get("prefer_doc"):
        g = (user_message or "").lower()
        other = any(k in g for k in ["找厂", "比价", "回海外", "询厂", "样品", "认证", "moq", "添加厂商", "添加客户"])
        if not other or any(k in g for k in ["识别", "pdf", "ocr", "表格", "附件", "截图", "扫描"]):
            skill = get_skill("doc_parse") or {
                "id": "doc_parse",
                "title": "文档表格识别",
                "mode": "agents",
                "tools": ["parse_document", "extract_quote_fields", "doc_vs_requirement"],
            }
            agent = get_domain_agent("document_agent") or agent_for_skill("doc_parse")
            return {
                "layer": "supervisor",
                "skill": "doc_parse",
                "skill_title": skill.get("title") or "文档表格识别",
                "skill_mode": "agents",
                "agent": agent["id"],
                "agent_title": agent.get("title") or agent["id"],
                "reason": "检测到上传附件，优先文档识别 Agent",
                "default_tools": list(skill.get("tools") or ["parse_document", "extract_quote_fields"]),
            }

    # CRM / 跳转优先
    # 注意：钱账、履约、客户雷达类意图若句中出现「客户/厂商」二字，
    # 不能被这里的泛化规则截胡，故先做排除。
    g0 = user_message or ""
    _money_or_ops = any(
        k in g0
        for k in [
            "能赚多少", "赚多少", "毛利", "净利", "利润", "算算账", "能不能接",
            "划不划算", "盈亏平衡", "真实成本", "含退税",
            "收款", "催款", "谁欠", "还欠多少", "尾款", "到账", "账期", "应收", "逾期没付",
            "生产进度", "跟单", "到哪一步", "到哪了", "交期", "会不会延期", "催工厂", "红绿灯", "排产",
            "要跑了", "快回收", "公海", "捞客户", "认领", "雷达", "盘一下客户",
            "底价", "低于底价", "能不能报", "特批", "红线", "丢单",
        ]
    )
    if not _money_or_ops and (
        any(
            k in g0
            for k in [
                "添加厂商", "新建厂商", "加厂商", "登记厂商", "录入厂商",
                "添加客户", "新建客户", "加客户", "添加跟进",
                "打开厂商", "打开客户", "打开跟进", "去厂商", "去客户", "厂商页", "客户页",
                "打开询盘", "打开样品", "打开报价", "打开订单",
                "客户360", "查客户", "查厂商", "逾期跟进",
            ]
        )
        or (("厂商" in g0 or "客户" in g0) and any(k in g0 for k in ["添加", "新建", "登记", "录入", "加"]))
    ):
        skill = get_skill("crm_action") or {"id": "crm_action", "title": "CRM写入与跳转", "tools": ["crm_action"]}
        agent = get_domain_agent("crm_agent") or agent_for_skill("crm_action")
        return {
            "layer": "supervisor",
            "skill": "crm_action",
            "skill_title": skill.get("title") or "CRM写入与跳转",
            "skill_mode": "agents",
            "agent": agent["id"],
            "agent_title": agent.get("title") or agent["id"],
            "reason": "识别到 CRM 写入或页面跳转意图",
            "default_tools": list(skill.get("tools") or ["crm_action"]),
        }

    # 先用已有 skill 匹配（规则/LLM）
    skill_plan = match_skill(user_message, hint)
    skill_id = skill_plan.get("skill") or "kb_qa"
    skill = get_skill(skill_id) or {"id": skill_id, "title": skill_id}

    agent = agent_for_skill(skill_id)
    reason = skill_plan.get("reason") or f"意图对应 Skill「{skill.get('title')}」"

    if _use_llm():
        try:
            from backend.core.llm_factory import get_llm

            skills_txt = "\n".join(
                f"- {s['id']}: {s['title']} → 建议Agent={SKILL_TO_AGENT.get(s['id'], '?')} | {s.get('when')}"
                for s in list_skills()
            )
            agents_txt = "\n".join(
                f"- {a['id']}: {a['title']} | skills={','.join(a.get('skills') or [])} | tools={','.join(a.get('tools') or []) or '无(知识库)'}"
                for a in list_domain_agents()
            )
            from backend.agents.prompts_registry import SUP_SELECT_SYSTEM

            system = SUP_SELECT_SYSTEM.format(skills_txt=skills_txt, agents_txt=agents_txt)
            llm = get_llm("intent", temperature=0)
            resp = llm.invoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=f"用户：{user_message}\n上下文：{hint[:400]}"),
                ]
            )
            data = _parse_json(getattr(resp, "content", "") or "")
            sid = (data.get("skill") or "").strip()
            aid = (data.get("agent") or "").strip()
            if sid and get_skill(sid):
                skill_id = sid
                skill = get_skill(sid) or skill
            if aid and get_domain_agent(aid):
                agent = get_domain_agent(aid) or agent
            if data.get("reason"):
                reason = str(data["reason"])
        except Exception as e:
            logger.error(f"supervisor_select.llm_fallback err={e}")

    return {
        "layer": "supervisor",
        "skill": skill_id,
        "skill_title": skill.get("title") or skill_id,
        "skill_mode": skill.get("mode") or ("kb" if skill_id == "kb_qa" else "agents"),
        "agent": agent["id"],
        "agent_title": agent.get("title") or agent["id"],
        "reason": reason,
        "default_tools": list(skill.get("tools") or []),
    }


def domain_agent_select_tools(
    agent: dict[str, Any],
    skill_id: str,
    user_message: str,
    hint: str = "",
) -> dict[str, Any]:
    """
    子 Agent：在自己的工具箱里，按 Skill / 用户目标挑选要调用的工具。
    """
    bootstrap_tools()
    skill = get_skill(skill_id) or {}
    allowed = list(agent.get("tools") or [])
    preferred = [t for t in (skill.get("tools") or []) if t in allowed]

    if agent.get("mode") == "kb" or skill.get("mode") == "kb":
        return {
            "layer": "agent",
            "agent": agent["id"],
            "agent_title": agent.get("title"),
            "skill": skill_id,
            "tools": [],
            "reason": "知识问答，不调用业务工具",
            "mode": "kb",
        }

    tools = preferred or list(allowed)
    reason = f"按 Skill「{skill.get('title') or skill_id}」默认工具链"

    # 找厂且用户说「只要」→ 只 search
    g = (user_message or "").lower()
    if skill_id == "find_vendor" and any(k in g for k in ["只要", "仅", "只找", "only"]):
        tools = [t for t in ["search_vendors"] if t in allowed] or tools
        reason = "用户只要找厂，寻源 Agent 仅调用 search_vendors"

    if skill_id == "ask_factory" and "search_vendors" in allowed:
        # 缺厂商线索时可加 search（有产品词就只写话术）
        if not any(k in g for k in ["厂", "vendor", "V-"]):
            if "search_vendors" not in tools:
                tools = ["search_vendors"] + [t for t in tools if t != "search_vendors"]
                reason = "询厂前先补厂商匹配"

    # 沟通：只要润色
    if skill_id == "reply_overseas" and any(k in g for k in ["润色", "改短", "更正式", "强硬"]):
        tools = [t for t in ["polish_reply"] if t in allowed] or tools
        reason = "用户要润色已有回复"

    # 样品：逾期 / 推进 / 简报
    if skill_id == "sample_track":
        if any(k in g for k in ["逾期", "超期", "延期"]):
            tools = [t for t in ["sample_overdue"] if t in allowed] or tools
            reason = "查逾期样品"
        elif any(k in g for k in ["推进", "下一步", "已寄出", "打样中"]):
            tools = [t for t in ["advance_sample_status"] if t in allowed] or tools
            reason = "推进样品状态"
        elif any(k in g for k in ["简报", "打样要求"]):
            tools = [t for t in ["sample_brief"] if t in allowed] or tools
            reason = "生成打样简报"
        elif any(k in g for k in ["登记", "新建样品", "加样品"]):
            tools = [t for t in ["upsert_sample"] if t in allowed] or tools
            reason = "登记样品"

    # 合规细分
    if skill_id == "cert_check":
        if any(k in g for k in ["宣传", "可降解", "再生", "抗菌"]):
            tools = [t for t in ["claim_risk_check"] if t in allowed] or tools
            reason = "宣传用语风险"
        elif any(k in g for k in ["出货", "箱单", "发票单证"]):
            tools = [t for t in ["shipping_doc_checklist"] if t in allowed] or tools
            reason = "出货单证"
        elif any(k in g for k in ["美国", "欧洲", "英国", "澳洲", "日本", "欧盟"]):
            tools = [t for t in ["market_cert_pack"] if t in allowed] or tools
            reason = "目的市场认证包"

    # 文档：只要抽字段 / 对比
    if skill_id == "doc_parse":
        if any(k in g for k in ["抽", "单价", "moq", "字段"]):
            tools = [t for t in ["extract_quote_fields"] if t in allowed] or tools
            reason = "抽取报价字段"
        elif any(k in g for k in ["对比", "缺口", "是否满足"]):
            tools = [t for t in ["parse_document", "doc_vs_requirement"] if t in allowed] or tools
            reason = "文档与需求对比"

    # CRM 细分
    if skill_id == "crm_action":
        if any(k in g for k in ["360", "全貌", "关联"]):
            tools = [t for t in ["customer_360"] if t in allowed] or tools
            reason = "客户360"
        elif any(k in g for k in ["逾期跟进", "跟进逾期"]):
            tools = [t for t in ["list_overdue_followups"] if t in allowed] or tools
            reason = "逾期跟进"
        elif any(k in g for k in ["查客户", "查厂商", "搜索客户", "搜索厂商"]):
            tools = [t for t in ["search_crm"] if t in allowed] or tools
            reason = "CRM 搜索"

    # 知识：FAQ 优先再 RAG
    if skill_id == "kb_qa":
        tools = [t for t in ["faq_lookup", "kb_search"] if t in allowed] or tools
        reason = "FAQ 快查，未命中再知识库检索"

    # 利润核算：细分到具体测算动作
    if skill_id == "profit_check":
        if any(k in g for k in ["退税", "退税率"]):
            tools = [t for t in ["rebate_estimate"] if t in allowed] or tools
            reason = "只算出口退税"
        elif any(k in g for k in ["汇率", "贬值", "升值"]):
            tools = [t for t in ["fx_stress_test"] if t in allowed] or tools
            reason = "汇率压力测试"
        elif any(k in g for k in ["报多少", "建议报价", "报什么价"]):
            tools = [t for t in ["quote_price_suggest"] if t in allowed] or tools
            reason = "给建议报价区间"
        elif any(k in g for k in ["达标", "够不够", "红线"]):
            tools = [t for t in ["margin_check"] if t in allowed] or tools
            reason = "只判毛利是否达标"
        else:
            tools = [t for t in ["profit_calc", "margin_check"] if t in allowed] or tools
            reason = "真实毛利测算"

    # 报价守门：细分
    if skill_id == "floor_price_guard":
        if any(k in g for k in ["特批", "待批", "审批"]):
            tools = [t for t in ["below_floor_review"] if t in allowed] or tools
            reason = "列出待特批报价"
        elif any(k in g for k in ["版本", "改了几版", "对比"]):
            tools = [t for t in ["quote_version_diff"] if t in allowed] or tools
            reason = "报价版本对比"
        elif any(k in g for k in ["丢单", "为什么没成"]):
            tools = [t for t in ["lost_deal_analysis"] if t in allowed] or tools
            reason = "丢单归因"
        else:
            tools = [t for t in ["floor_price_check"] if t in allowed] or tools
            reason = "底价红线校验"

    # 生产跟单：细分
    if skill_id == "tracking_board":
        if any(k in g for k in ["延期", "红灯", "预警", "来不及", "危险"]):
            tools = [t for t in ["delay_alert"] if t in allowed] or tools
            reason = "只看有延期风险的订单"
        elif any(k in g for k in ["催", "催一下", "问工厂"]):
            tools = [t for t in ["chase_factory_script"] if t in allowed] or tools
            reason = "生成催工厂话术"
        elif any(k in g for k in ["推进", "做完了", "已完成", "更新节点"]):
            tools = [t for t in ["milestone_advance"] if t in allowed] or tools
            reason = "推进生产节点"
        else:
            tools = [t for t in ["tracking_overview"] if t in allowed] or tools
            reason = "生产跟单总览"

    # 收款催款：细分
    if skill_id == "collection_chase":
        if any(k in g for k in ["登记", "到账了", "打款了", "记一笔"]):
            tools = [t for t in ["payment_record"] if t in allowed] or tools
            reason = "登记一笔收款"
        elif any(k in g for k in ["话术", "怎么写", "写封", "催款信"]):
            tools = [t for t in ["dunning_script"] if t in allowed] or tools
            reason = "生成催款话术"
        elif any(k in g for k in ["升级", "逾很久", "超30", "催不回"]):
            tools = [t for t in ["escalation_advice"] if t in allowed] or tools
            reason = "逾期升级建议"
        elif any(k in g for k in ["逾期", "超过", "欠多久"]):
            tools = [t for t in ["overdue_aging"] if t in allowed] or tools
            reason = "按账龄列逾期"
        else:
            tools = [t for t in ["collection_board"] if t in allowed] or tools
            reason = "应收看板总览"

    # 客户雷达：细分
    if skill_id == "customer_radar":
        if any(k in g for k in ["话术", "说什么", "怎么跟进", "开场"]):
            tools = [t for t in ["reachout_script"] if t in allowed] or tools
            reason = "生成触达话术"
        elif any(k in g for k in ["认领", "值不值得", "捞不捞"]):
            tools = [t for t in ["claim_advice"] if t in allowed] or tools
            reason = "认领建议"
        elif any(k in g for k in ["要跑了", "回收", "预警", "降温"]):
            tools = [t for t in ["customer_radar_report"] if t in allowed] or tools
            reason = "私海降温预警"
        else:
            tools = [t for t in ["customer_pool_scan"] if t in allowed] or tools
            reason = "客户池扫描"

    if _use_llm() and allowed:
        try:
            from backend.core.llm_factory import get_llm

            from backend.agents.prompts_registry import AGENT_SELECT_TOOLS_SYSTEM

            system = AGENT_SELECT_TOOLS_SYSTEM.format(
                agent_title=agent.get("title") or agent.get("id"),
                skill_id=skill_id,
                preferred=", ".join(preferred) or "无",
                allowed=", ".join(allowed) or "无",
            )
            llm = get_llm("intent", temperature=0)
            resp = llm.invoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=f"用户：{user_message}\n上下文：{hint[:300]}"),
                ]
            )
            data = _parse_json(getattr(resp, "content", "") or "")
            picked = [t for t in (data.get("tools") or []) if t in allowed]
            if picked:
                tools = picked
                reason = str(data.get("reason") or reason)
        except Exception as e:
            logger.error(f"domain_agent_select.llm_fallback err={e}")

    # 去重保序
    seen = set()
    ordered = []
    for t in tools:
        if t in allowed and t not in seen:
            seen.add(t)
            ordered.append(t)

    return {
        "layer": "agent",
        "agent": agent["id"],
        "agent_title": agent.get("title"),
        "skill": skill_id,
        "tools": ordered,
        "reason": reason,
        "mode": "agents",
    }


def _extract_vendor_cards(run_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    from backend.agents.vendor_cards import enrich_matched_vendors

    result = run_result or {}
    pipe = result.get("pipeline") or {}
    outputs = result.get("outputs") or {}
    cards: list[dict[str, Any]] = []
    for out in outputs.values():
        if isinstance(out, dict) and out.get("vendors"):
            cards = list(out["vendors"])
            break
    if not cards and pipe.get("vendors"):
        cards = list(pipe.get("vendors") or [])
    if not cards:
        matched = (pipe.get("vendor_match") or {}).get("matched_vendors") or []
        cards = enrich_matched_vendors(matched)
    return cards


def _collect_actions(run_result: dict[str, Any] | None, supervisor: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.agents.vendor_cards import vendor_actions

    actions: list[dict[str, Any]] = []
    result = run_result or {}
    pipe = result.get("pipeline") or {}
    outputs = result.get("outputs") or {}

    for out in outputs.values():
        if isinstance(out, dict):
            for a in out.get("actions") or out.get("nav_links") or []:
                if isinstance(a, dict) and a not in actions:
                    actions.append(a)

    for a in pipe.get("actions") or pipe.get("nav_links") or []:
        if isinstance(a, dict) and a not in actions:
            actions.append(a)

    # 推荐厂商：每家一条「查看档案」+「询厂」
    cards = _extract_vendor_cards(result)
    for a in vendor_actions(cards):
        if a not in actions:
            actions.append(a)

    # 按业务结果补默认跳转
    skill = supervisor.get("skill") or ""
    defaults = {
        "find_vendor": ("/vendors", "打开厂商名录"),
        "compare_quotes": ("/quotations", "打开报价单"),
        "cost_estimate": ("/quotations", "打开报价单"),
        "sample_track": ("/samples", "打开样品进度"),
        "full_rfq": ("/inbox", "打开需求收件箱"),
        "doc_parse": ("/assistant", "继续在对话助手处理"),
        "crm_action": ("/vendors", "打开厂商名录"),
        # 新增链路
        "profit_check": ("/quotations", "打开报价单"),
        "floor_price_guard": ("/quotations", "打开报价单"),
        "tracking_board": ("/tracking", "打开生产跟单看板"),
        "collection_chase": ("/collections", "打开收款看板"),
        "customer_radar": ("/customers/pool", "打开客户公海"),
    }
    if skill in defaults and not any(a.get("type") == "link" for a in actions):
        path, label = defaults[skill]
        actions.append({"type": "link", "path": path, "label": label})

    # 去重 path+label
    seen = set()
    uniq = []
    for a in actions:
        key = (a.get("type"), a.get("path"), a.get("id"), a.get("label"), a.get("message"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    return uniq


def _format_answer(
    user_message: str,
    supervisor: dict[str, Any],
    agent_plan: dict[str, Any],
    run_result: dict[str, Any] | None,
    kb_answer: str | None = None,
) -> str:
    lines = [
        f"【总控】识别 Skill：{supervisor.get('skill_title')} → 交给「{supervisor.get('agent_title')}」",
        f"原因：{supervisor.get('reason')}",
        f"【{agent_plan.get('agent_title')}】选用工具：{' → '.join(agent_plan.get('tools') or []) or '（知识库）'}",
        f"原因：{agent_plan.get('reason')}",
        "",
    ]
    if kb_answer:
        lines.append(kb_answer)
        return "\n".join(lines).strip()

    result = run_result or {}
    for t in result.get("agent_trace") or []:
        lines.append(f"· {t}")

    pipe = result.get("pipeline") or {}
    outputs = result.get("outputs") or {}

    # CRM 结果优先展示
    for out in outputs.values():
        if isinstance(out, dict) and out.get("crm"):
            lines.append("")
            lines.append(out.get("summary") or "CRM 操作完成")
            item = (out.get("crm") or {}).get("item")
            if item:
                lines.append(f"编号：{item.get('id')} 名称：{item.get('name') or item.get('customer_name') or '-'}")

    vendors = _extract_vendor_cards(result)
    if vendors:
        lines.append("")
        lines.append("匹配厂商（可点下方按钮查看完整档案）：")
        for v in vendors[:6]:
            bits = [
                f"{v.get('vendor_id')} · {v.get('vendor_name')}",
                v.get("region") or "",
                v.get("fit_reason") or "",
            ]
            if v.get("moq_note"):
                bits.append(f"MOQ {v['moq_note']}")
            if v.get("contact"):
                bits.append(f"联系人 {v['contact']} {v.get('phone') or ''}".strip())
            lines.append("- " + "｜".join(x for x in bits if x))

    if pipe.get("compare") or pipe.get("quote_draft"):
        opts = (pipe.get("compare") or pipe.get("quote_draft") or {}).get("options") or []
        if opts:
            lines.append("")
            lines.append("比价要点：")
            for o in opts[:4]:
                lines.append(
                    f"- {o.get('vendor_name')} 参考 {o.get('foreign_currency', '')} {o.get('ref_unit_price_foreign', o.get('ref_unit_price_cny', ''))}"
                )

    if pipe.get("reply_draft"):
        lines.append("")
        lines.append("海外回复草稿：")
        lines.append(str(pipe["reply_draft"])[:1200])

    if pipe.get("factory_brief") or pipe.get("sample_brief"):
        lines.append("")
        lines.append("询厂/打样话术：")
        lines.append(str(pipe.get("factory_brief") or pipe.get("sample_brief") or "")[:1200])

    if pipe.get("vendor_shortlist") or pipe.get("vendor_ranking"):
        lines.append("")
        lines.append("厂商短名单/排序：")
        for v in (pipe.get("vendor_shortlist") or pipe.get("vendor_ranking") or [])[:5]:
            lines.append(
                f"- [{v.get('score')}] {v.get('vendor_id')} · {v.get('vendor_name')}："
                f"{'；'.join(v.get('reasons') or [])}"
            )

    if pipe.get("cost_estimate"):
        lines.append("")
        lines.append("成本粗算：")
        for line in (pipe["cost_estimate"].get("lines") or [])[:5]:
            lines.append(f"- {json.dumps(line, ensure_ascii=False)[:200]}")

    if pipe.get("risk_report"):
        lines.append("")
        lines.append("厂商风险：")
        for r in (pipe["risk_report"] or [])[:6]:
            lines.append(f"- {r.get('vendor_name') or r.get('vendor_id')} [{r.get('level')}] {'；'.join(r.get('issues') or [])}")

    if pipe.get("email_todos"):
        lines.append("")
        lines.append("邮件待办：")
        for t in (pipe["email_todos"] or [])[:8]:
            if isinstance(t, dict):
                lines.append(f"- [{t.get('priority')}] {t.get('task')}（{t.get('owner')}）")
            else:
                lines.append(f"- {t}")

    if pipe.get("samples_overdue"):
        lines.append("")
        lines.append(f"逾期样品 {len(pipe['samples_overdue'])} 条：")
        for s in pipe["samples_overdue"][:5]:
            lines.append(f"- {s.get('id')} {s.get('product')} ETA {s.get('eta')} 逾期{s.get('overdue_days')}天")

    if pipe.get("claim_risks"):
        lines.append("")
        lines.append("宣传风险：")
        lines.extend(f"- {x.get('risk')}" for x in (pipe["claim_risks"] or [])[:8])

    if pipe.get("quote_fields"):
        lines.append("")
        lines.append(f"文档报价字段：{json.dumps(pipe['quote_fields'], ensure_ascii=False)[:500]}")

    if pipe.get("gaps"):
        lines.append("")
        lines.append("文档 vs 需求缺口：")
        lines.extend(f"- {g}" for g in (pipe["gaps"] or [])[:8])

    if pipe.get("kb_answer"):
        lines.append("")
        lines.append(str(pipe["kb_answer"])[:1500])
    elif pipe.get("faq_hit") and (pipe["faq_hit"] or {}).get("answer"):
        lines.append("")
        lines.append(str(pipe["faq_hit"]["answer"])[:1500])

    if pipe.get("checklist"):
        lines.append("")
        lines.append("认证清单：")
        lines.extend(f"- {x}" for x in (pipe["checklist"] or [])[:12])

    # ─── 新增链路：钱账 / 履约 / 客户资产 ───────────────────
    profit = pipe.get("profit")
    if profit:
        lines.append("")
        lines.append("【真实毛利测算】")
        lines.append(
            f"- 收入 {profit.get('revenue', {}).get('amount')} {profit.get('currency')}"
            f"｜成本 {profit.get('total_cost')}"
            f"｜退税 {profit.get('export_rebate', {}).get('amount')}"
        )
        lines.append(
            f"- 毛利 {profit.get('gross_profit')}（{float(profit.get('gross_margin') or 0):.2%}）"
            f"｜汇率压力后 {float(profit.get('net_margin_after_fx') or 0):.2%}"
            f"｜盈亏平衡价 {profit.get('breakeven_price')}"
        )
        floor = profit.get("floor_advice") or {}
        if floor:
            lines.append(f"- 建议底价 {floor.get('suggested_floor')}（{floor.get('reason')}）")
        lines.append(f"- 判定：{profit.get('verdict')}")
        for f in (profit.get("risk_flags") or [])[:4]:
            lines.append(f"- ⚠ {f}")

    margin_check = pipe.get("margin_check")
    if margin_check and not profit:
        lines.append("")
        lines.append(f"毛利检查：{float(margin_check.get('gross_margin') or 0):.2%}（{margin_check.get('level')}）")

    floor_check = pipe.get("floor_check")
    if floor_check:
        lines.append("")
        lines.append(f"底价校验：{floor_check.get('verdict')}")

    tracking = pipe.get("tracking") or pipe.get("order_tracking")
    if tracking:
        s = tracking.get("summary") or {}
        lines.append("")
        lines.append(f"生产跟单：红灯 {s.get('red', 0)} / 黄灯 {s.get('amber', 0)} / 绿灯 {s.get('green', 0)}")
        for r in (tracking.get("orders") or [])[:5]:
            light = {"red": "🔴", "amber": "🟡", "green": "🟢"}.get(r.get("light"), "⚪")
            lines.append(
                f"- {light} {r.get('id') or r.get('order_id')} {r.get('product') or ''}｜"
                f"{r.get('current_milestone') or r.get('current_node') or '-'}｜"
                f"进度 {r.get('milestone_progress') or 0}｜ETD {r.get('etd') or '-'}"
            )

    alerts = pipe.get("delay_alerts")
    if alerts:
        lines.append("")
        lines.append(f"交期预警 {len(alerts)} 张：")
        for r in alerts[:5]:
            lines.append(
                f"- {r.get('id') or r.get('order_id')} {r.get('product') or ''}｜"
                f"节点 {r.get('current_milestone') or r.get('current_node') or '-'}｜"
                f"落后节点数 {r.get('delayed_nodes') or 0}｜风险分 {r.get('delay_risk') or '-'}"
            )

    collections = pipe.get("collections")
    if collections:
        s = collections.get("summary") or {}
        lines.append("")
        lines.append(
            f"应收看板：{len(collections.get('rows') or [])} 笔｜逾期 {s.get('overdue_count', 0)} 笔"
            f"｜逾期金额 {s.get('overdue_amount', 0)}"
        )
        for r in (collections.get("rows") or [])[:5]:
            lines.append(
                f"- {r.get('id') or r.get('order_id')} {r.get('customer_name') or ''}｜"
                f"未收 {r.get('due_amount')}｜逾期 {r.get('overdue_days') or 0} 天"
                f"（{r.get('collection_action') or ''}）"
            )

    overdue = pipe.get("overdue")
    if overdue:
        lines.append("")
        lines.append(f"逾期款项 {len(overdue)} 笔：")
        for r in overdue[:5]:
            lines.append(
                f"- {r.get('id') or r.get('order_id')} {r.get('customer_name') or ''}｜{r.get('due_amount')}"
                f"｜逾期 {r.get('overdue_days')} 天（{r.get('aging_light')}）"
            )

    dunning = pipe.get("dunning")
    if dunning:
        lines.append("")
        lines.append(f"催款话术（{dunning.get('action')}）：")
        lines.append(str(dunning.get("script") or "")[:900])

    radar = pipe.get("customer_radar")
    if radar:
        s = radar.get("summary") or {}
        lines.append("")
        lines.append(
            f"客户雷达：私海预警 {s.get('at_risk_count', 0)} 个｜3 天内回收 {s.get('recycle_soon', 0)} 个"
            f"｜公海可捞 {s.get('public_total', 0)} 个"
        )
        for c in (radar.get("at_risk") or [])[:5]:
            lines.append(
                f"- ⚠ {c.get('customer_name')}（{c.get('stage')}）"
                f"已 {c.get('days_since_contact')} 天未跟进，{c.get('recycle_in_days')} 天后回收"
            )
        for c in (radar.get("public_picks") or [])[:3]:
            lines.append(f"- 可认领：{c.get('customer_name')}（{c.get('country')}）")

    reachout = pipe.get("reachout")
    if reachout:
        lines.append("")
        lines.append(f"触达话术（{reachout.get('stage')}）：")
        lines.append(str(reachout.get("script") or "")[:700])

    chase = pipe.get("chase_script")
    if chase:
        lines.append("")
        lines.append("催工厂话术：")
        lines.append(str(chase)[:700])

    doc = pipe.get("document") or {}
    if pipe.get("document_text") or doc.get("text"):
        lines.append("")
        lines.append("文档识别摘要：")
        lines.append(str(pipe.get("document_text") or doc.get("text") or "")[:1500])
    tables = pipe.get("document_tables") or doc.get("tables") or []
    if tables:
        lines.append("")
        lines.append(f"识别到表格 {len(tables)} 个：")
        for t in tables[:3]:
            md = t.get("markdown") or ""
            if md:
                lines.append(md[:800])
    fields = pipe.get("document_fields") or doc.get("structured") or {}
    if fields:
        lines.append("")
        lines.append("抽取字段：" + ", ".join(f"{k}={v}" for k, v in fields.items() if v)[:500])

    samples = pipe.get("samples")
    if samples:
        lines.append("")
        lines.append(f"样品：共 {len(samples) if isinstance(samples, list) else samples} 条（见样品页）")

    actions = _collect_actions(result, supervisor)
    if actions:
        lines.append("")
        lines.append("可操作：")
        for a in actions:
            if a.get("type") == "link":
                lines.append(f"- {a.get('label')} → {a.get('path')}")
            elif a.get("type") == "created":
                lines.append(f"- 已创建 {a.get('entity')} {a.get('id')}")

    if not any(
        [
            vendors,
            pipe.get("reply_draft"),
            pipe.get("factory_brief"),
            pipe.get("checklist"),
            result.get("agent_trace"),
            actions,
        ]
    ):
        lines.append("已按调度执行。可在询盘详情查看完整产出，或补充更具体的目标再试。")

    return "\n".join(lines).strip()


def _sup_select(state: SupervisorState) -> dict[str, Any]:
    ctx = dict(state.get("context") or {})
    msg = (state.get("user_message") or "").strip()
    hint = f"{ctx.get('subject', '')}\n{ctx.get('body', '')}".strip()
    supervisor = supervisor_select(msg, hint, ctx)
    agent = get_domain_agent(supervisor["agent"]) or agent_for_skill(supervisor["skill"])
    agent_plan = domain_agent_select_tools(agent, supervisor["skill"], msg, hint)
    return {
        "hint": hint,
        "supervisor": supervisor,
        "agent_plan": agent_plan,
        "layers": [supervisor, agent_plan],
    }


def _sup_after_plan(state: SupervisorState) -> Literal["kb", "tools"]:
    plan = state.get("agent_plan") or {}
    if plan.get("mode") == "kb" or not plan.get("tools"):
        return "kb"
    return "tools"


def _sup_kb(state: SupervisorState) -> dict[str, Any]:
    from backend.core.chat_assistant import get_chat_assistant

    msg = (state.get("user_message") or "").strip()
    kb = get_chat_assistant()._kb_only(msg)
    return {
        "kb_answer": kb.get("answer") or "暂无资料。",
        "kb_source": kb.get("source") or "rag",
        "run_result": {},
    }


def _sup_tools(state: SupervisorState) -> dict[str, Any]:
    ctx = dict(state.get("context") or {})
    msg = (state.get("user_message") or "").strip()
    plan = state.get("agent_plan") or {}
    run_ctx = {
        **ctx,
        "query": msg,
        "subject": ctx.get("subject") or msg,
        "body": ctx.get("body") or msg,
        "file_path": ctx.get("file_path") or "",
        "force_vision": bool(ctx.get("force_vision")),
        "pipeline": dict(ctx.get("pipeline") or {}),
    }
    if run_ctx["file_path"]:
        run_ctx["pipeline"].setdefault("document", {})
        run_ctx["pipeline"]["document"]["file_path"] = run_ctx["file_path"]
    run_result = run_selected_tools(list(plan.get("tools") or []), run_ctx)
    layers = list(state.get("layers") or [])
    layers.append(
        {
            "layer": "tools",
            "tools": plan.get("tools") or [],
            "agent_trace": run_result.get("agent_trace") or [],
        }
    )
    return {"run_result": run_result, "layers": layers, "kb_answer": "", "kb_source": ""}


def _sup_format(state: SupervisorState) -> dict[str, Any]:
    msg = (state.get("user_message") or "").strip()
    supervisor = state.get("supervisor") or {}
    agent_plan = state.get("agent_plan") or {}
    run_result = state.get("run_result") or None
    kb_answer = state.get("kb_answer") or None
    layers = list(state.get("layers") or [])

    if kb_answer:
        answer = _format_answer(msg, supervisor, agent_plan, None, kb_answer=kb_answer)
        result = {
            "answer": answer,
            "source": "supervisor",
            "kb_source": state.get("kb_source") or "rag",
            "supervisor": supervisor,
            "agent_plan": agent_plan,
            "layers": layers,
            "invoked_tools": [],
            "agent_trace": [],
            "pipeline": {},
            "route": {
                "skill": supervisor.get("skill"),
                "skill_title": supervisor.get("skill_title"),
                "agent": supervisor.get("agent"),
                "agent_title": supervisor.get("agent_title"),
                "tools": [],
                "reason": supervisor.get("reason"),
            },
        }
        return {"answer": answer, "actions": [], "result": result}

    answer = _format_answer(msg, supervisor, agent_plan, run_result)
    actions = _collect_actions(run_result or {}, supervisor)
    vendors = _extract_vendor_cards(run_result)
    pipe = dict((run_result or {}).get("pipeline") or {})
    if vendors:
        pipe["vendors"] = vendors
    result = {
        "answer": answer,
        "source": "supervisor",
        "supervisor": supervisor,
        "agent_plan": agent_plan,
        "layers": layers,
        "invoked_tools": (run_result or {}).get("invoked_tools") or [],
        "agent_trace": (run_result or {}).get("agent_trace") or [],
        "pipeline": pipe,
        "outputs": (run_result or {}).get("outputs") or {},
        "vendors": vendors,
        "actions": actions,
        "nav_links": [a for a in actions if a.get("type") == "link"],
        "route": {
            "skill": supervisor.get("skill"),
            "skill_title": supervisor.get("skill_title"),
            "agent": supervisor.get("agent"),
            "agent_title": supervisor.get("agent_title"),
            "tools": agent_plan.get("tools") or [],
            "reason": f"{supervisor.get('reason')} | {agent_plan.get('reason')}",
        },
    }
    return {"answer": answer, "actions": actions, "result": result}


def build_supervisor_graph():
    g = StateGraph(SupervisorState)
    g.add_node("select", _sup_select)
    g.add_node("kb", _sup_kb)
    g.add_node("tools", _sup_tools)
    g.add_node("format", _sup_format)
    g.add_edge(START, "select")
    g.add_conditional_edges("select", _sup_after_plan, {"kb": "kb", "tools": "tools"})
    g.add_edge("kb", "format")
    g.add_edge("tools", "format")
    g.add_edge("format", END)
    return g.compile()


_supervisor_graph = None


def get_supervisor_graph():
    global _supervisor_graph
    if _supervisor_graph is None:
        _supervisor_graph = build_supervisor_graph()
    return _supervisor_graph


def run_supervisor_desk(
    user_message: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """大对话入口（LangGraph）：总控 → 子 Agent → 工具/知识 → 汇总。"""
    msg = (user_message or "").strip()
    if not msg:
        return {"answer": "请输入你的目标或问题。", "source": "empty"}

    final = get_supervisor_graph().invoke(
        {
            "user_message": msg,
            "context": dict(context or {}),
            "layers": [],
            "run_result": {},
            "kb_answer": "",
            "kb_source": "",
            "actions": [],
        }
    )
    return final.get("result") or {"answer": "处理失败", "source": "error"}
