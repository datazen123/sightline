import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Tests never call a real model and never touch the real run DB."""
    monkeypatch.setenv("SIGHTLINE_PROVIDER", "mock")
    monkeypatch.setenv("SIGHTLINE_DB", str(tmp_path / "test.duckdb"))
    import sightline.core.store as store
    import sightline.ingest.mapping as mapping

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.duckdb")
    monkeypatch.setattr(mapping, "REJECTION_LOG", tmp_path / "rejected.jsonl")
    yield


@pytest.fixture(scope="session")
def terms():
    sys.path.insert(0, str(ROOT / "data"))
    from generate_parcel import build_terms

    t = build_terms()
    t.source_file = "rate_agreement.pdf"
    return t
