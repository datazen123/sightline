from decimal import Decimal as D

from corpora.parcel_invoices import rules
from corpora.parcel_invoices.contract import money


def line(terms, **kw):
    ln = {"tracking_number": "T1", "line_type": "SHIP", "service": "GROUND", "dest_zip": "46201",
          "address_type": "COM", "length": D(6), "width": D(4), "height": D(2), "actual_weight": D("3.0"),
          "residential_fee": D("0.00"), "address_correction_fee": D("0.00"), "other_charge": D("0.00"),
          "other_charge_desc": "", "recipient": "Warehouse #1", "_file": "inv.csv", "_location": "row 1",
          "_invoice_id": "INV-1"}
    ln.update(kw)
    zone = kw.get("zone", terms.zone_for(ln["dest_zip"]))
    wt = kw.get("billed_weight", terms.billable_weight(ln["actual_weight"], ln["length"], ln["width"], ln["height"]))
    ln.setdefault("zone", zone)
    ln.setdefault("billed_weight", D(wt))
    ln.setdefault("freight", terms.net_transport(ln["service"], int(zone), int(wt)))
    ln.setdefault("fuel", terms.fuel(ln["freight"]))
    ln.setdefault("total", money(ln["freight"] + ln["fuel"] + ln["residential_fee"]
                                 + ln["address_correction_fee"] + ln["other_charge"]))
    return ln


def rules_hit(hits):
    return [h.rule for h in hits]


def test_clean_line_has_no_findings(terms):
    assert rules.run_all([line(terms)], terms) == []


def test_duplicate_tracking(terms):
    a, b = line(terms), line(terms, _invoice_id="INV-2")
    hits = rules.check_duplicates([a, b], terms)
    assert rules_hit(hits) == ["duplicate_tracking"] and hits[0].amount == b["total"]


def test_adjustment_rows_are_not_duplicates(terms):
    a = line(terms)
    adj = line(terms, line_type="ADJ")
    assert rules.check_duplicates([a, adj], terms) == []


def test_line_total_mismatch(terms):
    ln = line(terms)
    ln["total"] += D("10.00")
    hits = rules.check_line_totals([ln], terms)
    assert hits[0].amount == D("10.00")


def test_wrong_zone(terms):
    ln = line(terms, dest_zip="30318", zone=7, freight=terms.net_transport("GROUND", 7, 3))
    ln["fuel"] = terms.fuel(ln["freight"])
    hits = rules.check_transport([ln], terms)
    assert rules_hit(hits) == ["wrong_zone"]
    correct = terms.net_transport("GROUND", 5, 3)
    assert hits[0].amount == money(ln["freight"] - correct + terms.fuel(ln["freight"]) - terms.fuel(correct))


def test_billed_weight_above_dim(terms):
    ln = line(terms, length=D(12), width=D(10), height=D(8), actual_weight=D("6.0"), billed_weight=D(15),
              freight=terms.net_transport("GROUND", 2, 15))
    hits = rules.check_transport([ln], terms)
    assert rules_hit(hits) == ["billed_weight_exceeds_billable"]
    assert hits[0].facts["billable_weight"] == 7


def test_missed_discount(terms):
    ln = line(terms, service="2DAY", freight=terms.list_rate("2DAY", 2, 3))
    assert rules_hit(rules.check_transport([ln], terms)) == ["missed_discount"]


def test_underbilling_is_not_flagged(terms):
    ln = line(terms, freight=D("1.00"))
    assert rules.check_transport([ln], terms) == []


def test_fuel_mismatch_aggregates_per_invoice(terms):
    lines = [line(terms, tracking_number=f"T{i}") for i in range(3)]
    for ln in lines:
        ln["fuel"] = money(ln["freight"] * D("9.25") / 100)
    hits = rules.check_fuel(lines, terms)
    assert len(hits) == 1 and hits[0].facts["lines_affected"] == 3
    assert hits[0].amount == money(sum(ln["fuel"] - terms.fuel(ln["freight"]) for ln in lines))


def test_residential_fee_on_commercial(terms):
    ln = line(terms, residential_fee=terms.residential_fee)
    assert rules_hit(rules.check_residential([ln], terms)) == ["residential_fee_on_commercial"]


def test_residential_fee_business_name_is_judgment(terms):
    ln = line(terms, address_type="RES", residential_fee=terms.residential_fee, recipient="Acme Design LLC Ste 2")
    hits = rules.check_residential([ln], terms)
    assert rules_hit(hits) == ["residential_fee_business_name"]
    assert hits[0].classification == "judgment_required" and hits[0].amount is None


def test_residential_fee_on_home_is_fine(terms):
    ln = line(terms, address_type="RES", residential_fee=terms.residential_fee, recipient="Private Residence #1")
    assert rules.check_residential([ln], terms) == []


def test_residential_fee_wrong_rate(terms):
    ln = line(terms, address_type="RES", residential_fee=D("6.00"), recipient="Private Residence #1")
    assert rules_hit(rules.check_residential([ln], terms)) == ["accessorial_rate_mismatch"]


def test_repeated_address_correction(terms):
    a = line(terms, address_correction_fee=terms.address_correction_fee)
    b = line(terms, line_type="ADJ", address_correction_fee=terms.address_correction_fee)
    hits = rules.check_address_corrections([a, b], terms)
    assert rules_hit(hits) == ["repeated_address_correction"] and hits[0].amount == D("18.00")


def test_single_address_correction_is_fine(terms):
    assert rules.check_address_corrections([line(terms, address_correction_fee=D("18.00"))], terms) == []


def test_unlisted_accessorial_is_judgment(terms):
    hits = rules.check_unlisted([line(terms, other_charge=D("31.50"), other_charge_desc="LARGE PKG")], terms)
    assert hits[0].classification == "judgment_required"
