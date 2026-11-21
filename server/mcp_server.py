"""FastMCP entrypoint exposing the 6 deal-room tools.

Run: uv run python server/mcp_server.py
Or point an MCP-compatible client (e.g. Claude Code, Claude Desktop) at this
script - that's the "pathways to the file" thesis point: retrieval as a
typed, connectable surface, not just an internal function call.
"""

from __future__ import annotations

from fastmcp import FastMCP

from server import tools

mcp = FastMCP("sightline-dealroom-agent")


@mcp.tool
def list_documents() -> list[dict]:
    """List every document in the deal room with id, title, type, and page count."""
    return tools.list_documents()


@mcp.tool
def get_document(doc_id: str) -> dict:
    """Get the full text and provenance of one document by doc_id."""
    return tools.get_document(doc_id)


@mcp.tool
def search_docs(query: str, k: int = 5) -> list[dict]:
    """Keyword search across all document chunks, returns top-k with scores."""
    return tools.search_docs(query, k=k)


@mcp.tool
def get_deal_terms() -> dict:
    """Get the extracted, cited DealSheet (property terms, price, fees, etc)."""
    return tools.get_deal_terms()


@mcp.tool
def get_financials() -> dict:
    """Get the extracted, cited Financials (NOI, occupancy, cap rates, etc)."""
    return tools.get_financials()


@mcp.tool
def flag_risks() -> list[dict]:
    """Cross-check the deal room and return risk findings, each classified
    verifiable or judgment_required."""
    return tools.flag_risks()


if __name__ == "__main__":
    mcp.run()
