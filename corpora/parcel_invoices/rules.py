"""Deterministic invoice-vs-contract checks. No model is involved here.

Each check takes canonical invoice lines (typed by the mapping validator) and
the verified contract terms, and returns ``Hit`` objects with the dollar
impact already computed. Attribution is exclusive per line so one overcharge
is never counted twice: zone > weight > missed discount > other rate error.
Fuel is checked separately against the *billed* freight, so a fuel error and
a freight error on the same line do not overlap.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from corpora.parcel_invoices.contract import RateAgreement, money

ZERO = Decimal("0.00")
BUSINESS_MARKERS = re.compile(r"\b(LLC|INC|CORP|LTD|CO\.|STE|SUITE|COMPANY)\b", re.I)


@dataclass
class Hit:
    rule: str
    classification: str
    severity: str
    lines: list[dict[str, Any]]
    amount: Decimal | None
    facts: dict[str, Any] = field(default_factory=dict)
    keys: dict[str, Any] = field(default_factory=dict)


def _ship(lines):
    return [ln for ln in lines if ln.get("line_type", "SHIP") == "SHIP"]


def check_duplicates(lines, terms: RateAgreement) -> list[Hit]:
    by_trk = defaultdict(list)
    for ln in _ship(lines):
        by_trk[ln["tracking_number"]].append(ln)
    hits = []
    for trk, group in by_trk.items():
        if len(group) < 2:
            continue
        for dup in group[1:]:
            hits.append(Hit("duplicate_tracking", "verifiable", "high", [group[0], dup], dup["total"],
                            {"tracking_number": trk, "times_billed": len(group),
                             "first_invoice": group[0].get("_invoice_id"), "repeat_invoice": dup.get("_invoice_id"),
                             "duplicate_total": dup["total"]},
                            {"tracking_numbers": [trk]}))
    return hits


def check_line_totals(lines, terms) -> list[Hit]:
    hits = []
    for ln in lines:
        parts = ln["freight"] + ln["fuel"] + ln["residential_fee"] + ln["address_correction_fee"] + ln["other_charge"]
        diff = money(ln["total"] - parts)
        if diff != ZERO:
            hits.append(Hit("line_total_mismatch", "verifiable", "medium", [ln], diff,
                            {"billed_total": ln["total"], "sum_of_charges": money(parts), "difference": diff},
                            {"tracking_numbers": [ln["tracking_number"]]}))
    return hits


def expected_transport(ln, terms: RateAgreement) -> dict[str, Any]:
    zone = terms.zone_for(ln["dest_zip"])
    dim = terms.dim_weight(ln["length"], ln["width"], ln["height"])
    bw = terms.billable_weight(ln["actual_weight"], ln["length"], ln["width"], ln["height"])
    return {"zone": zone, "dim_weight": dim, "billable_weight": bw,
            "freight": terms.net_transport(ln["service"], zone, bw),
            "list_rate": terms.list_rate(ln["service"], zone, bw),
            "discount_pct": terms.discount_pct(ln["service"], zone)}


def check_transport(lines, terms: RateAgreement) -> list[Hit]:
    hits = []
    for ln in _ship(lines):
        exp = expected_transport(ln, terms)
        billed_zone, billed_wt = int(ln["zone"]), int(ln["billed_weight"])
        billed, expected = ln["freight"], exp["freight"]
        delta = money((billed - expected) + (terms.fuel(billed) - terms.fuel(expected)))
        if delta <= ZERO:
            continue  # correct, or under-billed (not a recovery)
        facts = {"billed_freight": billed, "contract_freight": expected,
                 "overcharge_incl_fuel": delta, "fuel_pct": terms.fuel_pct}
        keys = {"tracking_numbers": [ln["tracking_number"]]}
        if billed_zone != exp["zone"]:
            facts.update(billed_zone=billed_zone, contract_zone=exp["zone"], dest_zip=ln["dest_zip"])
            hits.append(Hit("wrong_zone", "verifiable", "medium", [ln], delta, facts, keys))
        elif billed_wt > exp["billable_weight"]:
            facts.update(billed_weight=billed_wt, actual_weight=ln["actual_weight"],
                         dim_weight=exp["dim_weight"], billable_weight=exp["billable_weight"],
                         dims=f"{ln['length']}x{ln['width']}x{ln['height']}", dim_divisor=terms.dim_divisor)
            hits.append(Hit("billed_weight_exceeds_billable", "verifiable", "medium", [ln], delta, facts, keys))
        elif billed == terms.list_rate(ln["service"], billed_zone, billed_wt) and exp["discount_pct"] > 0:
            facts.update(list_rate=exp["list_rate"], discount_pct=exp["discount_pct"], service=ln["service"],
                         zone=billed_zone)
            hits.append(Hit("missed_discount", "verifiable", "medium", [ln], delta, facts, keys))
        else:
            hits.append(Hit("rate_mismatch", "verifiable", "low", [ln], delta, facts, keys))
    return hits


def check_fuel(lines, terms: RateAgreement) -> list[Hit]:
    by_inv = defaultdict(list)
    for ln in _ship(lines):
        if ln["fuel"] != terms.fuel(ln["freight"]):
            by_inv[(ln["_file"], ln.get("_invoice_id"))].append(ln)
    hits = []
    for (_file, inv), bad in by_inv.items():
        delta = money(sum(ln["fuel"] - terms.fuel(ln["freight"]) for ln in bad))
        if delta <= ZERO:
            continue
        freight = sum(ln["freight"] for ln in bad)
        implied = (sum(ln["fuel"] for ln in bad) / freight * 100).quantize(Decimal("0.01")) if freight else None
        hits.append(Hit("fuel_rate_mismatch", "verifiable", "high", bad, delta,
                        {"invoice_id": inv, "lines_affected": len(bad), "contract_fuel_pct": terms.fuel_pct,
                         "implied_billed_fuel_pct": implied, "overcharge": delta},
                        {"invoice_id": inv}))
    return hits


def check_residential(lines, terms: RateAgreement) -> list[Hit]:
    hits = []
    for ln in _ship(lines):
        fee = ln["residential_fee"]
        if fee <= ZERO:
            continue
        keys = {"tracking_numbers": [ln["tracking_number"]]}
        if ln["address_type"] == "COM":
            hits.append(Hit("residential_fee_on_commercial", "verifiable", "low", [ln], fee,
                            {"residential_fee": fee, "address_type_on_invoice": "COM"}, keys))
        elif fee != terms.residential_fee:
            hits.append(Hit("accessorial_rate_mismatch", "verifiable", "low", [ln], money(fee - terms.residential_fee),
                            {"billed_fee": fee, "contract_fee": terms.residential_fee, "charge": "residential"}, keys))
        elif BUSINESS_MARKERS.search(ln.get("recipient") or ""):
            hits.append(Hit("residential_fee_business_name", "judgment_required", "low", [ln], None,
                            {"residential_fee": fee, "recipient": ln["recipient"],
                             "marker": BUSINESS_MARKERS.search(ln["recipient"]).group(0)}, keys))
    return hits


def check_address_corrections(lines, terms: RateAgreement) -> list[Hit]:
    by_trk = defaultdict(list)
    for ln in lines:
        if ln["address_correction_fee"] > ZERO:
            by_trk[ln["tracking_number"]].append(ln)
    hits = []
    for trk, group in by_trk.items():
        if len(group) > 1:
            extra = money(sum(ln["address_correction_fee"] for ln in group[1:]))
            hits.append(Hit("repeated_address_correction", "verifiable", "low", group, extra,
                            {"tracking_number": trk, "times_billed": len(group),
                             "contract_fee": terms.address_correction_fee, "overcharge": extra},
                            {"tracking_numbers": [trk]}))
        for ln in group:
            if ln["address_correction_fee"] != terms.address_correction_fee:
                hits.append(Hit("accessorial_rate_mismatch", "verifiable", "low", [ln],
                                money(ln["address_correction_fee"] - terms.address_correction_fee),
                                {"billed_fee": ln["address_correction_fee"],
                                 "contract_fee": terms.address_correction_fee, "charge": "address correction"},
                                {"tracking_numbers": [trk]}))
    return hits


def check_unlisted(lines, terms: RateAgreement) -> list[Hit]:
    return [
        Hit("unlisted_accessorial", "judgment_required", "low", [ln], None,
            {"charge": ln["other_charge"], "description": ln.get("other_charge_desc") or "(no description)"},
            {"tracking_numbers": [ln["tracking_number"]]})
        for ln in lines if ln["other_charge"] > ZERO
    ]


ALL_CHECKS = [check_duplicates, check_line_totals, check_transport, check_fuel,
              check_residential, check_address_corrections, check_unlisted]


def run_all(lines, terms: RateAgreement) -> list[Hit]:
    hits: list[Hit] = []
    for check in ALL_CHECKS:
        hits.extend(check(lines, terms))
    return hits
