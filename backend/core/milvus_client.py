"""
Milvus 知识库客户端（参考 eduagent）+ 父子分块检索。

- Child：小块向量（dense+sparse），用于召回
- Parent：大块原文，命中 child 后回填 parent 给 LLM
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional

from pymilvus import AnnSearchRequest, DataType, MilvusClient, WeightedRanker

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

VECTOR_DIM = 1024
COLLECTION_NAME = "gift_knowledge"
ANN_EF = 64


@dataclass
class DocumentChunk:
    id: str
    content: str
    embedding: list[float]
    sparse_embedding: dict
    document_id: str
    source_name: str
    chunk_index: int
    chunk_level: str  # parent | child
    parent_id: str = ""
    parent_content: str = ""
    chunk_type: str = "text"
    tenant_id: str = "tenant_demo"
    version: str = "1.0"
    updated_at: int = field(default_factory=lambda: int(time.time()))


def generate_chunk_id(content: str, document_id: str, chunk_index: int, level: str) -> str:
    raw = f"{document_id}_{level}_{chunk_index}_{content[:50]}"
    return hashlib.md5(raw.encode()).hexdigest()


class MilvusKBClient:
    _client: Optional[MilvusClient] = None
    _ensured: bool = False

    def __init__(self) -> None:
        settings = get_settings()
        if MilvusKBClient._client is None:
            uri = f"http://{settings.milvus_host}:{settings.milvus_port}"
            MilvusKBClient._client = MilvusClient(uri=uri)
            logger.info(f"milvus.connected uri={uri}")
        self.collection = settings.milvus_collection
        self.tenant_id = settings.default_tenant_id
        self.ensure_collection()

    @property
    def client(self) -> MilvusClient:
        assert MilvusKBClient._client is not None
        return MilvusKBClient._client

    def ensure_collection(self) -> None:
        if MilvusKBClient._ensured and self.client.has_collection(self.collection):
            try:
                self.client.load_collection(self.collection)
            except Exception:
                pass
            return

        if not self.client.has_collection(self.collection):
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=VECTOR_DIM)
            schema.add_field("sparse_embedding", DataType.SPARSE_FLOAT_VECTOR)
            schema.add_field("content", DataType.VARCHAR, max_length=4096)
            schema.add_field("parent_content", DataType.VARCHAR, max_length=8192)
            schema.add_field("parent_id", DataType.VARCHAR, max_length=64)
            schema.add_field("chunk_level", DataType.VARCHAR, max_length=16)
            schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
            schema.add_field("document_id", DataType.VARCHAR, max_length=128)
            schema.add_field("source_name", DataType.VARCHAR, max_length=256)
            schema.add_field("chunk_type", DataType.VARCHAR, max_length=32)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("version", DataType.VARCHAR, max_length=32)
            schema.add_field("updated_at", DataType.INT64)

            ip = self.client.prepare_index_params()
            ip.add_index(
                field_name="embedding",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 256},
            )
            ip.add_index(
                field_name="sparse_embedding",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
                params={"drop_ratio_build": 0.2},
            )
            ip.add_index(field_name="tenant_id", index_type="INVERTED")
            ip.add_index(field_name="chunk_level", index_type="INVERTED")
            ip.add_index(field_name="document_id", index_type="INVERTED")

            self.client.create_collection(
                collection_name=self.collection,
                schema=schema,
                index_params=ip,
            )
            logger.info(f"milvus.collection_created name={self.collection}")

        try:
            self.client.load_collection(self.collection)
        except Exception as e:
            logger.error(f"milvus.load_failed err={e}")
        MilvusKBClient._ensured = True

    def delete_document(self, document_id: str) -> None:
        safe = document_id.replace('"', '\\"')
        self.client.delete(
            collection_name=self.collection,
            filter=f'document_id == "{safe}"',
        )

    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0
        data = []
        for c in chunks:
            # parent 行也需要向量字段：用 parent 自身 embedding
            data.append(
                {
                    "id": c.id,
                    "embedding": c.embedding,
                    "sparse_embedding": c.sparse_embedding,
                    "content": (c.content or "")[:4096],
                    "parent_content": (c.parent_content or c.content or "")[:8192],
                    "parent_id": c.parent_id or "",
                    "chunk_level": c.chunk_level,
                    "tenant_id": c.tenant_id,
                    "document_id": c.document_id,
                    "source_name": c.source_name[:256],
                    "chunk_type": c.chunk_type,
                    "chunk_index": int(c.chunk_index),
                    "version": c.version,
                    "updated_at": int(c.updated_at),
                }
            )
        self.client.upsert(collection_name=self.collection, data=data)
        logger.info(f"milvus.upserted count={len(data)}")
        return len(data)

    def hybrid_search_children(
        self,
        dense: list[float],
        sparse: dict,
        top_k: int = 6,
        tenant_id: str | None = None,
    ) -> list[dict]:
        """只检索 child，返回时带 parent_content 做回填。"""
        tenant = (tenant_id or self.tenant_id).replace('"', '\\"')
        filters = f'tenant_id == "{tenant}" and chunk_level == "child"'

        dense_req = AnnSearchRequest(
            data=[dense],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": ANN_EF}},
            limit=top_k,
            expr=filters,
        )
        sparse_req = AnnSearchRequest(
            data=[sparse],
            anns_field="sparse_embedding",
            param={"metric_type": "IP"},
            limit=top_k,
            expr=filters,
        )
        results = self.client.hybrid_search(
            collection_name=self.collection,
            reqs=[dense_req, sparse_req],
            ranker=WeightedRanker(0.7, 0.3),
            limit=top_k,
            output_fields=[
                "content",
                "parent_content",
                "parent_id",
                "source_name",
                "document_id",
                "chunk_index",
                "chunk_level",
            ],
        )
        out = []
        for hit in results[0]:
            ent = hit.get("entity") or {}
            out.append(
                {
                    "content": ent.get("content") or "",
                    "parent_content": ent.get("parent_content") or ent.get("content") or "",
                    "parent_id": ent.get("parent_id") or "",
                    "score": float(hit.get("distance") or 0.0),
                    "source_name": ent.get("source_name") or "",
                    "document_id": ent.get("document_id") or "",
                    "chunk_index": ent.get("chunk_index") or 0,
                }
            )
        return out
