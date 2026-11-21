"""Stress test for ingestion: what happens when inputs are not friendly.

Builds a perturbed copy of the parcel pack in a temp dir:
  * inv_2026-09.csv: every header renamed to names the offline mapper has
    never seen ("Pkg Ref", "Shipped On", ...).
  * inv_2026-10.xlsx: the stated "Amount Due" is changed by +$1.00, so the
    detail no longer reconciles to the summary.
  * inv_2026-11.pdf: unchanged.

Expected, and reported honestly:
  * offline mode: the CSV is rejected (required fields unmapped), the XLSX is
    rejected (totals do not reconcile). Their issues are MISSED. That is the
    design: an unreconciled file is never audited on trust.
  * with an LLM key: the CSV is likely mapped by the model and recovered; the
    XLSX is still rejected, because no mapping can fix a wrong control total.

Run: uv run python eval/stress_parcel.py
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook  # noqa: E402

from agents.llm import detect_provider  # noqa: E402
from sightline.core.engine import run_audit  # noqa: E402
from sightline.core.plugins import get_plugin  # noqa: E402

RENAMES = ["Pkg Ref", "Shipped On", "Product", "From Postcode", "To Postcode", "Delivery Class", "Len",
           "Wid", "Hgt", "Scale Lbs", "Rated Lbs", "Rate Band", "Base Chg", "Energy Chg", "Home Dlvry",
           "Addr Fix", "Extra", "Extra Note", "Amount", "Deliver To"]


def build(tmp: Path) -> None:
    src = get_plugin("parcel_invoices").config.data_dir
    for f in src.iterdir():
        shutil.copy(f, tmp / f.name)
    rows = list(csv.reader((src / "inv_2026-09.csv").open()))
    hdr = next(i for i, r in enumerate(rows) if not r[0].startswith("#"))
    rows[hdr] = RENAMES
    with (tmp / "inv_2026-09.csv").open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    wb = load_workbook(tmp / "inv_2026-10.xlsx")
    ws = wb["Summary"]
    for row in ws.iter_rows():
        if row[0].value == "Amount Due":
            amt = float(str(row[1].value).replace("$", "").replace(",", "")) + 1.00
            row[1].value = f"${amt:,.2f}"
    wb.save(tmp / "inv_2026-10.xlsx")


def main() -> int:
    seeded = json.loads((Path(__file__).parent / "seeded_issues_parcel.json").read_text())["issues"]
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        build(tmp)
        result, plugin = run_audit("parcel_invoices", sorted(tmp.iterdir()), persist=False)
    print(f"mode: {detect_provider()}")
    print("files accepted:", [f["file"] + f" ({f['mapping_by']})" for f in plugin.stats.get("files", [])])
    print("files rejected:", plugin.stats.get("files_rejected", []))
    for r in result.rejected_mappings:
        print(f"  rejected {r['file']} [{r['proposed_by']}]: {r['errors'][:2]}")
    caught = 0
    for issue in seeded:
        hit = any(f.rule == issue["rule"] and set(issue["keys"]) & plugin.match_key(f) for f in result.findings)
        caught += hit
        print(f"  {'CAUGHT' if hit else 'MISSED':<7} {issue['id']:<28} ({issue['file']})")
    print(f"recall under stress: {caught}/{len(seeded)}  findings: {len(result.findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
