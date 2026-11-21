"""Template for a third corpus. Copy to corpora/<name>/plugin.py.

Recipe (see docs/ARCHITECTURE.md, "Adding a corpus"):
  1. Describe the canonical row as a CanonicalSchema. The mapping layer maps
     any CSV/XLSX/PDF table onto it and refuses rows that do not reconcile.
  2. Read the governing document (contract, order form) into typed terms and
     verify every term against the page it came from.
  3. Write each check as a pure function: rows + terms -> findings with
     amounts computed in Decimal. Unit-test each one.
  4. Pass findings to sightline.core.explain.explain with a template, so the
     LLM adds prose but can never add numbers.
"""

from __future__ import annotations

from pathlib import Path

from sightline.core.explain import explain
from sightline.core.plugins import CorpusPlugin
from sightline.core.schema import Finding
from sightline.ingest.mapping import CanonicalSchema, FieldSpec, MappingRejected, ingest_table
from sightline.ingest.tables import read_any

SCHEMA = CanonicalSchema(
    name="invoice_line",
    total_field="amount",
    fields=[
        FieldSpec("sku", "str", synonyms=["item", "product code"]),
        FieldSpec("quantity", "decimal", synonyms=["qty", "seats"]),
        FieldSpec("unit_price", "decimal", synonyms=["price", "rate"]),
        FieldSpec("amount", "decimal", synonyms=["line total", "extended"]),
    ],
)


class TemplateAudit(CorpusPlugin):
    def audit(self, files: list[Path]) -> list[Finding]:
        rows = []
        for f in files:
            try:
                got, _ = ingest_table(read_any(f), SCHEMA, self.rejected_mappings)
                rows += got
            except MappingRejected:
                continue
        findings: list[Finding] = []
        for i, r in enumerate(rows):
            expected = r["quantity"] * r["unit_price"]
            if expected != r["amount"]:
                findings.append(Finding(
                    id=f"V{i:03d}", corpus=self.config.name, rule="extension_error",
                    title="Quantity x price does not equal amount", severity="low",
                    classification="verifiable", amount_usd=float(r["amount"] - expected),
                    facts={"quantity": str(r["quantity"]), "unit_price": str(r["unit_price"]),
                           "amount": str(r["amount"])}, keys={"sku": r["sku"]}))
        return explain(findings, lambda f: (f.title, f"Please correct {f.keys['sku']}."))
