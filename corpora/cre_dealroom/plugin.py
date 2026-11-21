"""Corpus #1: CRE deal room (synthetic Larkveil Residences).

Same rule as every corpus: the model reads, code computes.

  1. Extractor (small model) pulls a fixed vocabulary of facts, each with a
     doc / page / verbatim snippet.
  2. Code verifies every fact: the snippet must appear on the cited page and
     the value must appear in the snippet. Unverified facts are dropped and
     logged, so a hallucinated number never reaches a rule.
  3. Deterministic rules compare facts across documents and compute impact
     (fee dollars, exit-value delta, occupancy gap).
  4. A judgment pass (large model) may surface interpretive issues; these are
     always judgment_required and never carry a computed verdict.

Offline (no API key), steps 1 and 4 replay ``eval/fixtures/cre_llm_fixture.json``,
a hand-recorded extraction that goes through the same verification in step 2.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from agents.llm import call_structured, register_mock
from server.ingest import DocumentIndex
from sightline.core.explain import explain
from sightline.core.plugins import REPO_ROOT, CorpusPlugin
from sightline.core.schema import Citation, Finding

FIXTURE = REPO_ROOT / "eval" / "fixtures" / "cre_llm_fixture.json"

FACTS = {
    "purchase_price": "Purchase price in USD",
    "acquisition_fee_pct": "Acquisition fee as % of purchase price",
    "asset_management_fee_pct": "Asset management fee %",
    "disposition_fee_pct": "Disposition fee %",
    "in_place_occupancy_pct": "Current in-place occupancy %",
    "proforma_year1_occupancy_pct": "Occupancy % assumed for Year 1 in projections",
    "exit_cap_rate_pct": "Exit cap rate % used in projections",
    "market_cap_rate_low_pct": "Low end of prevailing market cap-rate range %",
    "market_cap_rate_high_pct": "High end of prevailing market cap-rate range %",
    "year5_noi": "Projected Year 5 NOI in USD",
    "lease_up_months": "Months allotted to lease up from current to stabilized occupancy (only if stated)",
}
JUDGMENT_TOPICS = ["track_record", "sponsor_quality", "market_timing", "deal_structure", "other"]

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "enum": list(FACTS)},
                    "value": {"type": "number"},
                    "doc_id": {"type": "string"},
                    "page": {"type": "integer"},
                    "snippet": {"type": "string"},
                },
                "required": ["fact", "value", "doc_id", "page", "snippet"],
            },
        }
    },
    "required": ["facts"],
}
JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": JUDGMENT_TOPICS},
                    "title": {"type": "string"},
                    "what_to_weigh": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"doc_id": {"type": "string"}, "page": {"type": "integer"},
                                           "snippet": {"type": "string"}},
                            "required": ["doc_id", "page", "snippet"],
                        },
                    },
                },
                "required": ["topic", "title", "what_to_weigh", "evidence"],
            },
        }
    },
    "required": ["items"],
}

EXTRACT_SYSTEM = (
    "Extract facts from a real-estate deal room. For each fact in the vocabulary, "
    "emit one entry PER DOCUMENT that states it (the same fact stated in two "
    "documents = two entries). Copy the snippet verbatim from the page (label and "
    "value), give the page number, and the numeric value with no units. Omit facts "
    "that are not stated. Do not compute or infer values.\nVocabulary:\n"
    + "\n".join(f"- {k}: {v}" for k, v in FACTS.items())
)
JUDGMENT_SYSTEM = (
    "You review a deal room for interpretive issues that need a human: framing "
    "that may mislead, sponsor quality, market timing, structure. Do NOT report "
    "numeric contradictions between documents (code checks those). Do not give a "
    "verdict; say what a human must weigh. Quote evidence verbatim with page numbers."
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _value_in(value: float, snippet: str) -> bool:
    nums = {Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", snippet)}
    return Decimal(str(value)) in nums


def _fixture_handler(key: str):
    def handler(system: str, user: str) -> dict:
        return json.loads(FIXTURE.read_text())[key]
    return handler


register_mock("extract_cre_facts", _fixture_handler("extract_cre_facts"))
register_mock("surface_judgment_items", _fixture_handler("surface_judgment_items"))


def template(f: Finding) -> tuple[str, str]:
    x = f.facts
    if f.rule == "fact_conflict":
        vals = "; ".join(f"{d}: {v}" for d, v in x["values_by_doc"].items())
        e = f"Documents disagree on {x['fact']} ({vals})."
        if f.amount_usd:
            e += f" On a purchase price of ${x['purchase_price']:,} the gap is ${f.amount_usd:,.0f}."
        return e, f"Please confirm which {x['fact']} figure governs and correct the other document."
    if f.rule == "exit_cap_below_market":
        return (f"The pro forma exits at a {x['exit_cap_rate_pct']}% cap rate, below the market range "
                f"{x['market_low_pct']}-{x['market_high_pct']}%. At the market midpoint "
                f"{x['market_mid_pct']}% the Year 5 NOI of ${x['year5_noi']:,} is worth "
                f"${x['value_at_market_mid']:,} instead of ${x['value_at_exit_cap']:,}, ${f.amount_usd:,.0f} less.",
                "Please provide support for the exit cap rate or a sensitivity at the market range.")
    if f.rule == "occupancy_gap_unbridged":
        return (f"In-place occupancy is {x['in_place_pct']}% but Year 1 assumes {x['year1_pct']}%, a "
                f"{x['gap_pts']}-point jump with no lease-up period stated anywhere in the deal room.",
                "Please provide the lease-up plan, timeline and cost between current and assumed occupancy.")
    return (x.get("what_to_weigh", f.title),
            "Please provide additional context so a reviewer can assess this item.")


class CreDealRoomAudit(CorpusPlugin):
    def audit(self, files: list[Path]) -> list[Finding]:
        pdfs = sorted(p for p in files if p.suffix.lower() == ".pdf")
        index = DocumentIndex(pdfs[0].parent).load()
        fname = {re.sub(r"^\d+_", "", p.stem): p.name for p in pdfs}
        corpus = index.full_corpus_text()

        raw = call_structured(EXTRACT_SYSTEM, corpus, "extract_cre_facts",
                              "Record cited facts.", FACT_SCHEMA, agent="cre_extractor").data["facts"]
        facts = []
        for fct in raw:
            doc = index.documents.get(fct["doc_id"])
            page = doc.pages[fct["page"] - 1] if doc and 0 < fct["page"] <= len(doc.pages) else ""
            if not page or _norm(fct["snippet"]) not in _norm(page):
                self.rejected_mappings.append({"fact": fct, "errors": ["snippet not found on cited page"]})
            elif not _value_in(fct["value"], fct["snippet"]):
                self.rejected_mappings.append({"fact": fct, "errors": ["value not present in snippet"]})
            else:
                facts.append(fct)
        self.stats.update(facts_proposed=len(raw), facts_verified=len(facts))
        self.tables["facts"] = facts

        findings = self._rules(facts, fname)
        judg = call_structured(JUDGMENT_SYSTEM, corpus, "surface_judgment_items",
                               "Record judgment items.", JUDGMENT_SCHEMA, agent="judgment").data["items"]
        for item in judg:
            ev = [e for e in item["evidence"] if (d := index.documents.get(e["doc_id"]))
                  and 0 < e["page"] <= len(d.pages) and _norm(e["snippet"]) in _norm(d.pages[e["page"] - 1])]
            if not ev:
                self.rejected_mappings.append({"judgment": item["title"], "errors": ["no verifiable evidence"]})
                continue
            findings.append(Finding(
                id="", corpus=self.config.name, rule="judgment", title=item["title"], severity="low",
                classification="judgment_required", facts={"what_to_weigh": item["what_to_weigh"]},
                keys={"topic": item["topic"]},
                citations=[Citation(file=fname.get(e["doc_id"], e["doc_id"]), location=f"page {e['page']}",
                                    snippet=e["snippet"]) for e in ev]))
        for i, f in enumerate(findings, start=1):
            f.id = f"C{i:03d}"
        return explain(findings, template)

    def _rules(self, facts: list[dict], fname: dict[str, str]) -> list[Finding]:
        by = defaultdict(list)
        for f in facts:
            by[f["fact"]].append(f)

        def cite(f):
            return Citation(file=fname.get(f["doc_id"], f["doc_id"]), location=f"page {f['page']}", snippet=f["snippet"])

        def one(name):
            return Decimal(str(by[name][0]["value"])) if by.get(name) else None

        out: list[Finding] = []
        price = one("purchase_price")
        for name, group in by.items():
            vals = {Decimal(str(g["value"])) for g in group}
            if len(vals) < 2:
                continue
            amount = None
            if name == "acquisition_fee_pct" and price:
                amount = float((max(vals) - min(vals)) / 100 * price)
            out.append(Finding(
                id="", corpus=self.config.name, rule="fact_conflict",
                title=f"Documents disagree on {name.replace('_', ' ')}", severity="high",
                classification="verifiable", amount_usd=amount,
                facts={"fact": name, "values_by_doc": {g["doc_id"]: g["value"] for g in group},
                       "purchase_price": int(price) if price else None},
                keys={"fact": name}, citations=[cite(g) for g in group]))

        exit_cap, lo, hi, noi = (one("exit_cap_rate_pct"), one("market_cap_rate_low_pct"),
                                 one("market_cap_rate_high_pct"), one("year5_noi"))
        if exit_cap and lo and exit_cap < lo:
            mid = (lo + hi) / 2 if hi else lo
            v_exit = (noi / (exit_cap / 100)).quantize(Decimal(1)) if noi else None
            v_mid = (noi / (mid / 100)).quantize(Decimal(1)) if noi else None
            out.append(Finding(
                id="", corpus=self.config.name, rule="exit_cap_below_market",
                title="Exit cap rate is below the market study's range", severity="high",
                classification="verifiable", amount_usd=float(v_exit - v_mid) if noi else None,
                facts={"exit_cap_rate_pct": float(exit_cap), "market_low_pct": float(lo),
                       "market_high_pct": float(hi) if hi else None, "market_mid_pct": float(mid),
                       "year5_noi": int(noi) if noi else None, "value_at_exit_cap": int(v_exit) if noi else None,
                       "value_at_market_mid": int(v_mid) if noi else None},
                keys={"fact": "exit_cap_rate_pct"},
                citations=[cite(by[k][0]) for k in ("exit_cap_rate_pct", "market_cap_rate_low_pct", "year5_noi") if by.get(k)]))

        cur, y1 = one("in_place_occupancy_pct"), one("proforma_year1_occupancy_pct")
        if cur and y1 and y1 - cur >= 3 and not by.get("lease_up_months"):
            out.append(Finding(
                id="", corpus=self.config.name, rule="occupancy_gap_unbridged",
                title="Year 1 occupancy assumption has no lease-up bridge", severity="medium",
                classification="verifiable", amount_usd=None,
                facts={"in_place_pct": float(cur), "year1_pct": float(y1), "gap_pts": float(y1 - cur)},
                keys={"fact": "occupancy"},
                citations=[cite(by["in_place_occupancy_pct"][0]), cite(by["proforma_year1_occupancy_pct"][0])]))
        return out
