"""
外贸多 Agent 演示台（Streamlit）
参考 SmartVoyage 的双栏交互风格：左侧业务看板，右侧 Agent 处理结果。
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st

from backend.agents.trade.graph import run_inquiry_pipeline
from backend.config import get_settings
from backend.core.knowledge_base import KnowledgeBase, get_knowledge_base
from backend.services.seed_data import load_customers, load_followups, load_inquiries

st.set_page_config(
    page_title="外贸多 Agent 工作台",
    page_icon="📦",
    layout="wide",
)

settings = get_settings()

st.markdown(
    """
<style>
.block-card {
  background: #f7f4ef;
  border: 1px solid #e2d8c8;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.trace-pill {
  display: inline-block;
  background: #1f4b3a;
  color: #fff;
  border-radius: 6px;
  padding: 4px 8px;
  margin: 2px 4px 2px 0;
  font-size: 12px;
}
</style>
""",
    unsafe_allow_html=True,
)

if "pipeline_result" not in st.session_state:
    st.session_state.pipeline_result = None
if "kb_ready" not in st.session_state:
    st.session_state.kb_ready = False


@st.cache_resource
def init_kb() -> int:
    KnowledgeBase.reset()
    return get_knowledge_base().build()


def sidebar():
    with st.sidebar:
        st.title("外贸多 Agent")
        st.caption(settings.company_name)
        mode = "MOCK（规则演示）" if not settings.use_real_llm else f"LLM：{settings.llm_model}"
        st.info(f"当前模式：{mode}")
        page = st.radio(
            "功能",
            ["询盘处理台", "客户与跟进", "知识库检索", "系统说明"],
            index=0,
        )
        st.divider()
        if st.button("重建知识库索引", use_container_width=True):
            st.cache_resource.clear()
            n = init_kb()
            st.success(f"已重建，共 {n} 个 chunk")
        return page


def page_inquiry():
    st.header("询盘处理台")
    st.write("流程：意图识别 → RAG 检索 → 报价草拟 → 回复草稿 → **人工确认后发送**")

    inquiries = load_inquiries()
    labels = {
        i["id"]: f"{i['id']} | {i['customer_name']} | {i['subject'][:42]}"
        for i in inquiries
    }
    selected = st.selectbox("选择测试询盘", options=list(labels.keys()), format_func=lambda x: labels[x])
    inquiry = next(i for i in inquiries if i["id"] == selected)

    c1, c2 = st.columns([1.05, 1])
    with c1:
        st.subheader("客户来信")
        st.markdown(
            f"**客户**：{inquiry['customer_name']}（{inquiry['country']}）  \n"
            f"**邮箱**：{inquiry['from_email']}  \n"
            f"**时间**：{inquiry['received_at']}  \n"
            f"**主题**：{inquiry['subject']}"
        )
        st.text_area("正文", inquiry["body"], height=280)

        custom = st.checkbox("改用自定义邮件测试")
        if custom:
            inquiry = {
                **inquiry,
                "id": "INQ-CUSTOM",
                "subject": st.text_input("自定义主题", inquiry["subject"]),
                "body": st.text_area("自定义正文", inquiry["body"], height=200),
                "customer_name": st.text_input("客户名", inquiry["customer_name"]),
                "country": st.text_input("国家", inquiry["country"]),
            }

        if st.button("运行多 Agent 流水线", type="primary", use_container_width=True):
            with st.spinner("Intent → RAG → Quote → Reply ..."):
                init_kb()
                result = run_inquiry_pipeline(inquiry)
                st.session_state.pipeline_result = result

    with c2:
        st.subheader("Agent 输出")
        result = st.session_state.pipeline_result
        if not result:
            st.info("选择询盘后点击左侧按钮，查看各 Agent 结果。")
            return

        trace = result.get("agent_trace") or []
        st.markdown(
            "".join(f"<span class='trace-pill'>{t}</span>" for t in trace),
            unsafe_allow_html=True,
        )

        st.markdown("#### 1) 意图识别")
        st.json(result.get("intent_detail") or {"intent": result.get("intent")})

        st.markdown("#### 2) RAG 检索来源")
        sources = result.get("retrieved_sources") or []
        if sources:
            for s in sources:
                st.write(f"- {s}")
        else:
            st.write("无命中")
        with st.expander("查看检索上下文"):
            st.text(result.get("retrieved_context") or "")

        st.markdown("#### 3) 报价草稿")
        quote = result.get("quote_draft")
        if quote:
            st.json(quote)
        else:
            st.write("本意图未生成报价")

        st.markdown("#### 4) 回复草稿（待人工确认）")
        draft = st.text_area("可编辑后确认", result.get("reply_draft", ""), height=320)
        a1, a2 = st.columns(2)
        with a1:
            if st.button("确认发送（演示）", use_container_width=True):
                st.success("已记录为「人工确认发送」。演示环境不会真实发信。")
                st.session_state.pipeline_result = {
                    **result,
                    "reply_draft": draft,
                    "status": "approved_sent",
                }
        with a2:
            if st.button("驳回重写", use_container_width=True):
                st.warning("已驳回。可修改来信或换一条询盘重新跑流水线。")


def page_crm():
    st.header("客户与跟进")
    customers = load_customers()
    followups = load_followups()

    t1, t2 = st.tabs(["客户列表", "今日跟进"])
    with t1:
        st.dataframe(customers, use_container_width=True, hide_index=True)
    with t2:
        for fu in followups:
            st.markdown(
                f"""
<div class="block-card">
<b>{fu['id']}</b> · {fu['customer_name']} · 截止 {fu['due_date']} · 优先级 {fu['priority']}<br/>
原因：{fu['reason']}<br/>
建议：{fu['suggested_action']}
</div>
""",
                unsafe_allow_html=True,
            )


def page_kb():
    st.header("知识库检索（RAG）")
    n = init_kb()
    st.caption(f"当前索引 chunk 数：{n}")
    q = st.text_input("检索问题", "LH-PM-100 FOB price MOQ lead time CE")
    top_k = st.slider("Top K", 1, 8, 4)
    if st.button("检索", type="primary") or q:
        hits = get_knowledge_base().search(q, top_k=top_k)
        if not hits:
            st.warning("无结果")
        for h in hits:
            with st.expander(f"{h.source_name}  |  score={h.score:.3f}"):
                st.write(h.content)


def page_about():
    st.header("系统说明")
    st.markdown(
        f"""
### 这版 MVP 做什么
面向外贸小公司的**询盘应答多 Agent**：读邮件 → 识别意图 → 查产品知识库 → 出报价草稿 → 出回复草稿 → 人工确认。

### 技术栈对照
| 模块 | 参考 | 本项目落地 |
|------|------|------------|
| 多 Agent 编排 | eduagent LangGraph | `backend/agents/trade/graph.py` |
| LLM 工厂 | eduagent LLMFactory | `backend/core/llm_factory.py` |
| RAG 加载/分块 | eduagent build_knowledge_base | `backend/core/knowledge_base.py` |
| 交互台 | SmartVoyage Streamlit | `app.py` |
| 意图路由思路 | SmartVoyage Intent Agent | `classify_intent_node` |

### 当前模式
- `MOCK_LLM=true`：不调大模型，规则 + 模板也能跑通全流程（默认）
- 在 `.env.local` 填入 `LLM_API_KEY` 并设 `MOCK_LLM=false` 可切换真实模型

### 公司演示主体
**{settings.company_name}**（虚构测试数据）：离心泵 / 齿轮泵 / 三相电机出口。
"""
    )


def main():
    page = sidebar()
    if page == "询盘处理台":
        page_inquiry()
    elif page == "客户与跟进":
        page_crm()
    elif page == "知识库检索":
        page_kb()
    else:
        page_about()


if __name__ == "__main__":
    main()
