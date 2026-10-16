"""
重建礼品知识库：父子分块 → BGE-M3 dense+sparse → 写入 Milvus。

用法（项目根目录）:
  python scripts/build_knowledge_base.py
  python scripts/build_knowledge_base.py --no-milvus   # 仅本地 BM25/BGE
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.knowledge_base import KnowledgeBase


def main() -> None:
    parser = argparse.ArgumentParser(description="Build gift sourcing knowledge base")
    parser.add_argument("--no-milvus", action="store_true", help="跳过 Milvus，仅本地索引")
    parser.add_argument("--no-bge", action="store_true", help="跳过 BGE，仅 BM25")
    args = parser.parse_args()

    KnowledgeBase.reset()
    kb = KnowledgeBase.get_instance()
    result = kb.build(use_bge=not args.no_bge, use_milvus=not args.no_milvus)
    print(result)

    # 冒烟检索
    for q in ["保温杯 礼品 厂家", "折叠伞 定制", "蓝牙音箱 MOQ"]:
        hits = kb.search(q, top_k=2)
        print(f"\nQ: {q}")
        for h in hits:
            preview = h.content.replace("\n", " ")[:100]
            print(f"  [{h.score:.3f}] {h.source_name} | {preview}")


if __name__ == "__main__":
    main()
