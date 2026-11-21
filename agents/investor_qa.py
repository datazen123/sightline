"""Investor Q&A agent: answers questions using retrieved chunks, always with
citations. Refuses/deflects judgment-required questions per the judgment
boundary - it will not fabricate a verdict on things like "is this sponsor
trustworthy" or "is now a good time to invest."
"""

from __future__ import annotations

from agents.context_log import ContextLog
from agents.llm import call_structured
from server.ingest import DocumentIndex
from server.schema import Answer

SYSTEM_PROMPT = (
    "You are an investor-facing Q&A assistant for a CRE deal room. Answer "
    "ONLY using the provided context chunks. Every claim must be traceable "
    "to a citation from the context.\n"
    "Classify the question itself:\n"
    "- 'verifiable': answerable from facts stated in the documents (deal "
    "terms, financials, fees, dates). Answer it directly with citations.\n"
    "- 'judgment_required': asks for an opinion or verdict a human should "
    "make (e.g. 'is this a good investment', 'is the sponsor trustworthy', "
    "'is this the right time in the market cycle'). Do NOT answer with a "
    "verdict. Instead, set answered=false and text should explain that this "
    "requires human judgment, citing the relevant evidence a human would "
    "weigh.\n"
    "If the documents do not contain the answer, set answered=false and say "
    "so plainly - do not guess."
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
        "answered": {"type": "boolean"},
        "text": {"type": "string"},
        "classification": {
            "type": "string",
            "enum": ["verifiable", "judgment_required"],
        },
        "citations": {"type": "array", "items": CITATION_SCHEMA},
    },
    "required": ["answered", "text", "classification", "citations"],
}


def answer_question(question: str, index: DocumentIndex, log: ContextLog, k: int = 6) -> Answer:
    results = index.search(question, k=k)
    if not results:
        # fall back to full corpus for very short/broad questions
        context_chunks = index.chunks
        excluded = "keyword search returned no matches; used full corpus as fallback"
    else:
        context_chunks = [c for c, _ in results]
        excluded = (
            f"{len(index.chunks) - len(context_chunks)} chunks not retrieved "
            "(below keyword-overlap threshold for this query)"
        )

    context_text = "\n\n".join(
        f"[{c.doc_id} | {c.location}]\n{c.text}" for c in context_chunks
    )

    result = call_structured(
        system=SYSTEM_PROMPT,
        user_content=f"Question: {question}\n\nContext:\n{context_text}",
        tool_name="record_answer",
        tool_description="Record the answer with citations and classification.",
        input_schema=TOOL_SCHEMA,
        agent="investor_qa",
    )
    log.record(
        agent="Investor Q&A",
        system_prompt=SYSTEM_PROMPT,
        retrieved_context=[f"{c.doc_id} ({c.location})" for c in context_chunks],
        excluded=excluded,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    return Answer(question=question, **result.data)
