from decimal import Decimal as D
from pathlib import Path

from corpora.parcel_invoices.contract import TermCitation, money, parse_rate_agreement, verify_terms

AGREEMENT = Path(__file__).resolve().parent.parent / "data" / "parcel" / "rate_agreement.pdf"


def test_money_rounds_half_up():
    assert money("1.005") == D("1.01")
    assert money("1.004") == D("1.00")


def test_zone_chart_lookup(terms):
    assert terms.zone_for("30318") == 5
    assert terms.zone_for("46201") == 2
    assert terms.zone_for("99901") == 8


def test_dim_and_billable_weight(terms):
    # 12x10x8 = 960 / 139 = 6.9 -> 7
    assert terms.dim_weight(D(12), D(10), D(8)) == 7
    assert terms.billable_weight(D("6.0"), D(12), D(10), D(8)) == 7
    # actual heavier than DIM: actual wins, rounded up
    assert terms.billable_weight(D("20.1"), D(6), D(4), D(2)) == 21


def test_list_rate_and_discount(terms):
    # GROUND zone 2: first lb 9.10, addl 0.48 -> 3 lb = 9.10 + 2*0.48
    assert terms.list_rate("GROUND", 2, 3) == D("10.06")
    assert terms.net_transport("GROUND", 2, 3) == money(D("10.06") * D("0.78"))
    # 2DAY zone 3 has a 30% discount
    assert terms.discount_pct("2DAY", 3) == D("30.0")


def test_fuel_is_percent_of_net_freight(terms):
    assert terms.fuel(D("17.61")) == D("1.50")


def test_gri_raises_list_before_discount(terms):
    base = terms.net_transport("GROUND", 5, 10)
    after = terms.net_transport("GROUND", 5, 10, gri_pct=D("5.9"))
    assert after > base
    assert terms.net_transport("GROUND", 5, 10, gri_pct=D("0")) == base


def test_parse_and_verify_generated_agreement():
    terms, pages = parse_rate_agreement(AGREEMENT)
    assert terms.dim_divisor == 139
    assert terms.fuel_pct == D("8.50")
    assert len(terms.list_rates) == 21 and len(terms.discounts) == 21
    assert verify_terms(terms, pages) == []


def test_verify_rejects_unsupported_citation():
    terms, pages = parse_rate_agreement(AGREEMENT)
    terms.citations["fuel_pct"] = TermCitation(1, "1.3 Fuel surcharge: 6.00% of net")
    errs = verify_terms(terms, pages)
    assert any("fuel_pct" in e for e in errs)


def test_verify_rejects_missing_rate():
    terms, pages = parse_rate_agreement(AGREEMENT)
    del terms.list_rates[("NEXTDAY", 8)]
    assert any("NEXTDAY zone 8" in e for e in verify_terms(terms, pages))
