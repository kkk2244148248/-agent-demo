# Agent 与工具参数手册

> 已扩充：每个领域 Agent 工具箱约 **4～6** 个（知识 2 个），全库约 **30** 个工具。  
> 新增实现见 `backend/agents/tools/extended.py`。  
> 看图：[`完整流程图.html`](./完整流程图.html)

对照源码：`domain_agents.py`、`tools/handlers.py`、`tools/extended.py`、`orchestrator.py`、`api/app.py`。

---

## 0. 调用怎么串起来

```
POST /api/assistant/chat  (AssistantChatBody)
  → run_supervisor_desk(message, context)
      → supervisor_select(...)           # 选 Skill + 子 Agent
      → domain_agent_select_tools(...)   # 选工具名列表（含细分启发式）
      → run_selected_tools(tools, ctx)   # 逐个 call_tool(name, **ctx)
          → handlers / extended.tool_xxx(**payload)
```

### 公共 context

| 字段 | 说明 |
|------|------|
| inquiry_id, customer_name, country, subject, body | 询盘上下文 |
| query | 用户话 |
| requirement / vendor_match / compare / pipeline | 上游工具累积 |
| file_path, force_vision | 文档 |

### `POST /api/assistant/chat`

`message*`；可选 `inquiry_id, subject, body, customer_name, country, file_path, force_vision`

---

## 1. 七个子 Agent（工具箱）

| Agent | 工具数 | 工具 |
|-------|--------|------|
| sourcing_agent | 6 | parse_requirement, search_vendors, rank_vendors, compare_quotes, estimate_cost, vendor_risk_check |
| communication_agent | 6 | draft_client_reply, polish_reply, draft_followup_mail, extract_email_todos, draft_factory_brief, search_vendors |
| sample_agent | 5 | list_samples, upsert_sample, sample_overdue, advance_sample_status, sample_brief |
| compliance_agent | 4 | cert_checklist, market_cert_pack, claim_risk_check, shipping_doc_checklist |
| document_agent | 3 | parse_document, extract_quote_fields, doc_vs_requirement |
| crm_agent | 5 | crm_action, suggest_nav, search_crm, customer_360, list_overdue_followups |
| knowledge_agent | 2 | faq_lookup, kb_search |

---

## 2. 新增工具速查

| 工具 | 方法 | 关键入参 | 产出 |
|------|------|----------|------|
| rank_vendors | extended.tool_rank_vendors | vendor_match 或 query | vendor_ranking, vendor_shortlist |
| estimate_cost | tool_estimate_cost | compare 或 requirement | cost_estimate |
| vendor_risk_check | tool_vendor_risk_check | vendor_match / compare / V-xxx | risk_report |
| polish_reply | tool_polish_reply | **已有 reply_draft** | reply_draft（润色后） |
| extract_email_todos | tool_extract_email_todos | subject+body | email_todos, email_risks |
| draft_followup_mail | tool_draft_followup_mail | 客户/需求上下文 | followup_mail_draft |
| sample_overdue | tool_sample_overdue | 无 | samples_overdue |
| advance_sample_status | tool_advance_sample_status | sample_id?, status? | sample, sample_status_change |
| sample_brief | tool_sample_brief | requirement / 样品字段 | sample_brief |
| market_cert_pack | tool_market_cert_pack | country | market_cert_pack |
| claim_risk_check | tool_claim_risk_check | 文案/需求文本 | claim_risks |
| shipping_doc_checklist | tool_shipping_doc_checklist | country? | shipping_docs |
| extract_quote_fields | tool_extract_quote_fields | document 或 file_path | quote_fields |
| doc_vs_requirement | tool_doc_vs_requirement | document_text + requirement | gaps |
| search_crm | tool_search_crm | query | crm_customers, crm_vendors |
| customer_360 | tool_customer_360 | customer_name / id | customer_360 |
| list_overdue_followups | tool_list_overdue_followups | 无 | overdue_followups |
| kb_search | tool_kb_search | query | kb_hits, kb_answer |
| faq_lookup | tool_faq_lookup | query | faq_hit |

原有基础工具行为不变，见 `handlers.py` docstring。

---

## 3. Skill → Agent

| Skill | Agent | 默认 tools |
|-------|-------|------------|
| find_vendor | sourcing | search_vendors, rank_vendors |
| full_rfq | sourcing | parse→search→rank→compare→estimate→draft_client |
| cost_estimate | sourcing | estimate_cost |
| vendor_risk | sourcing | vendor_risk_check, rank_vendors |
| reply_overseas | communication | draft_client_reply, polish_reply |
| followup_mail | communication | draft_followup_mail |
| email_todos | communication | extract_email_todos |
| sample_track | sample | list / overdue / upsert / advance / brief |
| cert_check | compliance | cert / market / claim / shipping |
| doc_parse | document | parse / extract_quote / doc_vs_requirement |
| crm_action | crm | crm_action / search / 360 / overdue / nav |
| kb_qa | knowledge | faq_lookup, kb_search |

---

## 4. 依赖关系（简）

```
parse_requirement → search_vendors → rank_vendors → compare_quotes → estimate_cost
                                              ↘ vendor_risk_check
compare / vendor_match → draft_client_reply → polish_reply
vendor_match → draft_factory_brief
upload → parse_document → extract_quote_fields / doc_vs_requirement
faq_lookup → kb_search（知识）
```

重启 API（`python run_api.py`）后新工具才会生效。
