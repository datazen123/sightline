"""Result storage: DuckDB locally, BigQuery in production.

Tables are plain columns (no DuckDB-only types) and every view below is
written in the SQL subset DuckDB and BigQuery Standard SQL share: SELECT,
JOIN, GROUP BY, COUNT/SUM/ROUND, CAST(... AS FLOAT64-compatible), COALESCE.
To move to BigQuery: create the same tables in a dataset, load rows from
``runs/<run_id>/*.jsonl`` (or stream them), and run ``VIEWS`` with the
dataset prefix. See docs/RUNBOOK.md "Switching to BigQuery".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sightline.core.plugins import REPO_ROOT
from sightline.core.schema import AuditResult

DB_PATH = Path(os.environ.get("SIGHTLINE_DB", REPO_ROOT / "runs" / "sightline.duckdb"))


def _db(path: Path | None) -> Path:
    return path or DB_PATH

TABLES = {
    "runs": "run_id VARCHAR, corpus VARCHAR, created_at VARCHAR, findings INTEGER, "
            "recoverable_usd DOUBLE, llm_cost_usd DOUBLE, stats_json VARCHAR",
    "findings": "run_id VARCHAR, finding_id VARCHAR, corpus VARCHAR, rule VARCHAR, title VARCHAR, "
                "severity VARCHAR, classification VARCHAR, amount_usd DOUBLE, explanation VARCHAR, "
                "dispute_note VARCHAR, explained_by VARCHAR, facts_json VARCHAR, keys_json VARCHAR",
    "citations": "run_id VARCHAR, finding_id VARCHAR, file VARCHAR, location VARCHAR, snippet VARCHAR",
    "invoice_lines": "run_id VARCHAR, file VARCHAR, location VARCHAR, invoice_id VARCHAR, "
                     "tracking_number VARCHAR, line_type VARCHAR, service VARCHAR, zone INTEGER, "
                     "freight DOUBLE, fuel DOUBLE, total DOUBLE",
    "rejected_mappings": "run_id VARCHAR, file VARCHAR, proposed_by VARCHAR, errors_json VARCHAR",
    "llm_calls": "run_id VARCHAR, agent VARCHAR, provider VARCHAR, model VARCHAR, calls INTEGER, "
                 "tokens_in INTEGER, tokens_out INTEGER, cost_usd DOUBLE",
}

# Portable SQL: runs unchanged on DuckDB and BigQuery (prefix tables with
# `project.dataset.` on BigQuery).
VIEWS = {
    "v_findings_by_rule": """
        SELECT corpus, rule, classification, COUNT(*) AS findings,
               ROUND(COALESCE(SUM(amount_usd), 0), 2) AS amount_usd
        FROM findings GROUP BY corpus, rule, classification""",
    "v_recoverable_by_service": """
        SELECT l.run_id, l.service, COUNT(DISTINCT f.finding_id) AS findings,
               ROUND(SUM(f.amount_usd), 2) AS amount_usd
        FROM findings f
        JOIN citations c ON c.run_id = f.run_id AND c.finding_id = f.finding_id
        JOIN invoice_lines l ON l.run_id = c.run_id AND l.file = c.file AND l.location = c.location
        WHERE f.classification = 'verifiable'
        GROUP BY l.run_id, l.service""",
    "v_run_cost": """
        SELECT run_id, SUM(calls) AS calls, SUM(tokens_in) AS tokens_in,
               SUM(tokens_out) AS tokens_out, ROUND(SUM(cost_usd), 6) AS cost_usd
        FROM llm_calls GROUP BY run_id""",
}


def connect(path: Path | None = None):
    import duckdb

    path = _db(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    for name, cols in TABLES.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
    for name, sql in VIEWS.items():
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
    return con


def save(result: AuditResult, created_at: str, invoice_lines: list[dict] | None = None, path: Path | None = None):
    con = connect(path)
    rid = result.run_id
    con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                [rid, result.corpus, created_at, len(result.findings), result.stats.get("recoverable_usd"),
                 result.llm_cost_usd, json.dumps(result.stats, default=str)])
    for f in result.findings:
        con.execute("INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [rid, f.id, f.corpus, f.rule, f.title, f.severity, f.classification, f.amount_usd,
                     f.explanation, f.dispute_note, f.explained_by, json.dumps(f.facts, default=str),
                     json.dumps(f.keys, default=str)])
        for c in f.citations:
            con.execute("INSERT INTO citations VALUES (?, ?, ?, ?, ?)", [rid, f.id, c.file, c.location, c.snippet])
    for ln in invoice_lines or []:
        con.execute("INSERT INTO invoice_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [rid, ln["_file"], ln["_location"], ln.get("_invoice_id"), ln["tracking_number"],
                     ln["line_type"], ln["service"], int(ln["zone"]), float(ln["freight"]), float(ln["fuel"]),
                     float(ln["total"])])
    for r in result.rejected_mappings:
        con.execute("INSERT INTO rejected_mappings VALUES (?, ?, ?, ?)",
                    [rid, r.get("file"), r.get("proposed_by"), json.dumps(r.get("errors"), default=str)])
    for u in result.llm_usage:
        con.execute("INSERT INTO llm_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [rid, u["agent"], u["provider"], u["model"], u["calls"], u["tokens_in"], u["tokens_out"],
                     u["cost_usd"]])
    con.close()
