# RAG 说明（Milvus + 父子分块）

对齐参考项目 `F:\eduagent\总代码` 的检索栈，并补上 eduagent 未做的**父子分块**。

## 技术栈

| 组件 | 说明 |
|------|------|
| 嵌入 | 本地 BGE-M3：dense 1024 + sparse lexical |
| 向量库 | Milvus（`gift_knowledge`） |
| 检索 | Hybrid：dense COSINE + sparse IP，`WeightedRanker(0.7, 0.3)` |
| 分块 | Parent = Markdown 章节；Child = 章节内小块 |
| 回填 | 只搜 `chunk_level=child`，返回 `parent_content` |
| 兜底 | Milvus/BGE 不可用时 → 本地 BM25（仍按 parent 去重回填） |

## 配置（`.env.local`）

```
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION=gift_knowledge
USE_MILVUS=true
BGE_M3_MODEL_PATH=F:\eduagent\总代码\backend\models\embedding\bge-m3
```

本机若 19531 不通，保持 **19530**（与当前可用实例一致）。

## 建库

```bash
cd d:\外贸多agent项目
python scripts/init_milvus.py
python scripts/build_knowledge_base.py
```

API 启动时也会尝试 `build()`；已有集合则 upsert 覆盖同 `document_id`。

## 代码入口

- `backend/core/embedder.py` — BGE-M3
- `backend/core/milvus_client.py` — 建表 / upsert / hybrid_search
- `backend/core/knowledge_base.py` — 父子切分、建库、检索回填
