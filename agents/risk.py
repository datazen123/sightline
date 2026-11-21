"""Risk / Underwriter agent: cross-checks facts across documents, emits
RiskFindings tagged verifiable (a factual contradiction) vs judgment_required
(needs a human). This is the judgment-boundary differentiator - the agent
must never fabricate a verdict on a judgment_required item.
"""

from __future__ import annotations

from agents.context_log import ContextLog
from agents.llm import call_structured
from server.ingest import DocumentIndex
from server.schema import RiskFinding

SYSTEM_PROMPT = (
    "You are a CRE underwriting risk reviewer. Cross-check facts across ALL "
    "documents in this deal room and identify inconsistencies or risks a "
    "careful analyst would catch. For each finding, classify it strictly:\n"
    "- 'verifiable': two or more documents state different values for what "
    "should be the same fact (a fee %, a cap rate, an occupancy figure, a "
    "dollar total), OR a document asserts a figure with no reconciling "
    "explanation shown anywhere for a gap against another stated figure "
    "(e.g. a jump from a current occupancy figure to a higher projected one "
    "with no lease-up bridge, timeline, or cost shown). The discrepancy or "
    "unexplained gap ITSELF is always verifiable - you can point to exact "
    "quotes proving it - even when a deeper question about which figure to "
    "trust, or whether an assumption is reasonable, also exists on top of "
    "it. Do not downgrade a documented contradiction to judgment_required "
    "just because resolving it also takes judgment.\n"
    "- 'judgment_required': there is no contradiction between stated facts "
    "at all - only an interpretive question (sponsor quality, whether "
    "framing is misleading, market timing risk, deal structure risk). "
    "Do NOT render a verdict on these - only surface them with the "
    "relevant evidence attached, and explain what a human would need to "
    "weigh.\n"
    "If a factual contradiction ALSO raises a separate interpretive "
    "question (e.g. 'these two documents disagree' is verifiable, but "
    "'is the resulting assumption reasonable' is judgment_required), "
    "report the contradiction as its own verifiable finding, and optionally "
    "add a second judgment_required finding for the interpretive layer - "
    "do not merge them into one judgment_required finding.\n"
    "Only report findings you can support with direct quotes from the "
    "documents. Do not speculate about issues not evidenced in the text."
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
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "category": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": ["verifiable", "judgment_required"],
                    },
                    "explanation": {"type": "string"},
                    "evidence": {"type": "array", "items": CITATION_SCHEMA},
                },
                "required": [
                    "id", "title", "severity", "category",
                    "classification", "explanation", "evidence",
                ],
            },
        }
    },
    "required": ["findings"],
}


def flag_risks(index: DocumentIndex, log: ContextLog) -> list[RiskFinding]:
    corpus = index.full_corpus_text()
    result = call_structured(
        system=SYSTEM_PROMPT,
        user_content=(
            "Here is the full deal room. Cross-check it for inconsistencies "
            "and risks.\n\n" + corpus
        ),
        tool_name="record_risk_findings",
        tool_description="Record the list of risk findings.",
        input_schema=TOOL_SCHEMA,
        agent="risk",
    )
    log.record(
        agent="Risk/Underwriter",
        system_prompt=SYSTEM_PROMPT,
        retrieved_context=[f"full corpus ({len(index.documents)} documents)"],
        excluded="none - full corpus fits in context for this deal size",
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    return [RiskFinding.model_validate(f) for f in result.data["findings"]]
