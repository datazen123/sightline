"""Corpus plugin registry.

A corpus is a folder under ``corpora/<name>/`` with a ``corpus.toml``:

    name = "parcel_invoices"
    title = "Carrier invoices vs rate agreement"
    plugin = "corpora.parcel_invoices.plugin:ParcelInvoiceAudit"
    data_dir = "data/parcel"                 # default sample data, relative to repo root
    seeded_issues = "eval/seeded_issues_parcel.json"
    accepts = [".csv", ".xlsx", ".pdf"]

The plugin class subclasses ``CorpusPlugin`` and implements ``audit``.
Adding a third domain = a new folder with corpus.toml + plugin.py + data.
"""

from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sightline.core.schema import Finding

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPORA_DIR = REPO_ROOT / "corpora"


@dataclass
class CorpusConfig:
    name: str
    title: str
    plugin: str
    data_dir: Path
    seeded_issues: Path | None
    accepts: list[str]
    raw: dict[str, Any] = field(default_factory=dict)


class CorpusPlugin:
    """Base class. ``audit`` returns findings with amounts already computed by
    code; the engine then asks the explainer to add prose."""

    def __init__(self, config: CorpusConfig) -> None:
        self.config = config
        self.stats: dict[str, Any] = {}
        self.rejected_mappings: list[dict[str, Any]] = []
        self.tables: dict[str, list[dict[str, Any]]] = {}  # rows to persist, by table name

    def audit(self, files: list[Path]) -> list[Finding]:  # pragma: no cover - interface
        raise NotImplementedError

    def match_key(self, finding: Finding) -> set[str]:
        """Identifiers the eval uses to match a finding to a seeded issue."""
        return {str(v) for v in finding.keys.values() if not isinstance(v, list)} | {
            str(x) for v in finding.keys.values() if isinstance(v, list) for x in v
        }


def load_config(path: Path) -> CorpusConfig:
    raw = tomllib.loads(path.read_text())
    return CorpusConfig(
        name=raw["name"],
        title=raw.get("title", raw["name"]),
        plugin=raw["plugin"],
        data_dir=REPO_ROOT / raw.get("data_dir", f"data/{raw['name']}"),
        seeded_issues=(REPO_ROOT / raw["seeded_issues"]) if raw.get("seeded_issues") else None,
        accepts=raw.get("accepts", [".pdf"]),
        raw=raw,
    )


def discover() -> dict[str, CorpusConfig]:
    out = {}
    for toml_path in sorted(CORPORA_DIR.glob("*/corpus.toml")):
        cfg = load_config(toml_path)
        out[cfg.name] = cfg
    return out


def get_plugin(name: str) -> CorpusPlugin:
    corpora = discover()
    if name not in corpora:
        raise KeyError(f"Unknown corpus '{name}'. Available: {', '.join(corpora)}")
    cfg = corpora[name]
    module_name, cls_name = cfg.plugin.split(":")
    cls = getattr(importlib.import_module(module_name), cls_name)
    return cls(cfg)
