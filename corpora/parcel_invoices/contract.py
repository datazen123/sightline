"""Rate agreement terms and the pricing arithmetic.

All money math is Decimal, rounded half-up to the cent, in one place, so the
auditor, the scenario CLI and the tests agree on every cent.

Terms are read from the rate-agreement PDF by an extractor (LLM, or the
offline table parser below). Before any term is trusted, ``verify_terms``
checks completeness, sane ranges, and that every number appears verbatim on
the page it is cited from.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")
SERVICES = ["GROUND", "2DAY", "NEXTDAY"]
ZONES = list(range(2, 9))


def money(x: Decimal | float | int | str) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class TermCitation:
    page: int
    text: str


@dataclass
class RateAgreement:
    origin_zip3: str
    fuel_pct: Decimal
    residential_fee: Decimal
    address_correction_fee: Decimal
    dim_divisor: int
    zone_chart: list[tuple[int, int, int]]  # (dest zip3 low, high, zone)
    list_rates: dict[tuple[str, int], tuple[Decimal, Decimal]]  # (svc, zone) -> (first lb, each addl lb)
    discounts: dict[tuple[str, int], Decimal]  # (svc, zone) -> percent off list
    listed_accessorials: list[str] = field(default_factory=lambda: ["RESIDENTIAL", "ADDRESS CORRECTION", "FUEL"])
    source_file: str = ""
    citations: dict[str, TermCitation] = field(default_factory=dict)

    # --- deterministic pricing -------------------------------------------
    def zone_for(self, dest_zip: str) -> int | None:
        z3 = int(str(dest_zip)[:3])
        for lo, hi, zone in self.zone_chart:
            if lo <= z3 <= hi:
                return zone
        return None

    def dim_weight(self, length: Decimal, width: Decimal, height: Decimal) -> int:
        return math.ceil(Decimal(length) * Decimal(width) * Decimal(height) / Decimal(self.dim_divisor))

    def billable_weight(self, actual: Decimal, length: Decimal, width: Decimal, height: Decimal) -> int:
        return max(math.ceil(Decimal(actual)), self.dim_weight(length, width, height))

    def list_rate(self, service: str, zone: int, weight: int) -> Decimal:
        first, addl = self.list_rates[(service, zone)]
        return money(first + addl * (max(weight, 1) - 1))

    def discount_pct(self, service: str, zone: int) -> Decimal:
        return self.discounts[(service, zone)]

    def net_transport(self, service: str, zone: int, weight: int, gri_pct: Decimal = Decimal(0)) -> Decimal:
        lst = self.list_rate(service, zone, weight)
        if gri_pct:
            lst = money(lst * (1 + gri_pct / 100))
        return money(lst * (1 - self.discount_pct(service, zone) / 100))

    def fuel(self, transport: Decimal) -> Decimal:
        return money(transport * self.fuel_pct / 100)


# ---------------------------------------------------------------------------
# Verification (no model involved)
# ---------------------------------------------------------------------------
def verify_terms(terms: RateAgreement, pages: dict[int, str]) -> list[str]:
    errs: list[str] = []
    if not (Decimal(0) < terms.fuel_pct < Decimal(40)):
        errs.append(f"fuel_pct out of range: {terms.fuel_pct}")
    if not (100 <= terms.dim_divisor <= 250):
        errs.append(f"dim_divisor out of range: {terms.dim_divisor}")
    for svc in SERVICES:
        for z in ZONES:
            if (svc, z) not in terms.list_rates:
                errs.append(f"missing list rate for {svc} zone {z}")
            if (svc, z) not in terms.discounts:
                errs.append(f"missing discount for {svc} zone {z}")
            elif not (Decimal(0) <= terms.discounts[(svc, z)] < Decimal(90)):
                errs.append(f"discount out of range for {svc} zone {z}")
    covered = sorted((lo, hi) for lo, hi, _ in terms.zone_chart)
    if not covered or covered[0][0] > 100 or covered[-1][1] < 999:
        errs.append("zone chart does not cover destination ZIP3 100-999")
    # every cited scalar must literally appear on its cited page
    for key, cit in terms.citations.items():
        page_text = re.sub(r"\s+", " ", pages.get(cit.page, ""))
        if re.sub(r"\s+", " ", cit.text) not in page_text:
            errs.append(f"citation for '{key}' not found on page {cit.page}: {cit.text!r}")
    scalars = {
        "fuel_pct": f"{terms.fuel_pct}%",
        "residential_fee": f"${terms.residential_fee}",
        "address_correction_fee": f"${terms.address_correction_fee}",
        "dim_divisor": str(terms.dim_divisor),
    }
    for key, literal in scalars.items():
        cit = terms.citations.get(key)
        if cit is None or literal not in cit.text:
            errs.append(f"value for '{key}' ({literal}) is not supported by its citation")
    return errs


# ---------------------------------------------------------------------------
# Offline extractor: reads the agreement's labelled clauses and schedules.
# (With an API key the LLM extractor in plugin.py is tried first; both go
# through verify_terms.)
# ---------------------------------------------------------------------------
def _find(pages: dict[int, str], pattern: str) -> tuple[re.Match, int, str]:
    for pno, text in pages.items():
        for line in text.splitlines():
            m = re.search(pattern, line, re.I)
            if m:
                return m, pno, line.strip()
    raise ValueError(f"clause not found: {pattern}")


SVC_ALIASES = {"ground": "GROUND", "2day": "2DAY", "2nd day": "2DAY", "second day": "2DAY",
               "nextday": "NEXTDAY", "next day": "NEXTDAY", "overnight": "NEXTDAY"}


def _svc(raw: str) -> str:
    k = raw.strip().lower()
    return SVC_ALIASES.get(k, SVC_ALIASES.get(k.replace(" ", ""), raw.upper()))


def _zones(raw: str) -> list[int]:
    nums = [int(n) for n in re.findall(r"\d+", raw)]
    return list(range(nums[0], nums[-1] + 1)) if len(nums) >= 2 else nums


def parse_rate_agreement(path: Path) -> tuple[RateAgreement, dict[int, str]]:
    import pdfplumber

    pages: dict[int, str] = {}
    tables: list[list[list[str]]] = []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            pages[pno] = page.extract_text() or ""
            tables += [[[(c or "").strip() for c in r] for r in t] for t in page.extract_tables()]

    cites: dict[str, TermCitation] = {}
    m, p, line = _find(pages, r"fuel surcharge[^0-9]*([0-9]+(?:\.[0-9]+)?)%")
    fuel = Decimal(m.group(1))
    cites["fuel_pct"] = TermCitation(p, line)
    m, p, line = _find(pages, r"residential[^$]*\$([0-9]+\.[0-9]{2})")
    resi = Decimal(m.group(1))
    cites["residential_fee"] = TermCitation(p, line)
    m, p, line = _find(pages, r"address correction[^$]*\$([0-9]+\.[0-9]{2})")
    adcorr = Decimal(m.group(1))
    cites["address_correction_fee"] = TermCitation(p, line)
    m, p, line = _find(pages, r"divisor[^0-9]*([0-9]{3})")
    divisor = int(m.group(1))
    cites["dim_divisor"] = TermCitation(p, line)
    m, p, line = _find(pages, r"origin.*?ZIP3\s+([0-9]{3})")
    origin = m.group(1)

    list_rates, discounts, chart = {}, {}, []
    for t in tables:
        head = " ".join(t[0]).lower()
        if "first lb" in head:
            for r in t[1:]:
                list_rates[(_svc(r[0]), int(r[1]))] = (Decimal(r[2].lstrip("$")), Decimal(r[3].lstrip("$")))
        elif "discount" in head:
            for r in t[1:]:
                for z in _zones(r[1]):
                    discounts[(_svc(r[0]), z)] = Decimal(r[2].rstrip("%"))
        elif "zip" in head and "zone" in head:
            for r in t[1:]:
                lo, hi = (int(x) for x in re.findall(r"\d{3}", r[0])[:2])
                chart.append((lo, hi, int(r[1])))
    terms = RateAgreement(origin, fuel, resi, adcorr, divisor, chart, list_rates, discounts,
                          source_file=path.name, citations=cites)
    return terms, pages
