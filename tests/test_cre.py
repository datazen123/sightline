from decimal import Decimal as D

from corpora.cre_dealroom.plugin import _value_in
from sightline.core.engine import run_audit


def test_value_must_appear_in_snippet():
    assert _value_in(2.75, "Acquisition fee: 2.75% of purchase price")
    assert not _value_in(3.0, "Acquisition fee: 2.75% of purchase price")


def test_cre_rules_and_amounts():
    result, plugin = run_audit("cre_dealroom", persist=False)
    by_rule = {f.rule: f for f in result.findings}
    assert by_rule["fact_conflict"].amount_usd == 208500.0
    assert by_rule["exit_cap_below_market"].amount_usd == float(D(1520500) / D("0.05") - (D(1520500) / D("0.0575")).quantize(D(1)))
    assert by_rule["occupancy_gap_unbridged"].classification == "verifiable"
    assert plugin.stats["facts_verified"] == plugin.stats["facts_proposed"]


def test_unverifiable_fact_is_dropped(monkeypatch):
    import json

    import corpora.cre_dealroom.plugin as cre

    data = json.loads(cre.FIXTURE.read_text())
    data["extract_cre_facts"]["facts"].append(
        {"fact": "exit_cap_rate_pct", "value": 6.5, "doc_id": "pro_forma", "page": 1, "snippet": "Exit cap rate: 6.5%"})
    monkeypatch.setattr(cre, "FIXTURE", type("P", (), {"read_text": lambda self: json.dumps(data)})())
    result, plugin = run_audit("cre_dealroom", persist=False)
    assert any("snippet not found" in r["errors"][0] for r in plugin.rejected_mappings)
