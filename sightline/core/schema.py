"""Domain-neutral result types shared by every corpus plugin."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Classification = Literal["verifiable", "judgment_required"]
Severity = Literal["low", "medium", "high"]


class Citation(BaseModel):
    file: str
    location: str = Field(description="page N, row N, sheet!rowN, or a named section")
    snippet: str = ""


class Finding(BaseModel):
    id: str
    corpus: str
    rule: str
    title: str
    severity: Severity
    classification: Classification
    # Computed by deterministic code. None for judgment items with no amount.
    amount_usd: float | None = None
    facts: dict[str, Any] = Field(default_factory=dict, description="numbers code computed")
    keys: dict[str, Any] = Field(default_factory=dict, description="ids used for matching/dedup")
    citations: list[Citation] = Field(default_factory=list)
    explanation: str = ""
    dispute_note: str = ""
    explained_by: str = "template"


class AuditResult(BaseModel):
    run_id: str
    corpus: str
    findings: list[Finding]
    stats: dict[str, Any] = Field(default_factory=dict)
    rejected_mappings: list[dict[str, Any]] = Field(default_factory=list)
    llm_usage: list[dict[str, Any]] = Field(default_factory=list)
    llm_cost_usd: float | None = None
