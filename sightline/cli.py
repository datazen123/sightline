"""Command line.

    sightline corpora                         list installed corpus plugins
    sightline audit parcel_invoices [FILES]   run an audit (defaults to sample data)
    sightline scenario gri --pct 5.9          re-price sample invoices under a rate increase
    sightline scenario dim --divisor 166      re-price sample invoices under a different DIM divisor
    sightline scenario floor --labels 3000    target-price bidding: fixed discount vs a floor learner
    sightline serve                           start the FastAPI service
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import replace
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


def _unique_shipments(data_dir: Path | None = None):
    from sightline.core.plugins import get_plugin

    plugin = get_plugin("parcel_invoices")
    files = sorted((data_dir or plugin.config.data_dir).iterdir())
    contract, invoices = plugin._split(files)
    terms = plugin.load_terms(contract)
    seen: set[str] = set()
    ships = []
    for ln in plugin.load_lines(invoices):
        if ln["line_type"] != "SHIP" or ln["tracking_number"] in seen:
            continue
        seen.add(ln["tracking_number"])
        ships.append(ln)
    return terms, ships


def dim_impact(divisor: int, data_dir: Path | None = None) -> dict:
    """Contract-correct cost of each unique shipment with the contract's DIM
    (dimensional weight) divisor vs with ``divisor``. A larger divisor means a
    lower DIM weight, so light, bulky boxes bill at fewer pounds."""
    if not 100 <= divisor <= 250:
        raise ValueError("divisor must be between 100 and 250")
    terms, ships = _unique_shipments(data_dir)
    alt = replace(terms, dim_divisor=divisor)
    agg = defaultdict(lambda: {"shipments": 0, "reweighed": 0, "current": Decimal(0), "after": Decimal(0)})
    for ln in ships:
        zone = terms.zone_for(ln["dest_zip"])
        dims = (ln["actual_weight"], ln["length"], ln["width"], ln["height"])
        w_now = terms.billable_weight(*dims)
        w_new = alt.billable_weight(*dims)
        now = terms.net_transport(ln["service"], zone, w_now)
        new = terms.net_transport(ln["service"], zone, w_new)
        a = agg[ln["service"]]
        a["shipments"] += 1
        a["reweighed"] += int(w_new != w_now)
        a["current"] += now + terms.fuel(now)
        a["after"] += new + terms.fuel(new)
    rows = [{"service": svc, "shipments": a["shipments"], "reweighed": a["reweighed"],
             "current_usd": a["current"], "after_usd": a["after"], "delta_usd": a["after"] - a["current"]}
            for svc, a in sorted(agg.items())]
    return {"contract_divisor": terms.dim_divisor, "divisor": divisor, "rows": rows}


def floor_impact(labels: int = 3000, seed: int = 7, data_dir: Path | None = None) -> dict:
    """Replay the sample shipments as target-price labels against a synthetic
    carrier and compare bidding strategies (see corpora/parcel_invoices/floor.py)."""
    from corpora.parcel_invoices.floor import Segment, band, simulate

    terms, ships = _unique_shipments(data_dir)
    pool = []
    for ln in ships:
        zone = terms.zone_for(ln["dest_zip"])
        wt = terms.billable_weight(ln["actual_weight"], ln["length"], ln["width"], ln["height"])
        net = terms.net_transport(ln["service"], zone, wt)
        pool.append((Segment(ln["service"], zone, "", band(wt)), net + terms.fuel(net)))
    return simulate(pool, labels=labels, seed=seed)


def _print_floor(args) -> int:
    res = floor_impact(args.labels, args.seed)
    if args.json:
        print(json.dumps(res, default=str, indent=2))
        return 0
    print(f"{res['labels']:,} target-price labels drawn from the sample shipments (seed {res['seed']}).")
    print("Synthetic carrier: hidden floors vary by zone, weekday and weight band; a decline costs the contract rate.\n")
    print(f"{'strategy':<34}{'paid $':>12}{'saved $':>11}{'saved %':>9}{'accepted %':>12}")
    for r in res["rows"]:
        acc = f"{r['accept_pct']}" if r["accept_pct"] is not None else "-"
        print(f"{r['strategy']:<34}{r['paid_usd']:>12,.2f}{r['saved_usd']:>11,.2f}{r['saved_pct']:>9}{acc:>12}")
    print(f"\nThe learner captured {res['learner_share_of_possible_pct']}% of the savings that perfect knowledge "
          "of every floor would give. It never bids at or above contract.")
    return 0


def cmd_scenario(args) -> int:
    if args.kind == "dim":
        return _print_dim(args)
    if args.kind == "floor":
        return _print_floor(args)
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


def _print_dim(args) -> int:
    res = dim_impact(args.divisor)
    if args.json:
        print(json.dumps(res, default=str, indent=2))
        return 0
    print(f"DIM divisor {res['contract_divisor']} (contract) vs {res['divisor']}, rates, discounts and fuel % unchanged.")
    print("Base: contract-correct price of each unique shipment in the sample invoices (freight + fuel).\n")
    print(f"{'service':<10}{'shipments':>10}{'reweighed':>11}{'current $':>13}{'after $':>13}{'delta $':>11}")
    tot = defaultdict(Decimal)
    for r in res["rows"]:
        print(f"{r['service']:<10}{r['shipments']:>10}{r['reweighed']:>11}{r['current_usd']:>13,.2f}"
              f"{r['after_usd']:>13,.2f}{r['delta_usd']:>11,.2f}")
        for k in ("shipments", "reweighed", "current_usd", "after_usd", "delta_usd"):
            tot[k] += r[k]
    print(f"{'TOTAL':<10}{tot['shipments']:>10}{tot['reweighed']:>11}{tot['current_usd']:>13,.2f}"
          f"{tot['after_usd']:>13,.2f}{tot['delta_usd']:>11,.2f}")
    print("\nOnly shipments whose DIM weight exceeds their actual weight change price.")
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
    s.add_argument("kind", choices=["gri", "dim", "floor"])
    s.add_argument("--pct", type=float, default=5.9, help="gri: rate increase in percent")
    s.add_argument("--divisor", type=int, default=166, help="dim: DIM divisor to compare against the contract")
    s.add_argument("--labels", type=int, default=3000, help="floor: number of target-price labels to simulate")
    s.add_argument("--seed", type=int, default=7, help="floor: random seed for the synthetic carrier")
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
