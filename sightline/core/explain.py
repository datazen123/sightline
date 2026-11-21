"""The explainer: the only place an LLM touches a finding, and it only adds prose.

Input: a finding whose amount and facts were computed by code.
Output: a plain-English explanation and a short dispute note.

Guardrail: every number in the model's text must already appear in the
finding's facts, amount or citations. If the model writes any other number,
its text is discarded and the deterministic template is used instead. So the
model can explain a figure but can never introduce one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal

from agents.llm import call_structured, detect_provider
from sightline.core.schema import Finding

NUM = re.compile(r"(?<![A-Za-z])\$?-?\d[\d,]*(?:\.\d+)?%?")

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "dispute_note": {"type": "string"},
    },
    "required": ["explanation", "dispute_note"],
}

SYSTEM = (
    "You explain audit findings to a non-technical finance reader. The numbers "
    "were computed by deterministic code and are final: quote them exactly, do "
    "not round, recompute or add any new number, date or percentage. "
    "explanation: 2-3 sentences on what is wrong and why, citing the source. "
    "dispute_note: 2-4 sentences a customer could send to the vendor, naming "
    "the identifiers and the amount. If classification is judgment_required, do "
    "NOT conclude the charge is wrong: state what a human must check, and make "
    "the dispute_note a request for clarification, not a claim."
)


def _canon(tok: str) -> str:
    t = tok.replace("$", "").replace(",", "").rstrip("%")
    try:
        return str(Decimal(t).normalize())
    except Exception:
        return t


def allowed_numbers(f: Finding) -> set[str]:
    blob = json.dumps({"facts": f.facts, "amount": f.amount_usd, "keys": f.keys,
                       "cites": [c.model_dump() for c in f.citations], "title": f.title}, default=str)
    return {_canon(m) for m in NUM.findall(blob)}


def numbers_ok(text: str, allowed: set[str]) -> list[str]:
    """Return the numbers in text that are NOT in the allowed set."""
    small = {str(i) for i in range(0, 11)}  # "two documents", "1 line" etc. are fine
    return [m for m in NUM.findall(text) if _canon(m) not in allowed and _canon(m) not in small]


def explain(findings: list[Finding], template: Callable[[Finding], tuple[str, str]]) -> list[Finding]:
    use_llm = detect_provider() != "mock"
    for f in findings:
        f.explanation, f.dispute_note = template(f)
        f.explained_by = "template"
        if not use_llm:
            continue
        try:
            res = call_structured(
                system=SYSTEM,
                user_content=json.dumps(f.model_dump(exclude={"explanation", "dispute_note"}), default=str),
                tool_name="explain_finding",
                tool_description="Explanation and dispute note for one finding.",
                input_schema=EXPLAIN_SCHEMA,
                agent="judgment" if f.classification == "judgment_required" else "explainer",
            )
        except Exception:
            continue
        allowed = allowed_numbers(f)
        text = res.data["explanation"] + " " + res.data["dispute_note"]
        if not numbers_ok(text, allowed):
            f.explanation, f.dispute_note = res.data["explanation"], res.data["dispute_note"]
            f.explained_by = f"llm:{res.model}"
        else:
            f.explained_by = "template (llm text rejected: introduced numbers)"
    return findings
