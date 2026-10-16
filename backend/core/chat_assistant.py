"""
对话助手编排：

1) Redis 命中 → 直接返回
2) Redis 未命中 → MySQL FAQ + BM25，置信度 >= 阈值 → 返回答案并写入 Redis
3) 识别为业务 Skill（非 kb_qa）→ 按 Skill 调 Agent 工具
4) 否则 → RAG（知识库检索 + LLM）→ 返回答案并写入 Redis
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import get_settings
from backend.core.knowledge_base import get_knowledge_base
from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.services.faq_mysql import get_faq_store
from backend.services.redis_cache import get_redis_cache

logger = get_logger(__name__)

from backend.agents.prompts_registry import KB_CHAT_SYSTEM

CHAT_SYSTEM = KB_CHAT_SYSTEM


class ChatAssistant:
    def ask(self, question: str, user_name: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
        q = (question or "").strip()
        if not q:
            return {"answer": "请输入问题。", "source": "empty", "cached": False}

        cache = get_redis_cache()
        cached = cache.get(q)
        if cached:
            logger.info(f"chat.hit redis user={user_name}")
            return {
                "answer": cached.get("answer", ""),
                "source": "redis",
                "cached": True,
                "meta": {k: v for k, v in cached.items() if k != "answer"},
            }

        # 2) MySQL BM25
        faq = get_faq_store()
        if not faq.ready:
            faq.reload()
        hit = faq.best_above_threshold(q) if faq.ready else None
        if hit:
            payload = {
                "answer": hit.answer,
                "source": "mysql",
                "faq_id": hit.id,
                "faq_question": hit.question,
                "confidence": round(hit.confidence, 4),
                "score": round(hit.score, 4),
            }
            cache.set(q, payload)
            logger.info(
                f"chat.hit mysql id={hit.id} conf={hit.confidence:.3f} user={user_name}"
            )
            return {
                "answer": hit.answer,
                "source": "mysql",
                "cached": False,
                "meta": {
                    "faq_id": hit.id,
                    "faq_question": hit.question,
                    "confidence": round(hit.confidence, 4),
                    "score": round(hit.score, 4),
                    "redis_written": True,
                },
            }

        # 3) 业务 Skill（找厂/比价/写邮件等）
        skill_res = self._try_skill(q, context or {})
        if skill_res:
            logger.info(
                f"chat.hit skill={skill_res.get('skill')} user={user_name} "
                f"tools={skill_res.get('invoked_tools')}"
            )
            return skill_res

        # 4) RAG
        rag = self._rag_answer(q)
        payload = {
            "answer": rag["answer"],
            "source": "rag",
            "backend": rag.get("backend", ""),
            "sources": rag.get("sources") or [],
        }
        cache.set(q, payload)
        logger.info(f"chat.hit rag user={user_name} sources={len(payload['sources'])}")
        return {
            "answer": rag["answer"],
            "source": "rag",
            "cached": False,
            "meta": {
                "backend": rag.get("backend", ""),
                "sources": rag.get("sources") or [],
                "redis_written": True,
            },
        }

    def _kb_only(self, question: str) -> dict[str, Any]:
        """仅 FAQ / RAG，供总控 knowledge_agent 使用（避免递归进 Skill）。"""
        q = (question or "").strip()
        if not q:
            return {"answer": "请输入问题。", "source": "empty"}

        faq = get_faq_store()
        if not faq.ready:
            faq.reload()
        hit = faq.best_above_threshold(q) if faq.ready else None
        if hit:
            return {
                "answer": hit.answer,
                "source": "mysql",
                "meta": {"faq_id": hit.id, "confidence": round(hit.confidence, 4)},
            }
        rag = self._rag_answer(q)
        return {
            "answer": rag["answer"],
            "source": "rag",
            "meta": {"backend": rag.get("backend", ""), "sources": rag.get("sources") or []},
        }

    def _try_skill(self, question: str, context: dict[str, Any]) -> dict[str, Any] | None:
        from backend.agents.orchestrator import orchestrate
        from backend.agents.skills.router import match_skill

        hint = f"{context.get('subject', '')}\n{context.get('body', '')}".strip()
        plan = match_skill(question, hint)
        if plan.get("skill_mode") == "kb" or plan.get("skill") == "kb_qa":
            return None
        tools = plan.get("tools") or []
        if not tools:
            return None

        result = orchestrate(question, {
            "subject": context.get("subject", ""),
            "body": context.get("body", "") or question,
            "query": question,
            "pipeline": context.get("pipeline") or {},
            "customer_name": context.get("customer_name", ""),
            "country": context.get("country", ""),
            "inquiry_id": context.get("inquiry_id", ""),
        })
        route = result.get("route") or plan
        from backend.agents.vendor_cards import enrich_matched_vendors, vendor_actions

        pipe = result.get("pipeline") or {}
        vendors = list(pipe.get("vendors") or [])
        if not vendors:
            vendors = enrich_matched_vendors(
                (pipe.get("vendor_match") or {}).get("matched_vendors") or []
            )
        actions = vendor_actions(vendors)
        answer = self._format_skill_answer(route, result, vendors=vendors)
        return {
            "answer": answer,
            "source": "skill",
            "cached": False,
            "skill": route.get("skill"),
            "skill_title": route.get("skill_title"),
            "invoked_tools": result.get("invoked_tools") or [],
            "agent_trace": result.get("agent_trace") or [],
            "vendors": vendors,
            "actions": actions,
            "nav_links": [a for a in actions if a.get("type") == "link"],
            "route": route,
            "meta": {
                "skill": route.get("skill"),
                "skill_title": route.get("skill_title"),
                "reason": route.get("reason"),
                "invoked_tools": result.get("invoked_tools") or [],
                "agent_trace": result.get("agent_trace") or [],
            },
        }

    def _format_skill_answer(
        self,
        route: dict[str, Any],
        result: dict[str, Any],
        vendors: list[dict[str, Any]] | None = None,
    ) -> str:
        title = route.get("skill_title") or route.get("skill") or "Skill"
        reason = route.get("reason") or ""
        tools = " → ".join(result.get("invoked_tools") or route.get("tools") or []) or "无"
        lines = [
            f"已识别 Skill：**{title}**",
            f"原因：{reason}" if reason else "",
            f"调用工具：{tools}",
            "",
        ]
        traces = result.get("agent_trace") or []
        if traces:
            lines.append("执行轨迹：")
            lines.extend(f"- {t}" for t in traces)

        pipe = result.get("pipeline") or {}
        cards = vendors or pipe.get("vendors") or (pipe.get("vendor_match") or {}).get("matched_vendors") or []
        if cards:
            lines.append("")
            lines.append("匹配厂商（可点下方按钮查看完整档案）：")
            for v in cards[:5]:
                bits = [
                    f"{v.get('vendor_id')} · {v.get('vendor_name')}",
                    v.get("region") or "",
                    v.get("fit_reason") or "",
                ]
                if v.get("moq_note"):
                    bits.append(f"MOQ {v['moq_note']}")
                lines.append("- " + "｜".join(x for x in bits if x))

        reply = pipe.get("reply_draft")
        if reply:
            lines.append("")
            lines.append("海外回复草稿：")
            lines.append(str(reply)[:800])

        brief = pipe.get("factory_brief")
        if brief:
            lines.append("")
            lines.append("询厂话术：")
            lines.append(str(brief)[:800])

        checklist = pipe.get("checklist")
        if checklist:
            lines.append("")
            lines.append("认证清单：")
            lines.extend(f"- {x}" for x in checklist[:12])

        return "\n".join([x for x in lines if x is not None]).strip()

    def _rag_answer(self, question: str) -> dict[str, Any]:
        settings = get_settings()
        kb = get_knowledge_base()
        if not kb.ready:
            kb.build()
        top_k = int(settings.chat_rag_top_k)
        hits = kb.search(question, top_k=top_k)
        context = kb.format_context(question, top_k=top_k)
        sources = [h.source_name for h in hits]

        llm = get_llm("summarize", temperature=0.2)
        prompt = (
            f"用户问题：{question}\n\n"
            f"检索资料：\n{context}\n\n"
            "请基于资料作答；可引用厂商编号；无依据则说明不确定。"
        )
        resp = llm.invoke(
            [SystemMessage(content=CHAT_SYSTEM), HumanMessage(content=prompt)]
        )
        answer = (getattr(resp, "content", None) or str(resp)).strip()
        return {
            "answer": answer,
            "backend": kb.backend,
            "sources": sources,
        }


_assistant: ChatAssistant | None = None


def get_chat_assistant() -> ChatAssistant:
    global _assistant
    if _assistant is None:
        _assistant = ChatAssistant()
    return _assistant
