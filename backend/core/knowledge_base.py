"""
RAG：父子分块 + Milvus hybrid（dense+sparse）+ BM25 本地兜底。

对齐 eduagent：
- BGE-M3 dense(1024) + sparse lexical
- Milvus WeightedRanker(0.7, 0.3)

本项目补全父子分块（eduagent 未做）：
- Parent：Markdown 章节（## / ###）大块，供 LLM 上下文
- Child：章节内小块，用于向量召回；命中后回填 parent_content
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from backend.config import get_settings
from backend.core.logger import get_logger
from backend.core.milvus_client import DocumentChunk, MilvusKBClient, generate_chunk_id

logger = get_logger(__name__)

_MD_HEADER_SPLITTER = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")],
    strip_headers=False,
)
# Parent：章节过大时再切，保证 < parent_content 字段上限
_PARENT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1800,
    chunk_overlap=120,
    separators=["\n\n", "\n", "。", ". ", "，", ", ", " ", ""],
)
# Child：细粒度召回
_CHILD_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=420,
    chunk_overlap=60,
    separators=["\n\n", "\n", "。", ". ", "，", ", ", " ", ""],
)


@dataclass
class RetrievedChunk:
    content: str
    source_name: str
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class ParentChildPair:
    parent: Document
    children: list[Document]


def _tokenize(text: str) -> list[str]:
    text = text.lower()
    return re.findall(r"[a-z0-9\-/]+", text) + re.findall(r"[\u4e00-\u9fff]", text)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def load_markdown(file_path: str) -> list[Document]:
    path = Path(file_path)
    return [Document(page_content=path.read_text(encoding="utf-8"), metadata={"source": str(path)})]


def _source_name(doc: Document, filename: str) -> str:
    parts = [doc.metadata.get(k, "") for k in ("H1", "H2", "H3")]
    parts = [p for p in parts if p]
    return f"{filename} > {' > '.join(parts)}" if parts else filename


def split_parent_child(docs: list[Document]) -> list[ParentChildPair]:
    """Markdown 章节 → parent；章节再切 → children。"""
    pairs: list[ParentChildPair] = []
    for doc in docs:
        source_path = doc.metadata.get("source", "")
        filename = Path(source_path).stem
        sections = _MD_HEADER_SPLITTER.split_text(doc.page_content)
        if not sections:
            sections = [doc]

        for section in sections:
            section.metadata["source"] = source_path
            parents = _PARENT_SPLITTER.split_documents([section])
            for pi, parent in enumerate(parents):
                parent.metadata["source"] = source_path
                parent.metadata["source_name"] = _source_name(parent, filename)
                parent.metadata["chunk_level"] = "parent"
                parent.metadata["parent_index"] = pi

                children = _CHILD_SPLITTER.split_documents([parent])
                if not children:
                    children = [Document(page_content=parent.page_content, metadata=dict(parent.metadata))]
                for ci, child in enumerate(children):
                    child.metadata["source"] = source_path
                    child.metadata["source_name"] = parent.metadata["source_name"]
                    child.metadata["chunk_level"] = "child"
                    child.metadata["parent_index"] = pi
                    child.metadata["child_index"] = ci
                pairs.append(ParentChildPair(parent=parent, children=children))
    return pairs


class KnowledgeBase:
    _instance: Optional["KnowledgeBase"] = None

    def __init__(self) -> None:
        self.chunks: list[Document] = []  # 兜底 BM25 用 child 文本
        self.parent_by_id: dict[str, Document] = {}
        self.embeddings: list[list[float]] = []
        self._bm25: Optional[BM25Okapi] = None
        self._tokens: list[list[str]] = []
        self.backend: str = "bm25"
        self.ready: bool = False
        self.error: str = ""
        self.parent_count: int = 0
        self.child_count: int = 0

    @classmethod
    def get_instance(cls) -> "KnowledgeBase":
        if cls._instance is None:
            cls._instance = KnowledgeBase()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def list_documents(self) -> list[dict]:
        root = Path(get_settings().knowledge_dir)
        docs = []
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            docs.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "title": path.stem,
                    "chars": len(text),
                    "preview": text[:180].replace("\n", " "),
                }
            )
        return docs

    def _collect_pairs(self) -> tuple[list[ParentChildPair], dict[str, str]]:
        settings = get_settings()
        knowledge_dir = Path(settings.knowledge_dir)
        pairs: list[ParentChildPair] = []
        doc_ids: dict[str, str] = {}
        for path in sorted(knowledge_dir.rglob("*.md")):
            rel = str(path.relative_to(knowledge_dir)).replace("\\", "/")
            doc_id = hashlib.md5(rel.encode()).hexdigest()[:16]
            doc_ids[str(path)] = doc_id
            file_pairs = split_parent_child(load_markdown(str(path)))
            logger.info(
                f"kb.loaded file={path.name} parents={len(file_pairs)} "
                f"children={sum(len(p.children) for p in file_pairs)}"
            )
            pairs.extend(file_pairs)
        return pairs, doc_ids

    def _build_local_bm25(self, pairs: list[ParentChildPair]) -> None:
        children: list[Document] = []
        for pair in pairs:
            children.extend(pair.children)
        self.chunks = children
        self._tokens = [_tokenize(c.page_content) for c in children]
        self._bm25 = BM25Okapi(self._tokens) if self._tokens else None

    def _upsert_milvus(self, pairs: list[ParentChildPair], doc_ids: dict[str, str]) -> int:
        from backend.core.embedder import BGEMEmbedder

        settings = get_settings()
        embedder = BGEMEmbedder.get_instance()
        client = MilvusKBClient()

        milvus_rows: list[DocumentChunk] = []
        tenant = settings.default_tenant_id
        now = int(time.time())

        parent_texts: list[str] = []
        child_texts: list[str] = []
        meta_parents: list[tuple[ParentChildPair, str, str]] = []
        meta_children: list[tuple[Document, str, str, str]] = []

        for pair in pairs:
            source = pair.parent.metadata.get("source", "")
            doc_id = doc_ids.get(source) or hashlib.md5(source.encode()).hexdigest()[:16]
            pi = int(pair.parent.metadata.get("parent_index", 0))
            parent_id = generate_chunk_id(pair.parent.page_content, doc_id, pi, "parent")
            pair.parent.metadata["chunk_id"] = parent_id
            self.parent_by_id[parent_id] = pair.parent
            parent_texts.append(pair.parent.page_content)
            meta_parents.append((pair, doc_id, parent_id))
            for child in pair.children:
                child_texts.append(child.page_content)
                meta_children.append((child, doc_id, parent_id, pair.parent.page_content))

        logger.info(f"kb.embedding parents={len(parent_texts)} children={len(child_texts)}")
        p_dense, p_sparse = embedder.encode(parent_texts, batch_size=4) if parent_texts else ([], [])
        c_dense, c_sparse = embedder.encode(child_texts, batch_size=4) if child_texts else ([], [])

        for i, (pair, doc_id, parent_id) in enumerate(meta_parents):
            milvus_rows.append(
                DocumentChunk(
                    id=parent_id,
                    content=pair.parent.page_content,
                    embedding=p_dense[i],
                    sparse_embedding=p_sparse[i],
                    document_id=doc_id,
                    source_name=pair.parent.metadata.get("source_name", "")[:256],
                    chunk_index=int(pair.parent.metadata.get("parent_index", i)),
                    chunk_level="parent",
                    parent_id="",
                    parent_content=pair.parent.page_content,
                    tenant_id=tenant,
                    updated_at=now,
                )
            )

        for i, (child, doc_id, parent_id, parent_text) in enumerate(meta_children):
            ci = int(child.metadata.get("child_index", i))
            cid = generate_chunk_id(child.page_content, doc_id, ci, "child")
            child.metadata["chunk_id"] = cid
            child.metadata["parent_id"] = parent_id
            milvus_rows.append(
                DocumentChunk(
                    id=cid,
                    content=child.page_content,
                    embedding=c_dense[i],
                    sparse_embedding=c_sparse[i],
                    document_id=doc_id,
                    source_name=child.metadata.get("source_name", "")[:256],
                    chunk_index=ci,
                    chunk_level="child",
                    parent_id=parent_id,
                    parent_content=parent_text,
                    tenant_id=tenant,
                    updated_at=now,
                )
            )

        # 编码成功后再删旧写新，避免半成品空库
        for did in set(doc_ids.values()):
            client.delete_document(did)
        return client.upsert_chunks(milvus_rows)

    def build(self, use_bge: bool | None = None, use_milvus: bool | None = None) -> dict:
        settings = get_settings()
        pairs, doc_ids = self._collect_pairs()
        self.parent_count = len(pairs)
        self.child_count = sum(len(p.children) for p in pairs)
        self._build_local_bm25(pairs)
        self.embeddings = []
        self.backend = "bm25"
        self.error = ""

        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        meta_path = Path(settings.storage_dir) / "kb_index.json"
        meta_path.write_text(
            json.dumps(
                {
                    "parents": self.parent_count,
                    "children": self.child_count,
                    "files": [
                        {
                            "source_name": p.parent.metadata.get("source_name"),
                            "parent_chars": len(p.parent.page_content),
                            "children": len(p.children),
                        }
                        for p in pairs
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        use_bge = settings.use_local_bge if use_bge is None else use_bge
        use_milvus = settings.use_milvus if use_milvus is None else use_milvus

        if use_bge and use_milvus:
            try:
                n = self._upsert_milvus(pairs, doc_ids)
                self.backend = "milvus-hybrid+parent-child"
                logger.info(f"kb.milvus_ready rows={n}")
            except Exception as e:
                self.error = str(e)
                logger.error(f"kb.milvus_failed fallback_local err={e}")
                # 本地 dense 兜底
                try:
                    from backend.core.embedder import BGEMEmbedder

                    embedder = BGEMEmbedder.get_instance()
                    texts = [c.page_content for c in self.chunks]
                    dense, _ = embedder.encode(texts, batch_size=4)
                    self.embeddings = dense
                    self.backend = "bge-m3+bm25"
                except Exception as e2:
                    self.error = f"{self.error}; local_bge={e2}"
                    self.backend = "bm25"
        elif use_bge:
            try:
                from backend.core.embedder import BGEMEmbedder

                embedder = BGEMEmbedder.get_instance()
                texts = [c.page_content for c in self.chunks]
                dense, _ = embedder.encode(texts, batch_size=4)
                self.embeddings = dense
                self.backend = "bge-m3+bm25"
            except Exception as e:
                self.error = str(e)
                self.backend = "bm25"

        self.ready = True
        return {
            "chunks": self.child_count,
            "parents": self.parent_count,
            "children": self.child_count,
            "backend": self.backend,
            "error": self.error,
        }

    def _search_milvus(self, query: str, top_k: int) -> list[RetrievedChunk] | None:
        if not self.backend.startswith("milvus"):
            return None
        try:
            from backend.core.embedder import BGEMEmbedder

            dense, sparse = BGEMEmbedder.get_instance().encode_query(query)
            client = MilvusKBClient()
            # 多取一些 child，再按 parent 去重
            hits = client.hybrid_search_children(dense, sparse, top_k=max(top_k * 3, 8))
            seen_parents: set[str] = set()
            results: list[RetrievedChunk] = []
            for h in hits:
                pid = h.get("parent_id") or h.get("content")[:40]
                if pid in seen_parents:
                    continue
                seen_parents.add(pid)
                results.append(
                    RetrievedChunk(
                        content=h.get("parent_content") or h.get("content") or "",
                        source_name=h.get("source_name") or "unknown",
                        score=float(h.get("score") or 0.0),
                        metadata={
                            "parent_id": h.get("parent_id"),
                            "document_id": h.get("document_id"),
                            "child_preview": (h.get("content") or "")[:120],
                            "retrieval": "milvus-hybrid-parent-child",
                        },
                    )
                )
                if len(results) >= top_k:
                    break
            return results
        except Exception as e:
            logger.error(f"kb.milvus_search_failed err={e}")
            return None

    def _search_local(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if not self.chunks:
            return []
        bm25_scores = self._bm25.get_scores(_tokenize(query)) if self._bm25 else [0.0] * len(self.chunks)
        dense_scores = [0.0] * len(self.chunks)

        if self.embeddings:
            try:
                from backend.core.embedder import BGEMEmbedder

                q, _ = BGEMEmbedder.get_instance().encode_query(query)
                dense_scores = [_cosine(q, emb) for emb in self.embeddings]
            except Exception as e:
                logger.error(f"kb.query_embed_failed err={e}")

        def _norm(xs: list[float]) -> list[float]:
            lo, hi = min(xs), max(xs)
            if hi - lo < 1e-9:
                return [0.0 for _ in xs]
            return [(x - lo) / (hi - lo) for x in xs]

        n_bm = _norm([float(x) for x in bm25_scores])
        n_de = _norm(dense_scores)
        fused = [0.55 * d + 0.45 * b for d, b in zip(n_de, n_bm)] if self.embeddings else n_bm

        ranked = sorted(enumerate(fused), key=lambda x: x[1], reverse=True)[: top_k * 3]
        seen_parents: set[str] = set()
        results: list[RetrievedChunk] = []
        for idx, score in ranked:
            if score <= 0:
                continue
            doc = self.chunks[idx]
            parent_id = doc.metadata.get("parent_id") or doc.metadata.get("chunk_id") or str(idx)
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            parent = self.parent_by_id.get(parent_id)
            content = parent.page_content if parent else doc.page_content
            results.append(
                RetrievedChunk(
                    content=content,
                    source_name=doc.metadata.get("source_name", "unknown"),
                    score=float(score),
                    metadata={**dict(doc.metadata), "retrieval": "local-parent-child"},
                )
            )
            if len(results) >= top_k:
                break
        return results

    def search(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        if not self.ready:
            self.build()
        milvus_hits = self._search_milvus(query, top_k)
        if milvus_hits is not None:
            return milvus_hits
        return self._search_local(query, top_k)

    def format_context(self, query: str, top_k: int = 4) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return "（未检索到相关产品资料）"
        return "\n\n".join(f"[{i}] 来源: {h.source_name}\n{h.content}" for i, h in enumerate(hits, 1))


def get_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase.get_instance()
