"""The 6 retrieval/diligence primitives, as plain functions over a shared
Orchestrator instance. Used directly by the Streamlit app and wrapped by
mcp_server.py for external MCP clients (e.g. the customer's own Claude
client - "pathways to the file").
"""

from __future__ import annotations

from agents.orchestrator import Orchestrator

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


def list_documents() -> list[dict]:
    return [d.model_dump() for d in get_orchestrator().list_documents()]


def get_document(doc_id: str) -> dict:
    doc = get_orchestrator().get_document(doc_id)
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "text": doc.full_text,
        "pages": len(doc.pages),
    }


def search_docs(query: str, k: int = 5) -> list[dict]:
    results = get_orchestrator().search_docs(query, k=k)
    return [
        {"doc_id": c.doc_id, "location": c.location, "score": score, "chunk": c.text}
        for c, score in results
    ]


def get_deal_terms() -> dict:
    return get_orchestrator().get_deal_terms().model_dump()


def get_financials() -> dict:
    return get_orchestrator().get_financials().model_dump()


def flag_risks() -> list[dict]:
    return [r.model_dump() for r in get_orchestrator().flag_risks()]
