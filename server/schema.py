"""Pydantic models shared across ingestion, MCP tools, and agents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Classification = Literal["verifiable", "judgment_required"]
Severity = Literal["low", "medium", "high"]


class Citation(BaseModel):
    doc_id: str
    location: str = Field(description="Page number or named section")
    snippet: str


class Chunk(BaseModel):
    doc_id: str
    doc_title: str
    location: str
    text: str


class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    doc_type: str
    pages: int


class DealSheet(BaseModel):
    property_name: str
    address: str
    units: int
    strategy: str
    purchase_price: float
    target_hold_years: float
    projected_irr: float | None = None
    projected_moic: float | None = None
    fees: list[str] = Field(default_factory=list)
    sources_uses: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class Financials(BaseModel):
    t12_noi: float | None = None
    in_place_occupancy: float | None = None
    unit_mix: list[str] = Field(default_factory=list)
    proforma_year1_noi: float | None = None
    exit_cap_rate: float | None = None
    market_cap_rate: float | None = None
    citations: list[Citation] = Field(default_factory=list)


class RiskFinding(BaseModel):
    id: str
    title: str
    severity: Severity
    category: str
    classification: Classification
    explanation: str
    evidence: list[Citation] = Field(default_factory=list)


class Answer(BaseModel):
    question: str
    answered: bool
    text: str
    classification: Classification
    citations: list[Citation] = Field(default_factory=list)
