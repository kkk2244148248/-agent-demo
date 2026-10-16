# 悬浮对话助手（Redis → MySQL BM25 → RAG）

右下角悬浮框「海贸助手」，登录后全局可用。

## 检索链路

1. **Redis**：按归一化问题哈希查缓存，命中直接返回  
2. **MySQL FAQ + BM25**：未命中则在 `faq_qa` 表做 BM25；**原始分 ≥ `FAQ_BM25_MIN_SCORE`（默认 5）且置信度 ≥ `FAQ_BM25_CONFIDENCE`（默认 0.78）** 则返回答案，并写入 Redis  
3. **RAG**：FAQ 未达阈值 → 知识库检索（Milvus/BGE）+ LLM 生成，结果同样写入 Redis  

## 依赖服务

| 服务 | 默认 | 说明 |
|------|------|------|
| Redis | `127.0.0.1:6379` 密码 `1234`，db=`2` | 可复用本机 `milvus-redis` |
| MySQL | `127.0.0.1:3307` 用户 `gift` / `<REDACTED>` 库 `gift_desk` | Docker 容器 `gift-mysql` |

启动专用 MySQL（若尚未创建）：

```bash
docker run -d --name gift-mysql ^
  -e MYSQL_ROOT_PASSWORD=<REDACTED> ^
  -e MYSQL_DATABASE=gift_desk ^
  -e MYSQL_USER=gift ^
  -e MYSQL_PASSWORD=<REDACTED> ^
  -p 3307:3306 mysql:8.0
```

初始化 FAQ：

```bash
python scripts/init_faq_mysql.py
```

## API

- `POST /api/chat/ask` `{ "question": "..." }` → `{ answer, source, cached, meta }`  
  `source`：`redis` | `mysql` | `rag`
- `GET /api/chat/status` 检查 Redis/MySQL/FAQ 条数

## 配置（`.env.local`）

```
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=2
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=gift
MYSQL_PASSWORD=<REDACTED>
MYSQL_DATABASE=gift_desk
FAQ_BM25_CONFIDENCE=0.72
```

## 代码

- `backend/services/redis_cache.py`
- `backend/services/faq_mysql.py`
- `backend/core/chat_assistant.py`
- `frontend/src/components/FloatingChat.vue`
