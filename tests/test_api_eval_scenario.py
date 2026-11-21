from decimal import Decimal as D
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from sightline.cli import gri_impact
from sightline.core import store
from sightline.core.engine import run_audit

DATA = Path(__file__).resolve().parent.parent / "data" / "parcel"


def test_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["provider"] == "mock"


def test_audit_upload_returns_cited_findings():
    files = [("files", (p.name, p.read_bytes())) for p in sorted(DATA.iterdir())]
    r = TestClient(app).post("/audit", data={"corpus": "parcel_invoices"}, files=files)
    assert r.status_code == 200
    fs = r.json()["findings"]
    assert len(fs) == 10 and all(f["citations"] for f in fs)


def test_audit_rejects_bad_type_and_corpus():
    c = TestClient(app)
    assert c.post("/audit", data={"corpus": "nope"}).status_code == 400
    r = c.post("/audit", data={"corpus": "parcel_invoices"}, files=[("files", ("x.exe", b"1"))])
    assert r.status_code == 415


def test_parcel_eval_full_recall():
    import json

    seeded = json.loads((DATA.parent.parent / "eval" / "seeded_issues_parcel.json").read_text())["issues"]
    result, plugin = run_audit("parcel_invoices", persist=False)
    for issue in seeded:
        assert any(f.rule == issue["rule"] and set(issue["keys"]) & plugin.match_key(f) for f in result.findings), issue["id"]


def test_store_views_run():
    run_audit("parcel_invoices")
    con = store.connect(store.DB_PATH)
    rows = con.execute("SELECT service, amount_usd FROM v_recoverable_by_service").fetchall()
    assert rows and all(r[1] > 0 for r in rows)
    assert con.execute("SELECT COUNT(*) FROM v_findings_by_rule").fetchone()[0] >= 10


def test_gri_scenario():
    zero = gri_impact(D("0"))
    assert all(r["delta_usd"] == 0 for r in zero)
    rows = gri_impact(D("5.9"))
    assert {r["service"] for r in rows} == {"GROUND", "2DAY", "NEXTDAY"}
    assert all(D("5.5") < r["delta_pct"] < D("6.3") for r in rows)
