"""Format readers: CSV / XLSX / PDF -> RawTable.

These know about file *formats*, never about a particular sender's layout.
Which column means what is decided later by the mapping layer.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RawRow:
    location: str          # "row 7", "Detail!R12", "page 2, row 5"
    values: list[str]


@dataclass
class RawTable:
    source_file: str
    header: list[str]
    rows: list[RawRow]
    context_text: str = ""  # text around the table (summary blocks, comments)
    pages: dict[int, str] = field(default_factory=dict)  # for PDFs: page -> text

    def sample(self, n: int = 5) -> list[list[str]]:
        return [r.values for r in self.rows[:n]]


def _clean(v) -> str:
    if v is None:
        return ""
    return str(v).replace("\n", " ").strip()


def read_csv(path: Path) -> RawTable:
    context: list[str] = []
    header: list[str] | None = None
    rows: list[RawRow] = []
    with path.open(newline="") as f:
        for lineno, rec in enumerate(csv.reader(f), start=1):
            if not rec or all(not c.strip() for c in rec):
                continue
            if rec[0].lstrip().startswith("#"):
                context.append(",".join(rec).lstrip("# ").strip())
                continue
            if header is None:
                header = [_clean(c) for c in rec]
                continue
            rows.append(RawRow(f"row {lineno}", [_clean(c) for c in rec]))
    return RawTable(path.name, header or [], rows, "\n".join(context))


def read_xlsx(path: Path) -> RawTable:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    sheets = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    data_name = max(sheets, key=lambda k: len(sheets[k]))
    context_parts = []
    for name, grid in sheets.items():
        if name == data_name:
            continue
        for r in grid:
            cells = [_clean(c) for c in r if _clean(c)]
            if cells:
                context_parts.append(f"[{name}] " + ": ".join(cells))
    grid = sheets[data_name]
    header_idx = next(i for i, r in enumerate(grid) if sum(1 for c in r if _clean(c)) >= 3)
    header = [_clean(c) for c in grid[header_idx]]
    rows = [
        RawRow(f"{data_name}!R{i + 1}", [_clean(c) for c in r][: len(header)])
        for i, r in enumerate(grid[header_idx + 1:], start=header_idx + 1)
        if any(_clean(c) for c in r)
    ]
    return RawTable(path.name, header, rows, "\n".join(context_parts))


def read_pdf_table(path: Path) -> RawTable:
    import pdfplumber

    header: list[str] | None = None
    rows: list[RawRow] = []
    pages: dict[int, str] = {}
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            pages[pno] = page.extract_text() or ""
            for table in page.extract_tables():
                for rno, rec in enumerate(table, start=1):
                    vals = [_clean(c) for c in rec]
                    if header is None:
                        header = vals
                        continue
                    if vals == header or not any(vals):
                        continue
                    rows.append(RawRow(f"page {pno}, row {rno}", vals))
    # context = page-1 text above the table, plus any "total" lines at the end
    first = pages.get(1, "").splitlines()
    head0 = (header or [""])[0]
    cut = next((i for i, ln in enumerate(first) if head0 and ln.startswith(head0)), len(first))
    tail = [ln for ln in pages.get(max(pages) if pages else 1, "").splitlines()[-5:] if "total" in ln.lower()]
    context = "\n".join(first[:cut] + tail)
    return RawTable(path.name, header or [], rows, context, pages)


def read_any(path: Path) -> RawTable:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv(path)
    if suffix in (".xlsx", ".xlsm"):
        return read_xlsx(path)
    if suffix == ".pdf":
        return read_pdf_table(path)
    raise ValueError(f"Unsupported file type: {path.name}")
