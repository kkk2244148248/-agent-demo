# 海贸工作台（外贸小公司内部多 Agent）

面向 **1–20 人外贸团队** 的内部员工系统：询盘处理、RAG 报价口径、发送审批、跟进待办、操作审计。

## 文档（详细）

完整说明请先看文档中心：

- **[docs/README.md](docs/README.md)** — 文档索引  
- **[docs/项目文档.md](docs/项目文档.md)** — 产品 / 架构 / 前后端 / Agent / 数据 / 配置 / API / 扩展 / 限制  
- **[docs/技术细节与参数手册.md](docs/技术细节与参数手册.md)** — **参数级**：配置、模型、工具入参出参、可替代方案  
- **[docs/完整流程图.html](docs/完整流程图.html)** — 浏览器打开看流程图  
- **[docs/Agent与工具参数手册.md](docs/Agent与工具参数手册.md)** — 每个 Agent 与工具参数  

## 启动

### 1) 后端 API（8000）

```bash
cd d:\外贸多agent项目
pip install -r requirements.txt
python run_api.py
```

会读取系统环境变量 **`Apikey` / `API_KEY`**（千问），本地 **BGE-M3** 路径默认：

`F:\eduagent\总代码\backend\models\embedding\bge-m3`

### 2) 前端 Vue（5173）

```bash
cd d:\外贸多agent项目\frontend
npm install
npm run dev
```

打开 http://localhost:5173 （需先登录）

Agent 为 **MCP 风格按需调用**（不是固定流水线），说明见：

**[docs/MCP式Agent说明.md](docs/MCP式Agent说明.md)**

### 默认试用账号（密码均为 `123456`）

| 账号 | 姓名 | 说明 |
|------|------|------|
| `liht` | 李海涛 | 普通业务员 |
| `chenxw` | 陈晓雯 | 经理/管理员 |
| `zhoum` | 周明 | 老板/审批 |

离职人员：管理员登录后进入「账号管理」→ 点「停用（离职）」，对方立刻无法登录。

## 出差远程访问（不买云服务器）

老板若不想交云服务器费用，可用 **办公室常开电脑 + Tailscale**，让出差员工安全连回内网使用。

完整步骤、安全建议、故障排查见：

**[docs/远程访问-Tailscale.md](docs/远程访问-Tailscale.md)**

摘要：

1. 办公室电脑安装并登录 Tailscale，常开运行本系统  
2. 出差员工安装同一 Tailnet 的 Tailscale  
3. 浏览器访问 `http://<办公室Tailscale IP>:5173`

## 功能

- 今日看板：询盘 / 逾期跟进 / 样品 / 报价 / 订单待办
- 询盘建档 + Agent 按需找厂比价；正式报价 → 转订单
- 跟进可自建（逾期标红）；样品规格明细可转订单
- 客户 / 厂商档案 + 关联业务（轻量 360）
- 发送审批闸门（防 AI 乱承诺）
- 知识库检索（Milvus hybrid + 父子分块；失败时 BM25 兜底）
- 悬浮对话助手（Redis → MySQL FAQ/BM25 → RAG）
- 员工身份 + 操作审计
- 对话助手：总控 + Skill + 多领域 Agent（约 30 工具）

## 知识库（对齐 eduagent）

需本机 Milvus（默认 `127.0.0.1:19530`）与本地 BGE-M3。

```bash
python scripts/init_milvus.py
python scripts/build_knowledge_base.py
```

- 集合：`gift_knowledge`（dense 1024 + sparse，WeightedRanker 0.7/0.3）
- 父子分块：child 召回 → 回填 parent 给 LLM

## 技术

| 模块 | 方案 |
|------|------|
| 多 Agent | MCP 式按需工具（Supervisor → Skill → 子 Agent → Tool） |
| LLM | 千问 OpenAI 兼容（DashScope）+ 视觉 qwen-vl |
| RAG | BGE-M3 + Milvus hybrid + 父子分块 |
| API | FastAPI |
| 前端 | Vue 3 + Vite |
| 数据 | 默认 JSON Store（`storage/`） |
