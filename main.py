"""命令行快速跑一条询盘流水线。"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from backend.agents.trade.graph import run_inquiry_pipeline
from backend.core.knowledge_base import get_knowledge_base
from backend.services.seed_data import get_inquiry, load_inquiries


def main():
    parser = argparse.ArgumentParser(description="外贸多 Agent CLI")
    parser.add_argument("--id", default="INQ-001", help="询盘 ID，如 INQ-001")
    parser.add_argument("--list", action="store_true", help="列出测试询盘")
    args = parser.parse_args()

    if args.list:
        for item in load_inquiries():
            print(f"{item['id']}\t{item['customer_name']}\t{item['subject']}")
        return

    inquiry = get_inquiry(args.id)
    if not inquiry:
        print(f"未找到询盘: {args.id}")
        sys.exit(1)

    get_knowledge_base().build()
    result = run_inquiry_pipeline(inquiry)
    print(json.dumps(
        {
            "inquiry_id": result["inquiry_id"],
            "intent": result["intent"],
            "sources": result["retrieved_sources"],
            "quote_draft": result["quote_draft"],
            "reply_draft": result["reply_draft"],
            "agent_trace": result["agent_trace"],
            "status": result["status"],
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
