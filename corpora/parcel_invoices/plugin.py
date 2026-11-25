"""Corpus #2: carrier invoices audited against a parcel rate agreement.

Pipeline:
  1. contract PDF  -> RateAgreement (clause/table parser) -> verify_terms
  2. each invoice  -> RawTable -> mapping proposed (LLM or heuristic)
                   -> validated (types, row count, totals) -> canonical lines
  3. rules.run_all -> Hits with amounts computed in Decimal
  4. Findings with file/row citations -> explainer adds prose only
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from corpora.parcel_invoices import rules
from corpora.parcel_invoices.contract import RateAgreement, parse_rate_agreement, verify_terms
from sightline.core.explain import explain
from sightline.core.plugins import CorpusPlugin
from sightline.core.schema import Citation, Finding
from sightline.ingest.mapping import CanonicalSchema, FieldSpec, MappingRejected, ingest_table
from sightline.ingest.tables import read_any

SVC = {"GROUND": ["GND", "Ground", "GRD"], "2DAY": ["2DA", "2nd Day", "2 Day", "Second Day"],
       "NEXTDAY": ["NDA", "Next Day", "Overnight", "1 Day"]}

INVOICE_SCHEMA = CanonicalSchema(
    name="parcel_invoice_line",
    total_field="total",
    fields=[
        FieldSpec("tracking_number", "str", synonyms=["tracking #", "tracking", "trackingnumber", "tracking no"]),
        FieldSpec("line_type", "enum", required=False, default="SHIP", enum=["SHIP", "ADJ"],
                  enum_synonyms={"SHIP": ["SHP", "shipment"], "ADJ": ["adjustment", "adj"]},
                  synonyms=["linetype", "record type", "type code"],
                  description="SHIP for a shipment line, ADJ for a later adjustment to an earlier shipment"),
        FieldSpec("ship_date", "date", synonyms=["shipdate", "date", "pickup date"]),
        FieldSpec("service", "enum", enum=list(SVC), enum_synonyms=SVC, synonyms=["svc", "servicelevel", "service level"]),
        FieldSpec("origin_zip", "str", required=False, default="", synonyms=["orig zip", "originpostal", "from"]),
        FieldSpec("dest_zip", "str", synonyms=["dest zip", "destinationpostal", "dest", "to", "ship to zip"]),
        FieldSpec("address_type", "enum", enum=["RES", "COM"],
                  enum_synonyms={"RES": ["R", "Residential"], "COM": ["C", "Commercial"]},
                  synonyms=["res/com", "deliverytype", "type", "delivery type"]),
        FieldSpec("length", "decimal", synonyms=["l (in)", "l", "length in"]),
        FieldSpec("width", "decimal", synonyms=["w (in)", "w", "width in"]),
        FieldSpec("height", "decimal", synonyms=["h (in)", "h", "height in"]),
        FieldSpec("actual_weight", "decimal", synonyms=["act wt", "actualweightlb", "actwt", "actual weight"]),
        FieldSpec("billed_weight", "decimal", synonyms=["bill wt", "billedweightlb", "billwt", "billed weight"]),
        FieldSpec("zone", "int", synonyms=["billzone", "zn", "bill zone"]),
        FieldSpec("freight", "decimal", synonyms=["transportationcharge", "transport charge", "net freight"]),
        FieldSpec("fuel", "decimal", synonyms=["fuel surch", "fuelsurcharge", "fuel surcharge"]),
        FieldSpec("residential_fee", "decimal", required=False, default=Decimal("0"),
                  synonyms=["resi surch", "residentialsurcharge", "resi", "residential"]),
        FieldSpec("address_correction_fee", "decimal", required=False, default=Decimal("0"),
                  synonyms=["addr corr", "addresscorrection", "addrcorr", "address correction"]),
        FieldSpec("other_charge", "decimal", required=False, default=Decimal("0"),
                  synonyms=["misc chg", "othercharge", "other", "misc"]),
        FieldSpec("other_charge_desc", "str", required=False, default="",
                  synonyms=["misc desc", "otherchargedescription", "other desc"]),
        FieldSpec("total", "decimal", synonyms=["line total", "netamount", "net amount", "amount"]),
        FieldSpec("recipient", "str", required=False, default="", synonyms=["consigneename", "ship to", "consignee"]),
    ],
)

TITLES = {
    "duplicate_tracking": "Tracking number billed twice",
    "line_total_mismatch": "Line total does not equal its charges",
    "wrong_zone": "Billed in the wrong zone",
    "billed_weight_exceeds_billable": "Billed weight above billable (actual/DIM) weight",
    "missed_discount": "Contract discount not applied",
    "rate_mismatch": "Freight differs from contract rate",
    "fuel_rate_mismatch": "Fuel surcharge % does not match contract",
    "residential_fee_on_commercial": "Residential fee on a commercial address",
    "accessorial_rate_mismatch": "Accessorial billed at a non-contract rate",
    "repeated_address_correction": "Address correction fee billed more than once",
    "residential_fee_business_name": "Residential fee on what may be a business address",
    "unlisted_accessorial": "Charge not priced in the agreement",
    "adjustment_without_shipment": "Adjustment for a shipment not on these invoices",
}

CONTRACT_CLAUSE = {
    "fuel_rate_mismatch": "fuel_pct", "residential_fee_on_commercial": "residential_fee",
    "residential_fee_business_name": "residential_fee", "repeated_address_correction": "address_correction_fee",
    "billed_weight_exceeds_billable": "dim_divisor",
}


def _snippet(ln) -> str:
    return (f"{ln['tracking_number']} {ln['line_type']} {ln['service']} zone {ln['zone']} "
            f"bill wt {ln['billed_weight']} freight {ln['freight']} fuel {ln['fuel']} "
            f"resi {ln['residential_fee']} addr {ln['address_correction_fee']} other {ln['other_charge']} "
            f"total {ln['total']}")


def template(f: Finding) -> tuple[str, str]:
    x, amt = f.facts, (f"${f.amount_usd:,.2f}" if f.amount_usd is not None else "")
    trk = ", ".join(f.keys.get("tracking_numbers", [])) or f.keys.get("invoice_id", "")
    expl = {
        "duplicate_tracking": f"{trk} appears on invoice {x.get('first_invoice')} and again on "
                              f"{x.get('repeat_invoice')}. A package ships once, so the repeat is a duplicate"
                              + (f"; {x.get('already_credited')} was already credited, so {amt} is still owed back."
                                 if x.get("already_credited") else f" ({amt})."),
        "line_total_mismatch": f"The line total {x.get('billed_total')} is not the sum of its charges "
                               f"({x.get('sum_of_charges')}); difference {amt}.",
        "wrong_zone": f"Destination {x.get('dest_zip')} is zone {x.get('contract_zone')} in the zone chart, but "
                      f"the line was billed as zone {x.get('billed_zone')}. Overcharge incl. fuel: {amt}.",
        "billed_weight_exceeds_billable": f"Billed at {x.get('billed_weight')} lb. Actual {x.get('actual_weight')} lb, "
                      f"DIM {x.get('dim_weight')} lb ({x.get('dims')} / {x.get('dim_divisor')}), so billable is "
                      f"{x.get('billable_weight')} lb. Overcharge incl. fuel: {amt}.",
        "missed_discount": f"Freight {x.get('billed_freight')} equals the list rate; the contract discount of "
                           f"{x.get('discount_pct')}% was not applied. Overcharge incl. fuel: {amt}.",
        "rate_mismatch": f"Freight {x.get('billed_freight')} vs contract {x.get('contract_freight')}. Overcharge {amt}.",
        "fuel_rate_mismatch": f"{x.get('lines_affected')} lines on {x.get('invoice_id')} carry fuel at about "
                              f"{x.get('implied_billed_fuel_pct')}% of freight; the agreement fixes it at "
                              f"{x.get('contract_fuel_pct')}%. Overcharge: {amt}.",
        "residential_fee_on_commercial": f"The invoice marks {trk} as commercial yet adds a residential fee of {amt}.",
        "accessorial_rate_mismatch": f"{x.get('charge')} billed at {x.get('billed_fee')} vs contract "
                                     f"{x.get('contract_fee')}.",
        "repeated_address_correction": f"Address correction on {trk} was billed {x.get('times_billed')} times; the "
                                       f"agreement allows it once. Overcharge: {amt}.",
        "residential_fee_business_name": f"{trk} was classed residential and charged {x.get('residential_fee')}, but "
                      f"the consignee '{x.get('recipient')}' contains '{x.get('marker')}'. It may be a home business "
                      "(fee valid) or a commercial address (fee invalid). A human should check the address.",
        "adjustment_without_shipment": f"{trk} has an adjustment ({x.get('kind')}) of {x.get('adjustment_total')} on "
                      f"{x.get('invoice_id')}, but no shipment line for it is on the invoices provided. It may belong "
                      "to an earlier invoice; check that invoice before paying the charge or counting the credit.",
        "unlisted_accessorial": f"{trk} carries a {x.get('charge')} charge '{x.get('description')}' that the agreement "
                      "does not price. Clause 1.9 defers unlisted accessorials to the carrier's service guide, so "
                      "whether it is valid depends on that guide and the package.",
    }.get(f.rule, f.title)
    if f.classification == "judgment_required":
        note = (f"Please confirm the basis for the charge on {trk} and provide supporting detail "
                "(address classification or service-guide reference) before we accept it.")
    else:
        note = (f"We dispute {amt} on {trk}: {f.title.lower()}. Per our rate agreement this charge should be "
                "corrected. Please issue a credit within the dispute window.")
    return expl, note


class ParcelInvoiceAudit(CorpusPlugin):
    def _split(self, files: list[Path]) -> tuple[Path, list[Path]]:
        import pdfplumber

        marker = self.config.raw.get("contract_marker", "rate agreement").lower()
        contract, invoices = None, []
        for f in sorted(files):
            if f.suffix.lower() == ".pdf":
                with pdfplumber.open(f) as pdf:
                    first = (pdf.pages[0].extract_text() or "").lower()
                if marker in first:
                    contract = f
                    continue
            invoices.append(f)
        if contract is None:
            raise ValueError("No rate agreement found among the uploaded files.")
        return contract, invoices

    def load_terms(self, contract: Path) -> RateAgreement:
        terms, pages = parse_rate_agreement(contract)
        errs = verify_terms(terms, pages)
        if errs:
            raise ValueError("Contract terms failed verification: " + "; ".join(errs))
        return terms

    def load_lines(self, invoices: list[Path]) -> list[dict]:
        lines: list[dict] = []
        for inv in invoices:
            table = read_any(inv)
            try:
                rows, mapping = ingest_table(table, INVOICE_SCHEMA, self.rejected_mappings)
            except MappingRejected:
                self.stats.setdefault("files_rejected", []).append(inv.name)
                continue
            self.stats.setdefault("files", []).append(
                {"file": inv.name, "rows": len(rows), "mapping_by": mapping.proposed_by,
                 "invoice_id": mapping.control_totals.get("invoice_id"),
                 "stated_total": mapping.control_totals.get("total_amount")})
            lines.extend(rows)
        return lines

    def audit(self, files: list[Path]) -> list[Finding]:
        contract, invoices = self._split(files)
        terms = self.load_terms(contract)
        self.terms = terms
        lines = self.load_lines(invoices)
        self.lines = lines
        self.tables["invoice_lines"] = [
            {k: (str(v) if isinstance(v, Decimal) else v) for k, v in ln.items()} for ln in lines]
        hits = rules.run_all(lines, terms)
        findings: list[Finding] = []
        for i, h in enumerate(hits, start=1):
            cites = [Citation(file=ln["_file"], location=ln["_location"], snippet=_snippet(ln)) for ln in h.lines[:5]]
            clause = CONTRACT_CLAUSE.get(h.rule)
            if clause and clause in terms.citations:
                c = terms.citations[clause]
                cites.append(Citation(file=terms.source_file, location=f"page {c.page}", snippet=c.text))
            if h.rule == "wrong_zone":
                cites.append(Citation(file=terms.source_file, location="Schedule C", snippet="zone chart"))
            findings.append(Finding(
                id=f"P{i:03d}", corpus=self.config.name, rule=h.rule, title=TITLES.get(h.rule, h.rule),
                severity=h.severity, classification=h.classification,
                amount_usd=None if h.amount is None else float(h.amount),
                facts={k: (str(v) if isinstance(v, Decimal) else v) for k, v in h.facts.items()},
                keys=h.keys, citations=cites,
            ))
        self.stats["lines"] = len(lines)
        self.stats["recoverable_usd"] = round(sum(f.amount_usd or 0 for f in findings
                                                  if f.classification == "verifiable"), 2)
        return explain(findings, template)
