"""Command line.

    sightline corpora                         list installed corpus plugins
    sightline audit parcel_invoices [FILES]   run an audit (defaults to sample data)
    sightline scenario gri --pct 5.9          re-price sample invoices under a rate increase
    sightline serve                           start the FastAPI service
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from agents.llm import detect_provider, ledger


def cmd_corpora(_args) -> int:
    from sightline.core.plugins import discover

    for name, cfg in discover().items():
        print(f"{name:<18} {cfg.title}  (data: {cfg.data_dir.relative_to(cfg.data_dir.parents[1])})")
    return 0


def cmd_audit(args) -> int:
    from sightline.core.engine import run_audit

    files = [Path(f) for f in args.files] or None
    result, _ = run_audit(args.corpus, files, persist=not args.no_store)
    if args.json:
        print(result.model_dump_json(indent=2))
        return 0
    print(f"run {result.run_id}  corpus={result.corpus}  provider={detect_provider()}")
    for f in result.findings:
        amt = "" if f.amount_usd is None else f"${f.amount_usd:,.2f}"
        print(f"\n[{f.id}] {f.title}  ({f.classification}, {f.severity}) {amt}")
        print(f"    {f.explanation}")
        for c in f.citations[:3]:
            print(f"    - {c.file} | {c.location}")
    if result.stats.get("recoverable_usd") is not None:
        print(f"\nVerifiable recoverable total: ${result.stats['recoverable_usd']:,.2f}")
    if result.rejected_mappings:
        print(f"Rejected mappings/facts: {len(result.rejected_mappings)} (see runs/rejected_mappings.jsonl)")
    print("\nLLM usage this run:\n" + ledger().render())
    return 0


def gri_impact(pct: Decimal, data_dir: Path | None = None) -> list[dict]:
    """Contract-correct cost of each unique shipment today vs after a general
    rate increase of ``pct`` on list rates (discounts unchanged)."""
    from sightline.core.plugins import get_plugin

    plugin = get_plugin("parcel_invoices")
    files = sorted((data_dir or plugin.config.data_dir).iterdir())
    contract, invoices = plugin._split(files)
    terms = plugin.load_terms(contract)
    lines = plugin.load_lines(invoices)
    seen: set[str] = set()
    agg = defaultdict(lambda: {"shipments": 0, "current": Decimal(0), "after": Decimal(0)})
    for ln in lines:
        if ln["line_type"] != "SHIP" or ln["tracking_number"] in seen:
            continue
        seen.add(ln["tracking_number"])
        zone = terms.zone_for(ln["dest_zip"])
        wt = terms.billable_weight(ln["actual_weight"], ln["length"], ln["width"], ln["height"])
        now = terms.net_transport(ln["service"], zone, wt)
        after = terms.net_transport(ln["service"], zone, wt, gri_pct=pct)
        a = agg[ln["service"]]
        a["shipments"] += 1
        a["current"] += now + terms.fuel(now)
        a["after"] += after + terms.fuel(after)
    rows = []
    for svc in sorted(agg):
        a = agg[svc]
        rows.append({"service": svc, "shipments": a["shipments"], "current_usd": a["current"],
                     "after_usd": a["after"], "delta_usd": a["after"] - a["current"],
                     "delta_pct": ((a["after"] / a["current"] - 1) * 100).quantize(Decimal("0.01"))})
    return rows


def cmd_scenario(args) -> int:
    pct = Decimal(str(args.pct))
    rows = gri_impact(pct)
    if args.json:
        print(json.dumps(rows, default=str, indent=2))
        return 0
    print(f"General rate increase of {pct}% on list rates, contract discounts and fuel % unchanged.")
    print("Base: contract-correct price of each unique shipment in the sample invoices (freight + fuel).\n")
    print(f"{'service':<10}{'shipments':>10}{'current $':>13}{'after $':>13}{'delta $':>11}{'delta %':>9}")
    tot = defaultdict(Decimal)
    for r in rows:
        print(f"{r['service']:<10}{r['shipments']:>10}{r['current_usd']:>13,.2f}{r['after_usd']:>13,.2f}"
              f"{r['delta_usd']:>11,.2f}{r['delta_pct']:>9}")
        for k in ("shipments", "current_usd", "after_usd", "delta_usd"):
            tot[k] += r[k]
    pct_all = ((tot["after_usd"] / tot["current_usd"] - 1) * 100).quantize(Decimal("0.01"))
    print(f"{'TOTAL':<10}{tot['shipments']:>10}{tot['current_usd']:>13,.2f}{tot['after_usd']:>13,.2f}"
          f"{tot['delta_usd']:>11,.2f}{pct_all:>9}")
    print("\nEffective increase can differ from the headline % because of per-cent rounding at each step.")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sightline", description="Document and spend audit engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("corpora").set_defaults(fn=cmd_corpora)
    a = sub.add_parser("audit")
    a.add_argument("corpus")
    a.add_argument("files", nargs="*")
    a.add_argument("--json", action="store_true")
    a.add_argument("--no-store", action="store_true")
    a.set_defaults(fn=cmd_audit)
    s = sub.add_parser("scenario")
    s.add_argument("kind", choices=["gri"])
    s.add_argument("--pct", type=float, default=5.9)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scenario)
    v = sub.add_parser("serve")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(fn=cmd_serve)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
