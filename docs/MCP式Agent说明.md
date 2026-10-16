# 总控对话 + Skill + 子 Agent + 工具

## 调度链路

```
用户输入
  → 总控 Agent（意图识别）
  → 选 Skill
  → 选子 Agent（寻源 / 沟通 / 样品 / 合规 / 文档 / CRM / 知识）
  → 子 Agent 再按 Skill 选工具并执行
  → 汇总回复
```

主入口页面：侧栏 **对话助手** → `/assistant`  
API：`POST /api/assistant/chat`

工具实现：`backend/agents/tools/handlers.py`（基础）+ `extended.py`（扩充），共约 **30** 个工具。

## 子 Agent（工具箱已扩充）

| Agent | 擅长 | 工具箱 |
|-------|------|--------|
| sourcing_agent | 找厂/解析/排序/比价/成本/风险 | parse_requirement, search_vendors, rank_vendors, compare_quotes, estimate_cost, vendor_risk_check |
| communication_agent | 回海外/润色/跟催/询厂/待办 | draft_client_reply, polish_reply, draft_followup_mail, extract_email_todos, draft_factory_brief, search_vendors |
| sample_agent | 样品全流程 | list_samples, upsert_sample, sample_overdue, advance_sample_status, sample_brief |
| compliance_agent | 认证/市场/宣传/出货单证 | cert_checklist, market_cert_pack, claim_risk_check, shipping_doc_checklist |
| document_agent | OCR + 抽字段 + 需求对比 | parse_document, extract_quote_fields, doc_vs_requirement |
| crm_agent | 建档/搜索/360/逾期跟进 | crm_action, suggest_nav, search_crm, customer_360, list_overdue_followups |
| knowledge_agent | FAQ + RAG | faq_lookup, kb_search |

新增 Skill 示例：`cost_estimate`、`vendor_risk`、`email_todos`、`followup_mail`。

参数细节见：[Agent与工具参数手册.md](./Agent与工具参数手册.md)

## 文档识别

- 工具：`parse_document` → 可选 `extract_quote_fields` / `doc_vs_requirement`
- 策略：PDF 用 pdfplumber；扫描件/图片用 `qwen-vl-plus`
- 上传：`POST /api/documents/upload`

## 其它 HTTP

- `GET /api/assistant/agents` 子 Agent 目录  
- `GET /api/skills` Skill 目录  
- `GET /api/agents` 底层工具目录  
- `POST /api/agents/run` 询盘详情智能/手动调度  

## MCP（可选）

```bash
python -m backend.mcp_server.gift_mcp
```
