"""Summarizer agent: drafts an internal diligence memo and an investor-facing
summary from the already-extracted structured objects (not raw documents).
"""

from __future__ import annotations

import json

from agents.context_log import ContextLog
from agents.llm import call_text
from server.schema import DealSheet, Financials, RiskFinding

DILIGENCE_SYSTEM_PROMPT = (
    "You are a CRE diligence analyst drafting an internal memo for the "
    "investment committee. Be direct and specific. Lead with the risk "
    "findings - especially verifiable contradictions - before the deal "
    "summary. Do not soften or omit the risk findings. Keep it under 400 words."
)

INVESTOR_SYSTEM_PROMPT = (
    "You are drafting an investor-facing summary of a CRE deal. Use only the "
    "structured deal data provided. Be factual and cite figures plainly. Do "
    "not include internal risk-review language or judgment-required findings "
    "verbatim - investor communications should stick to disclosed, verifiable "
    "facts. Keep it under 300 words."
)


def _context_json(deal_sheet: DealSheet, financials: Financials, risks: list[RiskFinding]) -> str:
    return json.dumps(
        {
            "deal_sheet": deal_sheet.model_dump(),
            "financials": financials.model_dump(),
            "risk_findings": [r.model_dump() for r in risks],
        },
        indent=2,
        default=str,
    )


def draft_diligence_memo(
    deal_sheet: DealSheet, financials: Financials, risks: list[RiskFinding], log: ContextLog
) -> str:
    context = _context_json(deal_sheet, financials, risks)
    text, tokens_in, tokens_out = call_text(
        agent="summarizer",
        system=DILIGENCE_SYSTEM_PROMPT,
        user_content=f"Structured deal data:\n{context}",
    )
    log.record(
        agent="Summarizer (diligence memo)",
        system_prompt=DILIGENCE_SYSTEM_PROMPT,
        retrieved_context=["deal_sheet", "financials", f"{len(risks)} risk findings"],
        excluded="raw source documents (works from structured extraction only)",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    return text


def draft_investor_summary(
    deal_sheet: DealSheet, financials: Financials, log: ContextLog
) -> str:
    context = json.dumps(
        {"deal_sheet": deal_sheet.model_dump(), "financials": financials.model_dump()},
        indent=2,
        default=str,
    )
    text, tokens_in, tokens_out = call_text(
        agent="summarizer",
        system=INVESTOR_SYSTEM_PROMPT,
        user_content=f"Structured deal data:\n{context}",
    )
    log.record(
        agent="Summarizer (investor summary)",
        system_prompt=INVESTOR_SYSTEM_PROMPT,
        retrieved_context=["deal_sheet", "financials"],
        excluded="risk findings, raw source documents (investor summary scope only)",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    return text
