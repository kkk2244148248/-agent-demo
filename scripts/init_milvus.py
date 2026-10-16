"""初始化 / 检查 Milvus 集合 gift_knowledge。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.config import get_settings
from backend.core.milvus_client import MilvusKBClient


def main() -> None:
    s = get_settings()
    print(f"Milvus: {s.milvus_host}:{s.milvus_port}")
    print(f"Collection: {s.milvus_collection}")
    client = MilvusKBClient()
    exists = client.client.has_collection(s.milvus_collection)
    print(f"has_collection={exists}")
    if exists:
        try:
            stats = client.client.get_collection_stats(s.milvus_collection)
            print(f"stats={stats}")
        except Exception as e:
            print(f"stats_err={e}")
    print("OK — 集合已就绪（若不存在已自动创建）")


if __name__ == "__main__":
    main()
