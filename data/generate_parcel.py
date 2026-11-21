"""Generate the synthetic parcel-audit pack (corpus #2).

SYNTHETIC DATA. "Corvid Parcel" (carrier) and "Lumen Goods Co." (shipper)
are fictional. Every figure is generated from the seed below.

Outputs, under data/parcel/:
  rate_agreement.pdf        discounts by service/zone, residential fee,
                            fuel %, DIM divisor 139, zone chart, list rates
  inv_2026-09.csv           ~100 shipment lines, export-style CSV
  inv_2026-10.xlsx          ~100 lines + 1 adjustment, Summary + Detail sheets
  inv_2026-11.pdf           ~100 lines, printed-statement PDF
and eval/seeded_issues_parcel.json (ground truth for the planted errors).

Every line is priced exactly per the agreement EXCEPT the planted ones.

Run: uv run python data/generate_parcel.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from corpora.parcel_invoices.contract import RateAgreement, money  # noqa: E402

OUT = ROOT / "data" / "parcel"
SEEDED = ROOT / "eval" / "seeded_issues_parcel.json"
FOOTER = "SYNTHETIC DEMO DATA - fictional carrier and shipper, generated figures"

# ---------------------------------------------------------------------------
# Contract terms (the source of truth printed into rate_agreement.pdf)
# ---------------------------------------------------------------------------
ORIGIN_ZIP3 = "462"
FUEL_PCT = Decimal("8.50")
RESI_FEE = Decimal("4.85")
ADCORR_FEE = Decimal("18.00")
DIM_DIVISOR = 139
ZONE_CHART = [(100, 199, 5), (200, 299, 4), (300, 399, 5), (400, 479, 2), (480, 499, 3),
              (500, 599, 4), (600, 699, 3), (700, 799, 6), (800, 899, 7), (900, 999, 8)]
RATE_PARAMS = {  # service: (first-lb base, step per zone, addl-lb base, step per zone)
    "GROUND": ("9.10", "0.62", "0.48", "0.11"),
    "2DAY": ("18.40", "1.85", "1.20", "0.32"),
    "NEXTDAY": ("31.75", "3.10", "2.10", "0.55"),
}
DISCOUNT_BANDS = [("GROUND", 2, 4, "22.0"), ("GROUND", 5, 8, "18.0"), ("2DAY", 2, 8, "30.0"),
                  ("NEXTDAY", 2, 4, "35.0"), ("NEXTDAY", 5, 8, "32.0")]
SVC_LABEL = {"GROUND": "Ground", "2DAY": "2nd Day", "NEXTDAY": "Next Day"}


def build_terms() -> RateAgreement:
    list_rates = {}
    for svc, (b, s, ab, as_) in RATE_PARAMS.items():
        for z in range(2, 9):
            list_rates[(svc, z)] = (money(Decimal(b) + Decimal(s) * (z - 2)),
                                    money(Decimal(ab) + Decimal(as_) * (z - 2)))
    discounts = {(svc, z): Decimal(pct) for svc, lo, hi, pct in DISCOUNT_BANDS for z in range(lo, hi + 1)}
    return RateAgreement(ORIGIN_ZIP3, FUEL_PCT, RESI_FEE, ADCORR_FEE, DIM_DIVISOR, ZONE_CHART,
                         list_rates, discounts)


class Doc(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 6, FOOTER, align="C")


def write_agreement(terms: RateAgreement) -> None:
    pdf = Doc()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.multi_cell(0, 8, "Parcel Services Rate Agreement\nCorvid Parcel (carrier) and Lumen Goods Co. (shipper)",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, "Agreement No. RA-2026-0147. Term: 2026-01-01 through 2026-12-31. "
                         "Fictional parties - synthetic demo document.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Section 1. Pricing Terms", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    clauses = [
        f"1.1 Origin: all shipments tender from the shipper facility in ZIP3 {ORIGIN_ZIP3}.",
        "1.2 Net transportation charge = published list rate (Schedule A) less the discount in Schedule B.",
        f"1.3 Fuel surcharge: {FUEL_PCT}% of the net transportation charge, fixed for the term.",
        f"1.4 Residential delivery surcharge: ${RESI_FEE} per package delivered to a residential address.",
        f"1.5 Address correction fee: ${ADCORR_FEE} per package, assessed at most once per package.",
        f"1.6 Dimensional weight divisor: {DIM_DIVISOR}. Dimensional weight = L x W x H (inches) / {DIM_DIVISOR}.",
        "1.7 Billable weight is the greater of actual weight and dimensional weight, each rounded up to the next whole pound.",
        "1.8 Zones are determined by destination ZIP3 per Schedule C.",
        "1.9 Accessorial charges not listed in this Section are billed per the carrier's published service guide.",
        "1.10 Billing disputes must be raised within 90 days of the invoice date.",
    ]
    for c in clauses:
        pdf.multi_cell(0, 6, c, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Schedule B. Contract Discounts", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    rows = [["Service", "Zones", "Discount off list"]] + [
        [SVC_LABEL[s], f"{lo}-{hi}", f"{pct}%"] for s, lo, hi, pct in DISCOUNT_BANDS]
    with pdf.table(rows, col_widths=(40, 30, 40), width=110):
        pass
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Schedule C. Zone Chart (origin ZIP3 462)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    rows = [["Destination ZIP3", "Zone"]] + [[f"{lo:03d}-{hi:03d}", str(z)] for lo, hi, z in ZONE_CHART]
    with pdf.table(rows, col_widths=(50, 20), width=70):
        pass

    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Schedule A. Published List Rates (USD per package)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    rows = [["Service", "Zone", "First lb", "Each addl lb"]]
    for (svc, z), (first, addl) in terms.list_rates.items():
        rows.append([SVC_LABEL[svc], str(z), f"${first}", f"${addl}"])
    with pdf.table(rows, col_widths=(35, 20, 30, 35), width=120):
        pass
    pdf.output(str(OUT / "rate_agreement.pdf"))


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------
def price(terms, line, fuel_pct=FUEL_PCT, zone=None, weight=None, discount=True):
    zone = zone or terms.zone_for(line["dest_zip"])
    weight = weight or terms.billable_weight(line["actual_weight"], line["l"], line["w"], line["h"])
    freight = (terms.net_transport(line["service"], zone, weight) if discount
               else terms.list_rate(line["service"], zone, weight))
    line.update(zone=zone, billed_weight=weight, freight=freight, fuel=money(freight * fuel_pct / 100))
    totalize(line)


def totalize(line, extra=Decimal(0)):
    line["total"] = money(line["freight"] + line["fuel"] + line["resi"] + line["adcorr"] + line["other"] + extra)


def make_line(rng, terms, month, i):
    svc = rng.choices(["GROUND", "2DAY", "NEXTDAY"], [70, 20, 10])[0]
    lo, hi, _ = rng.choice(ZONE_CHART)
    dest = f"{rng.randint(lo, hi):03d}{rng.randint(1, 99):02d}"
    res = rng.random() < 0.45
    line = {
        "tracking": f"CP{month:02d}{i:04d}{rng.randint(100, 999)}",
        "ship_date": f"2026-{month:02d}-{rng.randint(1, 28):02d}",
        "service": svc, "origin": f"{ORIGIN_ZIP3}{rng.randint(1, 99):02d}", "dest_zip": dest,
        "addr": "RES" if res else "COM",
        "l": Decimal(rng.randint(6, 24)), "w": Decimal(rng.randint(4, 18)), "h": Decimal(rng.randint(2, 14)),
        "actual_weight": Decimal(rng.randint(5, 400)) / 10,
        "resi": RESI_FEE if res else Decimal("0.00"), "adcorr": Decimal("0.00"),
        "other": Decimal("0.00"), "other_desc": "", "line_type": "SHIP",
        "recipient": (f"Private Residence #{rng.randint(1000, 9999)}" if res else
                      f"{rng.choice(['Retail Store', 'Warehouse', 'Clinic', 'Office'])} #{rng.randint(10, 999)}"),
    }
    if rng.random() < 0.03:  # legitimate one-time address corrections (negative controls)
        line["adcorr"] = ADCORR_FEE
    price(terms, line)
    return line


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261120)
    terms = build_terms()
    write_agreement(terms)
    sep = [make_line(rng, terms, 9, i) for i in range(1, 101)]
    oct_ = [make_line(rng, terms, 10, i) for i in range(1, 101)]
    nov = [make_line(rng, terms, 11, i) for i in range(1, 100)]
    seeded = []

    def pick(lines, cond, used=set()):  # noqa: B006 - deliberate shared "used" set
        for ln in lines:
            if ln["tracking"] not in used and ln["adcorr"] == 0 and cond(ln):
                used.add(ln["tracking"])
                return ln
        raise RuntimeError("no candidate")

    def seed(id_, rule, cls, keys, desc, amount=None, file=None):
        seeded.append({"id": id_, "rule": rule, "classification": cls, "keys": keys,
                       "expected_amount_usd": None if amount is None else float(amount),
                       "file": file, "description": desc})

    # --- September CSV ---------------------------------------------------
    ln = pick(sep, lambda x: x["addr"] == "COM")
    ln["resi"] = RESI_FEE
    totalize(ln)
    seed("resi_on_commercial", "residential_fee_on_commercial", "verifiable", [ln["tracking"]],
         "Residential surcharge billed on a line the invoice itself marks commercial.", RESI_FEE, "inv_2026-09.csv")

    adcorr_line = pick(sep, lambda x: True)
    adcorr_line["adcorr"] = ADCORR_FEE
    totalize(adcorr_line)

    ln = pick(sep, lambda x: x["addr"] == "RES")
    ln["recipient"] = "Design Studio LLC Ste 210"
    seed("resi_business_name", "residential_fee_business_name", "judgment_required", [ln["tracking"]],
         "Residential surcharge on an address the carrier classed residential, but the consignee "
         "looks like a business (LLC, suite). Could be a home business; needs a human.", None, "inv_2026-09.csv")

    ln = pick(sep, lambda x: True)
    totalize(ln, extra=Decimal("10.00"))
    seed("line_total_math", "line_total_mismatch", "verifiable", [ln["tracking"]],
         "Line total is $10.00 more than the sum of its own charge columns.", Decimal("10.00"), "inv_2026-09.csv")

    dup_src = pick(sep, lambda x: True)

    # --- October XLSX ----------------------------------------------------
    ln = pick(oct_, lambda x: x["service"] == "GROUND")
    ln.update(l=Decimal(12), w=Decimal(10), h=Decimal(8), actual_weight=Decimal("6.0"))
    price(terms, ln)  # correct billable = 7 lb
    correct = ln["freight"] + ln["fuel"]
    price(terms, ln, weight=15)
    seed("billed_weight_over_dim", "billed_weight_exceeds_billable", "verifiable", [ln["tracking"]],
         "Billed at 15 lb; actual 6.0 lb and DIM weight 7 lb (12x10x8/139), so billable is 7 lb.",
         ln["freight"] + ln["fuel"] - correct, "inv_2026-10.xlsx")

    ln = pick(oct_, lambda x: x["service"] == "2DAY")
    correct = ln["freight"] + ln["fuel"]
    price(terms, ln, discount=False)
    seed("missed_discount", "missed_discount", "verifiable", [ln["tracking"]],
         "Freight billed at full list rate; the 30% 2-Day contract discount was not applied.",
         ln["freight"] + ln["fuel"] - correct, "inv_2026-10.xlsx")

    ln = pick(oct_, lambda x: x["service"] == "GROUND")
    ln["dest_zip"] = "30318"
    price(terms, ln)
    correct = ln["freight"] + ln["fuel"]
    price(terms, ln, zone=7)
    seed("wrong_zone", "wrong_zone", "verifiable", [ln["tracking"]],
         "Destination ZIP3 303 is zone 5 per Schedule C, billed and priced as zone 7.",
         ln["freight"] + ln["fuel"] - correct, "inv_2026-10.xlsx")

    ln = pick(oct_, lambda x: x["service"] == "GROUND")
    ln.update(other=Decimal("31.50"), other_desc="LARGE PACKAGE SURCHARGE")
    totalize(ln)
    seed("unlisted_accessorial", "unlisted_accessorial", "judgment_required", [ln["tracking"]],
         "A $31.50 large-package surcharge is not priced in the agreement; clause 1.9 defers unlisted "
         "accessorials to the carrier's service guide. Whether it applies needs a human.", None, "inv_2026-10.xlsx")

    adj = dict(adcorr_line)
    adj.update(line_type="ADJ", freight=Decimal("0.00"), fuel=Decimal("0.00"), resi=Decimal("0.00"),
               other=Decimal("0.00"), adcorr=ADCORR_FEE, ship_date=adcorr_line["ship_date"])
    totalize(adj)
    oct_.append(adj)
    seed("repeat_address_correction", "repeated_address_correction", "verifiable", [adcorr_line["tracking"]],
         "Address correction billed on the September line and again as an October adjustment; "
         "the agreement allows it at most once per package.", ADCORR_FEE, "inv_2026-10.xlsx")

    # --- November PDF ----------------------------------------------------
    nov_fuel = Decimal("9.25")
    dup = dict(dup_src)
    nov.insert(37, dup)
    for ln in nov:
        ln["fuel"] = money(ln["freight"] * nov_fuel / 100)
        totalize(ln)
    seed("duplicate_tracking", "duplicate_tracking", "verifiable", [dup["tracking"]],
         "Tracking number billed on the September invoice and again on the November invoice.",
         dup["total"], "inv_2026-11.pdf")
    fuel_delta = sum(ln["fuel"] - money(ln["freight"] * FUEL_PCT / 100) for ln in nov)
    seed("fuel_pct_mismatch", "fuel_rate_mismatch", "verifiable", ["INV-261130"],
         "Every November line applies a 9.25% fuel surcharge; the agreement fixes fuel at 8.50%.",
         fuel_delta, "inv_2026-11.pdf")

    write_csv(sep)
    write_xlsx(oct_)
    write_pdf_invoice(nov)
    SEEDED.write_text(json.dumps({
        "corpus": "parcel_invoices",
        "note": "Synthetic. Generated by data/generate_parcel.py; do not edit by hand.",
        "issues": seeded,
    }, indent=2) + "\n")
    print(f"Wrote {len(sep) + len(oct_) + len(nov)} invoice lines and {len(seeded)} seeded issues to {OUT}")


def _total(lines):
    return money(sum(ln["total"] for ln in lines))


def write_csv(lines):
    path = OUT / "inv_2026-09.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# Corvid Parcel - invoice detail export (synthetic)"])
        w.writerow(["# Invoice Number: INV-260930"])
        w.writerow(["# Invoice Date: 2026-09-30"])
        w.writerow([f"# Line Count: {len(lines)}"])
        w.writerow([f"# Invoice Total: ${_total(lines):,}"])
        w.writerow(["Tracking #", "Ship Date", "Svc", "Orig ZIP", "Dest ZIP", "Res/Com", "L (in)", "W (in)",
                    "H (in)", "Act Wt", "Bill Wt", "Zone", "Freight", "Fuel Surch", "Resi Surch", "Addr Corr",
                    "Misc Chg", "Misc Desc", "Line Total", "Recipient"])
        code = {"GROUND": "GND", "2DAY": "2DA", "NEXTDAY": "NDA"}
        for ln in lines:
            w.writerow([ln["tracking"], ln["ship_date"], code[ln["service"]], ln["origin"], ln["dest_zip"],
                        ln["addr"][0], ln["l"], ln["w"], ln["h"], ln["actual_weight"], ln["billed_weight"],
                        ln["zone"], ln["freight"], ln["fuel"], ln["resi"], ln["adcorr"], ln["other"],
                        ln["other_desc"], ln["total"], ln["recipient"]])


def write_xlsx(lines):
    wb = Workbook()
    s = wb.active
    s.title = "Summary"
    for row in [["Carrier", "Corvid Parcel (fictional)"], ["Invoice Number", "INV-261031"],
                ["Invoice Date", "2026-10-31"], ["Shipment Lines", len(lines)],
                ["Amount Due", f"${_total(lines):,}"]]:
        s.append(row)
    d = wb.create_sheet("Detail")
    d.append(["TrackingNumber", "LineType", "ShipDate", "ServiceLevel", "OriginPostal", "DestinationPostal",
              "DeliveryType", "Length", "Width", "Height", "ActualWeightLb", "BilledWeightLb", "BillZone",
              "TransportationCharge", "FuelSurcharge", "ResidentialSurcharge", "AddressCorrection",
              "OtherCharge", "OtherChargeDescription", "NetAmount", "ConsigneeName"])
    for ln in lines:
        d.append([ln["tracking"], ln["line_type"], ln["ship_date"], SVC_LABEL[ln["service"]], ln["origin"],
                  ln["dest_zip"], "Residential" if ln["addr"] == "RES" else "Commercial", int(ln["l"]),
                  int(ln["w"]), int(ln["h"]), float(ln["actual_weight"]), int(ln["billed_weight"]),
                  int(ln["zone"]), float(ln["freight"]), float(ln["fuel"]), float(ln["resi"]),
                  float(ln["adcorr"]), float(ln["other"]), ln["other_desc"], float(ln["total"]),
                  ln["recipient"]])
    wb.save(OUT / "inv_2026-10.xlsx")


def write_pdf_invoice(lines):
    pdf = Doc(orientation="L")
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, "Corvid Parcel - Shipping Statement (synthetic)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for t in ["Bill to: Lumen Goods Co. (fictional)", "Invoice Number: INV-261130", "Invoice Date: 2026-11-30",
              f"Line Count: {len(lines)}", f"Invoice Total: ${_total(lines):,}"]:
        pdf.cell(0, 5, t, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", size=6.5)
    head = ["Tracking", "Date", "Service", "Dest", "Type", "L", "W", "H", "ActWt", "BillWt", "Zn",
            "Freight", "Fuel", "Resi", "AddrCorr", "Other", "Total"]
    rows = [head] + [[ln["tracking"], ln["ship_date"], ln["service"], ln["dest_zip"], ln["addr"],
                      str(ln["l"]), str(ln["w"]), str(ln["h"]), str(ln["actual_weight"]),
                      str(ln["billed_weight"]), str(ln["zone"]), str(ln["freight"]), str(ln["fuel"]),
                      str(ln["resi"]), str(ln["adcorr"]), str(ln["other"]), str(ln["total"])] for ln in lines]
    widths = (26, 18, 16, 12, 10, 8, 8, 8, 12, 12, 8, 16, 14, 12, 14, 12, 16)
    with pdf.table(rows, col_widths=widths, width=sum(widths), repeat_headings=1, line_height=4):
        pass
    pdf.output(str(OUT / "inv_2026-11.pdf"))


if __name__ == "__main__":
    main()
