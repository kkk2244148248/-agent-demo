"""
MySQL FAQ + 进程内 BM25。

流程：从 MySQL 加载 question/answer → BM25 打分 →
置信度（归一化后 top1）>= 阈值则命中。
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Optional

import pymysql
from pymysql.cursors import DictCursor
from rank_bm25 import BM25Okapi

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    return re.findall(r"[a-z0-9\-/]+", text) + re.findall(r"[\u4e00-\u9fff]", text)


@dataclass
class FaqHit:
    id: int
    question: str
    answer: str
    score: float
    confidence: float


class MysqlFaqStore:
    _instance: Optional["MysqlFaqStore"] = None

    def __init__(self) -> None:
        self.settings = get_settings()
        self._rows: list[dict] = []
        self._bm25: Optional[BM25Okapi] = None
        self._tokens: list[list[str]] = []
        self._loaded_at: float = 0.0
        self.error: str = ""
        self.ready: bool = False

    @classmethod
    def get_instance(cls) -> "MysqlFaqStore":
        if cls._instance is None:
            cls._instance = MysqlFaqStore()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def _connect(self):
        s = self.settings
        return pymysql.connect(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            database=s.mysql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=3,
            read_timeout=5,
            write_timeout=5,
            autocommit=True,
        )

    def ensure_schema(self) -> None:
        s = self.settings
        # 先连到 server 再建库（若库不存在）
        conn = pymysql.connect(
            host=s.mysql_host,
            port=s.mysql_port,
            user=s.mysql_user,
            password=s.mysql_password,
            charset="utf8mb4",
            connect_timeout=3,
            autocommit=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{s.mysql_database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                cur.execute(f"USE `{s.mysql_database}`")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS faq_qa (
                      id BIGINT PRIMARY KEY AUTO_INCREMENT,
                      question VARCHAR(512) NOT NULL,
                      answer TEXT NOT NULL,
                      tags VARCHAR(255) DEFAULT '',
                      active TINYINT(1) NOT NULL DEFAULT 1,
                      hit_count INT NOT NULL DEFAULT 0,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                      KEY idx_active (active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
        finally:
            conn.close()

    def reload(self, force: bool = False) -> int:
        if self.ready and not force and (time.time() - self._loaded_at) < 60:
            return len(self._rows)
        try:
            self.ensure_schema()
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, question, answer, tags FROM faq_qa WHERE active=1 ORDER BY id"
                    )
                    rows = list(cur.fetchall() or [])
            self._rows = rows
            self._tokens = [_tokenize(r["question"] + " " + (r.get("tags") or "")) for r in rows]
            self._bm25 = BM25Okapi(self._tokens) if self._tokens else None
            self._loaded_at = time.time()
            self.ready = True
            self.error = ""
            logger.info(f"mysql_faq.loaded n={len(rows)}")
            return len(rows)
        except Exception as e:
            self.error = str(e)
            self.ready = False
            logger.warning(f"mysql_faq.load_failed err={e}")
            return 0

    def search(self, query: str, top_k: int = 3) -> list[FaqHit]:
        if not self.ready:
            self.reload()
        if not self._bm25 or not self._rows:
            return []

        scores = [float(x) for x in self._bm25.get_scores(_tokenize(query))]
        if not scores:
            return []

        # 置信度：对 top 分数做 softmax 风格归一，取 max/(sum) 不够稳；
        # 用相对 max 的 sigmoid 映射 + 绝对分门槛。
        max_raw = max(scores)
        if max_raw <= 0:
            return []

        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        hits: list[FaqHit] = []
        min_raw = float(self.settings.faq_bm25_min_score)
        for idx, raw in ranked:
            if raw < min_raw:
                continue
            # 绝对分主导，避免「只有弱匹配时 top1 相对分仍为 1」的假高置信
            rel = raw / max_raw if max_raw else 0.0
            strength = 1.0 - math.exp(-raw / 4.0)
            confidence = 0.25 * rel + 0.75 * strength
            row = self._rows[idx]
            hits.append(
                FaqHit(
                    id=int(row["id"]),
                    question=row["question"],
                    answer=row["answer"],
                    score=raw,
                    confidence=float(confidence),
                )
            )
        return hits

    def best_above_threshold(self, query: str) -> Optional[FaqHit]:
        thr = float(self.settings.faq_bm25_confidence)
        hits = self.search(query, top_k=1)
        if not hits:
            return None
        hit = hits[0]
        if hit.confidence < thr:
            logger.info(
                f"mysql_faq.below_threshold conf={hit.confidence:.3f} thr={thr} q={query[:40]}"
            )
            return None
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE faq_qa SET hit_count=hit_count+1 WHERE id=%s", (hit.id,))
        except Exception:
            pass
        return hit

    def seed_if_empty(self, items: list[dict]) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM faq_qa")
                count = int((cur.fetchone() or {}).get("c") or 0)
                if count > 0:
                    return 0
                for it in items:
                    cur.execute(
                        "INSERT INTO faq_qa (question, answer, tags) VALUES (%s,%s,%s)",
                        (it["question"], it["answer"], it.get("tags") or ""),
                    )
                return len(items)


def get_faq_store() -> MysqlFaqStore:
    return MysqlFaqStore.get_instance()
