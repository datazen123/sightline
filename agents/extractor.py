"""Extractor agent: reads the raw deal room, populates DealSheet + Financials
with citations back to source documents.
"""

from __future__ import annotations

from agents.context_log import ContextLog
from agents.llm import call_structured
from server.ingest import DocumentIndex
from server.schema import DealSheet, Financials

SYSTEM_PROMPT = (
    "You are a commercial real estate diligence analyst extracting structured "
    "facts from a deal room. Extract only what is explicitly stated in the "
    "documents. For every field, cite the exact document and location (page "
    "or section) it came from, with a short verbatim snippet as evidence. "
    "Do not resolve conflicts between documents yourself - if two documents "
    "disagree, extract the figure from the more authoritative source (the "
    "PPM governs over the OM for fees) but note the discrepancy is present; "
    "a separate risk-review step will flag it explicitly."
)

CITATION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string"},
        "location": {"type": "string"},
        "snippet": {"type": "string"},
    },
    "required": ["doc_id", "location", "snippet"],
}

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "deal_sheet": {
            "type": "object",
            "properties": {
                "property_name": {"type": "string"},
                "address": {"type": "string"},
                "units": {"type": "integer"},
                "strategy": {"type": "string"},
                "purchase_price": {"type": "number"},
                "target_hold_years": {"type": "number"},
                "projected_irr": {"type": ["number", "null"]},
                "projected_moic": {"type": ["number", "null"]},
                "fees": {"type": "array", "items": {"type": "string"}},
                "sources_uses": {"type": ["string", "null"]},
                "citations": {"type": "array", "items": CITATION_SCHEMA},
            },
            "required": [
                "property_name", "address", "units", "strategy",
                "purchase_price", "target_hold_years", "fees", "citations",
            ],
        },
        "financials": {
            "type": "object",
            "properties": {
                "t12_noi": {"type": ["number", "null"]},
                "in_place_occupancy": {"type": ["number", "null"]},
                "unit_mix": {"type": "array", "items": {"type": "string"}},
                "proforma_year1_noi": {"type": ["number", "null"]},
                "exit_cap_rate": {"type": ["number", "null"]},
                "market_cap_rate": {"type": ["number", "null"]},
                "citations": {"type": "array", "items": CITATION_SCHEMA},
            },
            "required": ["unit_mix", "citations"],
        },
    },
    "required": ["deal_sheet", "financials"],
}


def extract(index: DocumentIndex, log: ContextLog) -> tuple[DealSheet, Financials]:
    corpus = index.full_corpus_text()
    result = call_structured(
        system=SYSTEM_PROMPT,
        user_content=(
            "Here is the full deal room. Extract the deal sheet and financials.\n\n"
            + corpus
        ),
        tool_name="record_deal_extraction",
        tool_description="Record the extracted DealSheet and Financials with citations.",
        input_schema=TOOL_SCHEMA,
        agent="extractor",
    )
    log.record(
        agent="Extractor",
        system_prompt=SYSTEM_PROMPT,
        retrieved_context=[f"full corpus ({len(index.documents)} documents)"],
        excluded="none - full corpus fits in context for this deal size",
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    deal_sheet = DealSheet.model_validate(result.data["deal_sheet"])
    financials = Financials.model_validate(result.data["financials"])
    return deal_sheet, financials
