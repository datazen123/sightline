"""Credits and adjustments: money already refunded must not be claimed again."""

from decimal import Decimal as D

from corpora.parcel_invoices.rules import check_duplicates, check_orphan_adjustments, credits_by_tracking


def line(trk, total, line_type="SHIP", inv="INV-1"):
    return {"tracking_number": trk, "line_type": line_type, "total": D(total), "_invoice_id": inv}


def test_credits_are_summed_per_tracking_number():
    lines = [line("T1", "10.00"), line("T1", "-4.00", "ADJ"), line("T1", "-1.00", "ADJ"), line("T2", "5.00")]
    assert credits_by_tracking(lines) == {"T1": D("5.00")}


def test_duplicate_without_credit_is_claimed_in_full():
    hits = check_duplicates([line("T1", "18.00", inv="A"), line("T1", "18.00", inv="B")], None)
    assert len(hits) == 1 and hits[0].amount == D("18.00") and hits[0].facts["already_credited"] == 0


def test_duplicate_already_refunded_is_not_claimed_again():
    lines = [line("T1", "18.00", inv="A"), line("T1", "18.00", inv="B"), line("T1", "-18.00", "ADJ", inv="C")]
    assert check_duplicates(lines, None) == []


def test_partial_credit_leaves_the_remainder_owed():
    lines = [line("T1", "18.00", inv="A"), line("T1", "18.00", inv="B"), line("T1", "-5.50", "ADJ", inv="C")]
    (hit,) = check_duplicates(lines, None)
    assert hit.amount == D("12.50") and hit.facts["already_credited"] == D("5.50")


def test_one_credit_is_never_applied_twice():
    # billed three times, one credit of 18.00: one duplicate is settled, the other is still owed
    lines = [line("T1", "18.00", inv="A"), line("T1", "18.00", inv="B"), line("T1", "18.00", inv="C"),
             line("T1", "-18.00", "ADJ", inv="D")]
    hits = check_duplicates(lines, None)
    assert [h.amount for h in hits] == [D("18.00")]


def test_adjustment_without_a_shipment_goes_to_a_person():
    lines = [line("T1", "10.00"), line("T9", "-7.25", "ADJ", inv="INV-2"), line("T8", "3.10", "ADJ")]
    hits = check_orphan_adjustments(lines, None)
    assert {h.keys["tracking_numbers"][0] for h in hits} == {"T9", "T8"}
    assert all(h.classification == "judgment_required" and h.amount is None for h in hits)
    assert {h.facts["kind"] for h in hits} == {"credit", "charge"}
