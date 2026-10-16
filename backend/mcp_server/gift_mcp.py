"""
礼品寻源 MCP Server（FastMCP）
把各 Agent 暴露成 MCP tools，可被 Cursor/其他 Host 按需调用。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from backend.agents.tools.handlers import bootstrap_tools, tool_search_vendors, tool_parse_requirement, tool_compare_quotes, tool_draft_factory_brief, tool_list_samples, tool_cert_checklist
from backend.core.knowledge_base import get_knowledge_base

bootstrap_tools()
try:
    get_knowledge_base().build()
except Exception:
    pass

mcp = FastMCP(
    name="GiftSourcingTools",
    instructions="礼品中国分部寻源工具：找厂商、解析需求、比价、询厂话术、样品与认证检查。按需调用，不要默认全跑。",
)


@mcp.tool()
def search_vendors(query: str, subject: str = "", body: str = "") -> dict:
    """检索国内礼品厂商：谁能做某类礼品、参考能力与风险。只找厂时用这个。"""
    return tool_search_vendors(query=query, subject=subject, body=body)


@mcp.tool()
def parse_requirement(subject: str, body: str, customer_name: str = "", country: str = "") -> dict:
    """解析海外礼品需求邮件，拆成品类/数量/预算等字段。"""
    return tool_parse_requirement(subject=subject, body=body, customer_name=customer_name, country=country)


@mcp.tool()
def compare_quotes(requirement_json: str = "{}", vendor_match_json: str = "{}") -> dict:
    """对已有需求与厂商匹配结果做比价建议。"""
    import json

    return tool_compare_quotes(
        requirement=json.loads(requirement_json or "{}"),
        vendor_match=json.loads(vendor_match_json or "{}"),
    )


@mcp.tool()
def draft_factory_brief(requirement_json: str = "{}", vendor_match_json: str = "{}") -> dict:
    """生成发给国内工厂的中文询价话术。"""
    import json

    return tool_draft_factory_brief(
        requirement=json.loads(requirement_json or "{}"),
        vendor_match=json.loads(vendor_match_json or "{}"),
    )


@mcp.tool()
def list_samples(status: str = "") -> dict:
    """查看样品进度。"""
    return tool_list_samples(status=status or None)


@mcp.tool()
def cert_checklist(category_or_query: str) -> dict:
    """按品类给出出口认证检查清单。"""
    return tool_cert_checklist(query=category_or_query)


if __name__ == "__main__":
    # SSE/HTTP 取决于 mcp 版本；默认 stdio 也可被 Host 拉起
    mcp.run()
