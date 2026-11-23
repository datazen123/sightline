import json
from decimal import Decimal as D
from pathlib import Path

import pytest

import sightline.ingest.mapping as m
from corpora.parcel_invoices.plugin import INVOICE_SCHEMA
from sightline.ingest.tables import RawRow, RawTable, read_any

DATA = Path(__file__).resolve().parent.parent / "data" / "parcel"


@pytest.mark.parametrize("name,rows", [("inv_2026-09.csv", 100), ("inv_2026-10.xlsx", 101), ("inv_2026-11.pdf", 100)])
def test_heuristic_maps_every_format(name, rows):
    t = read_any(DATA / name)
    res = m.validate(t, INVOICE_SCHEMA, m.propose_heuristic(t, INVOICE_SCHEMA))
    assert res.ok, res.errors
    assert len(res.rows) == rows
    assert all(r["service"] in {"GROUND", "2DAY", "NEXTDAY"} for r in res.rows)


def tiny(total="5.00", count=1, header=("Tracking", "Total"), vals=("A1", "5.00")):
    return RawTable("t.csv", list(header), [RawRow("row 2", list(vals))],
                    f"Line Count: {count}\nInvoice Total: ${total}")


SCHEMA = m.CanonicalSchema("tiny", [m.FieldSpec("tracking_number", "str", synonyms=["tracking"]),
                                    m.FieldSpec("total", "decimal")], total_field="total")


def mapping(cols=None, totals=None):
    return m.Mapping(cols or {"tracking_number": "Tracking", "total": "Total"}, {},
                     totals or m.extract_control_totals(tiny().context_text), "test")


def test_valid_tiny_table():
    res = m.validate(tiny(), SCHEMA, mapping())
    assert res.ok and res.rows[0]["total"] == D("5.00")


def test_rejects_unmapped_required_field():
    res = m.validate(tiny(), SCHEMA, mapping({"tracking_number": None, "total": "Total"}))
    assert not res.ok and "not mapped" in res.errors[0]


def test_rejects_nonexistent_column():
    res = m.validate(tiny(), SCHEMA, mapping({"tracking_number": "Pkg", "total": "Total"}))
    assert any("non-existent" in e for e in res.errors)


def test_rejects_column_used_twice():
    res = m.validate(tiny(), SCHEMA, mapping({"tracking_number": "Total", "total": "Total"}))
    assert any("more than one" in e for e in res.errors)


def test_rejects_bad_type():
    t = tiny(vals=("A1", "five"))
    assert not m.validate(t, SCHEMA, mapping()).ok


def test_rejects_unmapped_enum_value():
    schema = m.CanonicalSchema("e", [m.FieldSpec("svc", "enum", enum=["GROUND"]), m.FieldSpec("total", "decimal")],
                               total_field="total")
    t = RawTable("t.csv", ["Svc", "Total"], [RawRow("row 2", ["XYZ", "5.00"])], tiny().context_text)
    res = m.validate(t, schema, m.Mapping({"svc": "Svc", "total": "Total"}, {}, mapping().control_totals, "t"))
    assert any("unmapped enum" in e for e in res.errors)


def test_rejects_row_count_mismatch():
    t = tiny(count=2)
    res = m.validate(t, SCHEMA, mapping(totals=m.extract_control_totals(t.context_text)))
    assert any("row count" in e for e in res.errors)


def test_rejects_total_mismatch():
    t = tiny(total="6.00")
    res = m.validate(t, SCHEMA, mapping(totals=m.extract_control_totals(t.context_text)))
    assert any("stated total" in e for e in res.errors)


def test_rejects_missing_control_totals():
    t = RawTable("t.csv", ["Tracking", "Total"], [RawRow("row 2", ["A1", "5.00"])], "")
    res = m.validate(t, SCHEMA, mapping(totals={"line_count": None, "total_amount": None}))
    assert any("no stated line count" in e for e in res.errors)


def test_rejects_control_total_not_in_document():
    # e.g. a model "reading" a total that is not actually in the text
    res = m.validate(tiny(), SCHEMA, mapping(totals={"line_count": 1, "total_amount": "5.00", "invoice_id": "INV-999"}))
    assert any("does not appear" in e for e in res.errors)


def test_rejected_mapping_is_logged(tmp_path):
    t = tiny(total="6.00")
    log = tmp_path / "rej.jsonl"
    m.log_rejection(t, mapping(), ["bad"], log)
    assert json.loads(log.read_text())["errors"] == ["bad"]


def test_ingest_raises_when_nothing_validates():
    t = RawTable("t.csv", ["Pkg", "Amt"], [RawRow("row 2", ["A1", "5.00"])], tiny().context_text)
    rej: list = []
    with pytest.raises(m.MappingRejected):
        m.ingest_table(t, SCHEMA, rej)
    assert rej and rej[0]["file"] == "t.csv"


# --- credits and adjustments -------------------------------------------------
@pytest.mark.parametrize("raw,want", [
    ("12.50", "12.50"), ("-12.50", "-12.50"), ("($12.50)", "-12.50"), ("12.50-", "-12.50"),
    ("12.50 CR", "-12.50"), ("12.50cr", "-12.50"), ("-$12.50", "-12.50"), ("$-12.50", "-12.50"),
    ("−12.50", "-12.50"), ("$1,234.56", "1234.56"), ("(1,234.56)", "-1234.56"),
])
def test_parse_money_reads_credit_formats(raw, want):
    assert m.parse_money(raw) == D(want)


@pytest.mark.parametrize("raw", ["twelve", "12.5.0", "NaN", "--", "()"])
def test_parse_money_rejects_non_numbers(raw):
    with pytest.raises(ValueError):
        m.parse_money(raw)


def credit_table(rows, stated):
    return RawTable("t.csv", ["Tracking", "Total"], [RawRow(f"row {i + 2}", list(r)) for i, r in enumerate(rows)],
                    f"Line Count: {len(rows)}\nInvoice Total: ${stated}")


def test_credit_lines_count_toward_the_reconciled_total():
    # 40.00 of charges, a 12.50 credit written two different ways: net 15.00
    t = credit_table([("A1", "20.00"), ("A2", "20.00"), ("A3", "(12.50)"), ("A4", "12.50 CR")], "15.00")
    res = m.validate(t, SCHEMA, m.Mapping({"tracking_number": "Tracking", "total": "Total"}, {},
                                          m.extract_control_totals(t.context_text), "test"))
    assert res.ok, res.errors
    assert sum(r["total"] for r in res.rows) == D("15.00")


def test_dropping_credit_lines_fails_reconciliation():
    # A reader that treats credits as "not costs" and skips them computes 40.00
    # against a stated 15.00. The check must refuse that, not accept it.
    full = credit_table([("A1", "20.00"), ("A2", "20.00"), ("A3", "-12.50"), ("A4", "-12.50")], "15.00")
    charges_only = RawTable(full.source_file, full.header, [r for r in full.rows if "-" not in r.values[1]],
                            "Line Count: 4\nInvoice Total: $15.00")
    res = m.validate(charges_only, SCHEMA, m.Mapping({"tracking_number": "Tracking", "total": "Total"}, {},
                                                     m.extract_control_totals(charges_only.context_text), "test"))
    assert not res.ok
    assert any("row count" in e for e in res.errors) and any("stated total" in e for e in res.errors)
