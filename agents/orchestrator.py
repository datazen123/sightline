"""Orchestrator: the brain. Owns the document index and context log, routes
requests to specialist agents, and caches expensive (LLM-backed) extraction
results so repeated calls (e.g. from the UI or MCP tools) don't re-run them.
"""

from __future__ import annotations

from pathlib import Path

from agents import extractor, investor_qa, risk, summarizer
from agents.context_log import ContextLog
from server.ingest import DocumentIndex
from server.schema import Answer, DealSheet, Financials, RiskFinding

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cre_dealroom"


class Orchestrator:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR) -> None:
        self.index = DocumentIndex(data_dir).load()
        self.log = ContextLog()
        self._deal_sheet: DealSheet | None = None
        self._financials: Financials | None = None
        self._risks: list[RiskFinding] | None = None

    def list_documents(self):
        return self.index.list_documents()

    def get_document(self, doc_id: str):
        return self.index.get_document(doc_id)

    def search_docs(self, query: str, k: int = 5):
        return self.index.search(query, k=k)

    def get_deal_terms(self) -> DealSheet:
        self._ensure_extracted()
        assert self._deal_sheet is not None
        return self._deal_sheet

    def get_financials(self) -> Financials:
        self._ensure_extracted()
        assert self._financials is not None
        return self._financials

    def flag_risks(self) -> list[RiskFinding]:
        if self._risks is None:
            self._risks = risk.flag_risks(self.index, self.log)
        return self._risks

    def ask(self, question: str) -> Answer:
        return investor_qa.answer_question(question, self.index, self.log)

    def diligence_memo(self) -> str:
        self._ensure_extracted()
        risks = self.flag_risks()
        assert self._deal_sheet is not None and self._financials is not None
        return summarizer.draft_diligence_memo(self._deal_sheet, self._financials, risks, self.log)

    def investor_summary(self) -> str:
        self._ensure_extracted()
        assert self._deal_sheet is not None and self._financials is not None
        return summarizer.draft_investor_summary(self._deal_sheet, self._financials, self.log)

    def _ensure_extracted(self) -> None:
        if self._deal_sheet is None or self._financials is None:
            self._deal_sheet, self._financials = extractor.extract(self.index, self.log)
