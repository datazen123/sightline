"""Score each corpus against its planted ground truth.

    uv run python eval/run_eval.py                 # all corpora
    uv run python eval/run_eval.py parcel_invoices # one corpus
    uv run python eval/run_eval.py --min-recall 1.0  # fail CI on regression

For every corpus it prints, per seeded issue, whether it was caught, with
which classification, and whether the computed amount matches; then a
precision / recall table. Findings that match no seeded issue are counted as
unmatched and lower precision, even when they look reasonable: the table
reports what happened, not what we hoped.

With no API key the LLM steps run on the offline stand-ins (heuristic column
mapper; recorded CRE extraction). The header line says which mode ran.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.llm import detect_provider  # noqa: E402
from sightline.core.engine import run_audit  # noqa: E402
from sightline.core.plugins import discover  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "runs"


def score(corpus: str) -> dict:
    cfg = discover()[corpus]
    seeded = json.loads(cfg.seeded_issues.read_text())["issues"]
    result, plugin = run_audit(corpus, persist=True)
    findings = result.findings
    matched_ids: set[str] = set()
    rows = []
    for issue in seeded:
        want = {str(k) for k in issue["keys"]}
        cands = [f for f in findings if f.rule == issue["rule"] and want & plugin.match_key(f)]
        best = cands[0] if cands else None
        if best:
            matched_ids.add(best.id)
        amt_ok = None
        if best and issue.get("expected_amount_usd") is not None:
            amt_ok = best.amount_usd is not None and abs(best.amount_usd - issue["expected_amount_usd"]) < 0.015
        rows.append({
            "issue": issue["id"], "expected": issue["classification"],
            "caught": best is not None, "got": best.classification if best else None,
            "class_ok": bool(best and best.classification == issue["classification"]),
            "amount_ok": amt_ok, "finding": best.id if best else None,
            "amount": best.amount_usd if best else None,
        })
    unmatched = [f for f in findings if f.id not in matched_ids]
    n, caught = len(seeded), sum(r["caught"] for r in rows)
    class_ok = sum(r["class_ok"] for r in rows)
    precision = (len(matched_ids) / len(findings)) if findings else 0.0
    return {
        "corpus": corpus, "seeded": n, "caught": caught, "class_ok": class_ok,
        "findings": len(findings), "unmatched": [{"id": f.id, "rule": f.rule, "title": f.title,
                                                  "classification": f.classification} for f in unmatched],
        "precision": round(precision, 3), "recall": round(caught / n, 3) if n else 0.0,
        "class_accuracy": round(class_ok / caught, 3) if caught else 0.0,
        "amounts_checked": sum(1 for r in rows if r["amount_ok"] is not None),
        "amounts_ok": sum(1 for r in rows if r["amount_ok"]),
        "rows": rows, "llm_cost_usd": result.llm_cost_usd, "stats": result.stats,
        "run_id": result.run_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpora", nargs="*")
    ap.add_argument("--min-recall", type=float, default=0.0)
    ap.add_argument("--min-precision", type=float, default=0.0)
    args = ap.parse_args()
    names = args.corpora or list(discover())
    mode = detect_provider()
    print(f"mode: {mode}" + ("  (no API key: offline stand-ins for LLM steps; scores measure the "
                             "deterministic layer)" if mode == "mock" else ""))
    results = []
    for name in names:
        r = score(name)
        results.append(r)
        print(f"\n== {name} ==")
        print(f"{'seeded issue':<28}{'expected':<19}{'got':<19}{'amount':>14}  result")
        for row in r["rows"]:
            status = ("MISS" if not row["caught"] else "OK" if row["class_ok"] else "WRONG CLASS")
            if row["amount_ok"] is False:
                status += " (amount off)"
            amt = "" if row["amount"] is None else f"${row['amount']:,.2f}"
            print(f"{row['issue']:<28}{row['expected']:<19}{(row['got'] or '-'):<19}{amt:>14}  {status}")
        for u in r["unmatched"]:
            print(f"  unmatched finding {u['id']}: {u['rule']} ({u['classification']}) - {u['title']}")

    print("\n" + f"{'corpus':<18}{'seeded':>7}{'caught':>7}{'findings':>9}{'unmatched':>10}"
          f"{'precision':>10}{'recall':>8}{'class acc':>10}{'amounts':>9}")
    for r in results:
        print(f"{r['corpus']:<18}{r['seeded']:>7}{r['caught']:>7}{r['findings']:>9}{len(r['unmatched']):>10}"
              f"{r['precision']:>10.2f}{r['recall']:>8.2f}{r['class_accuracy']:>10.2f}"
              f"{r['amounts_ok']:>5}/{r['amounts_checked']:<3}")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "eval_results.json").write_text(json.dumps({"mode": mode, "results": results}, indent=2, default=str))
    failed = [r for r in results if r["recall"] < args.min_recall or r["precision"] < args.min_precision]
    if failed:
        print(f"\nFAIL: below threshold for {[r['corpus'] for r in failed]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
