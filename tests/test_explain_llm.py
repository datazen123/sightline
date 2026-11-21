import agents.llm as llm
from sightline.core.explain import allowed_numbers, numbers_ok
from sightline.core.schema import Citation, Finding


def finding():
    return Finding(id="P1", corpus="c", rule="r", title="t", severity="low", classification="verifiable",
                   amount_usd=22.43, facts={"billed_freight": "68.89", "discount_pct": "30.0"},
                   keys={"tracking_numbers": ["CP1"]}, citations=[Citation(file="a.csv", location="row 7")])


def test_number_guard_accepts_known_numbers():
    f = finding()
    assert numbers_ok("Billed $68.89 with a 30% discount missing; dispute $22.43 (row 7).", allowed_numbers(f)) == []


def test_number_guard_rejects_invented_numbers():
    f = finding()
    assert numbers_ok("You could recover about $250.00 a year.", allowed_numbers(f)) == ["$250.00"]


def test_routing_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_PROVIDER", "anthropic")
    assert llm.resolve_model("mapper") == ("anthropic", "claude-haiku-5-5")
    assert llm.resolve_model("explainer") == ("anthropic", "claude-opus-5-5")
    monkeypatch.setenv("SIGHTLINE_MODEL_LARGE", "gemini:gemini-2.5-pro")
    assert llm.resolve_model("judgment") == ("gemini", "gemini-2.5-pro")
    monkeypatch.setenv("SIGHTLINE_MODEL_MAPPER", "claude-sonnet-5-5")
    assert llm.resolve_model("mapper") == ("anthropic", "claude-sonnet-5-5")


def test_auto_provider_is_mock_without_keys(monkeypatch):
    for k in ("SIGHTLINE_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert llm.detect_provider() == "mock"


def test_ledger_costs():
    led = llm.reset_ledger()
    llm._record("mapper", "anthropic", "claude-haiku-5-5", 1_000_000, 1_000_000)
    assert led.total_cost == 0.60
    llm._record("x", "gemini", "unpriced-model", 10, 10)
    assert led.total_cost is None  # unknown price -> reported as n/a, never guessed


def test_strict_schema_closes_objects():
    s = llm.strict_schema({"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}})
    assert s["additionalProperties"] is False and s["properties"]["a"]["required"] == ["b"]
