"""PDF -> text -> chunk in-memory index.

Deliberately simple: one chunk per page, keyword-overlap search. The
Larkveil corpus is 8 short documents, so a vector DB / embedding index
would be over-engineering for this demo (see docs/build-spec.md, "legible
over clever").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from server.schema import Chunk, DocumentSummary

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is",
    "at", "by", "with", "as", "that", "this", "it", "was", "are", "be",
}


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9%$.]+", text.lower()) if w not in _STOPWORDS]


def _title_from_filename(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^\d+_", "", stem)
    return stem.replace("_", " ").title()


@dataclass
class DocumentRecord:
    doc_id: str
    title: str
    doc_type: str
    pages: list[str]
    full_text: str


@dataclass
class DocumentIndex:
    data_dir: Path
    documents: dict[str, DocumentRecord] = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)

    def load(self) -> DocumentIndex:
        pdf_paths = sorted(self.data_dir.glob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(
                f"No PDFs found in {self.data_dir}. "
                "Run: uv run python data/generate_cre_dealroom.py"
            )
        for pdf_path in pdf_paths:
            doc_id = re.sub(r"^\d+_", "", pdf_path.stem)
            title = _title_from_filename(pdf_path)
            pages: list[str] = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    pages.append(page.extract_text() or "")
            full_text = "\n\n".join(pages)
            self.documents[doc_id] = DocumentRecord(
                doc_id=doc_id,
                title=title,
                doc_type=doc_id,
                pages=pages,
                full_text=full_text,
            )
            for i, page_text in enumerate(pages, start=1):
                if not page_text.strip():
                    continue
                self.chunks.append(
                    Chunk(
                        doc_id=doc_id,
                        doc_title=title,
                        location=f"page {i}",
                        text=page_text,
                    )
                )
        return self

    def list_documents(self) -> list[DocumentSummary]:
        return [
            DocumentSummary(
                doc_id=d.doc_id, title=d.title, doc_type=d.doc_type, pages=len(d.pages)
            )
            for d in self.documents.values()
        ]

    def get_document(self, doc_id: str) -> DocumentRecord:
        if doc_id not in self.documents:
            raise KeyError(f"Unknown doc_id: {doc_id}")
        return self.documents[doc_id]

    def search(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []
        scored: list[tuple[Chunk, float]] = []
        for chunk in self.chunks:
            chunk_tokens = _tokenize(chunk.text)
            if not chunk_tokens:
                continue
            overlap = sum(1 for t in chunk_tokens if t in query_tokens)
            if overlap == 0:
                continue
            score = overlap / (len(query_tokens) ** 0.5)
            scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def full_corpus_text(self) -> str:
        """All documents concatenated with headers, for extraction/risk agents."""
        parts = []
        for doc in self.documents.values():
            parts.append(f"=== DOCUMENT: {doc.title} (doc_id={doc.doc_id}) ===")
            for i, page_text in enumerate(doc.pages, start=1):
                parts.append(f"--- page {i} ---\n{page_text}")
        return "\n\n".join(parts)
