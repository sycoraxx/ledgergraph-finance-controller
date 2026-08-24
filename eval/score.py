"""
Scorer for the reconciliation agent.

Reads a predictions file and grades it against ground_truth.json. Prints the
metrics table, a per-tier breakdown, and a calibration table. Writes
results/metrics.md and results/exceptions.md.

Predictions file: JSON list, one object per bank_txn_id.

    {
      "bank_txn_id": "BNK000031",
      "decision": "matched" | "escalated",
      "settlement_id": "setl_...",          # required when matched
      "component_payments": ["pay_..."],
      "component_refunds": [],
      "component_disputes": [],
      "component_adjustments": [],
      "confidence": 0.94,                    # 0..1
      "layer": "L1",
      "reason": "...",
      "citations": ["settlement_recon.csv:1204"]
    }

Outcome categories, per record:

  resolvable record:
    matched, batch correct              -> TRUE_MATCH
    matched, batch wrong                -> FALSE_MATCH
    escalated                           -> MISS          (cost, not error)
  unresolvable record:
    escalated                           -> TRUE_REFUSAL
    matched                             -> FALSE_MATCH_UNRESOLVABLE   (worst)

A miss is a cost. A false match is an error. They are never summed, because a
system that escalates everything would otherwise look safe.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from decimal import Decimal

TRUE_MATCH = "true_match"
FALSE_MATCH = "false_match"
MISS = "miss"
TRUE_REFUSAL = "true_refusal"
FALSE_MATCH_UNRESOLVABLE = "false_match_unresolvable"

REQUIRED = {"bank_txn_id", "decision"}
LIST_FIELDS = ("component_payments", "component_refunds",
               "component_disputes", "component_adjustments")


def load(path):
    with open(path) as f:
        return json.load(f)


def validate(preds):
    """Fail loudly on a malformed predictions file rather than scoring noise."""
    errs = []
    seen = set()
    for i, p in enumerate(preds):
        if not isinstance(p, dict):
            errs.append(f"[{i}] not an object")
            continue
        missing = REQUIRED - set(p)
        if missing:
            errs.append(f"[{i}] missing {sorted(missing)}")
            continue
        if p["bank_txn_id"] in seen:
            errs.append(f"[{i}] duplicate bank_txn_id {p['bank_txn_id']}")
        seen.add(p["bank_txn_id"])
        if p["decision"] not in ("matched", "escalated"):
            errs.append(f"[{i}] bad decision {p['decision']!r}")
        if p["decision"] == "matched" and not (
            p.get("settlement_id") or p.get("settlement_ids")
        ):
            errs.append(f"[{i}] matched without settlement evidence")
        if "settlement_ids" in p and not isinstance(p["settlement_ids"], list):
            errs.append(f"[{i}] settlement_ids is not a list")
        if "bank_txn_ids" in p and not isinstance(p["bank_txn_ids"], list):
            errs.append(f"[{i}] bank_txn_ids is not a list")
        c = p.get("confidence")
        if c is not None and not (0.0 <= float(c) <= 1.0):
            errs.append(f"[{i}] confidence {c} outside 0..1")
        for fld in LIST_FIELDS:
            if fld in p and not isinstance(p[fld], list):
                errs.append(f"[{i}] {fld} is not a list")
    return errs


def components(obj):
    """Full component set, as a set of ids. Order and duplicates are ignored."""
    out = set()
    for fld in LIST_FIELDS:
        out |= set(obj.get(fld) or [])
    return out


def identifiers(obj, plural, singular):
    values = obj.get(plural)
    if values is not None:
        return set(values)
    value = obj.get(singular)
    return {value} if value else set()


def grade(truth, preds):
    by_id = {p["bank_txn_id"]: p for p in preds}
    rows = []

    for t in truth:
        bid = t["bank_txn_id"]
        p = by_id.get(bid)
        # A record with no prediction is treated as escalated, but tracked
        # separately so silent non-coverage cannot be mistaken for caution.
        covered = p is not None
        decision = p["decision"] if covered else "escalated"
        conf = float(p.get("confidence", 0.0)) if covered else 0.0

        batch_resolvable = t.get("batch_resolvable", t.get("resolvable", True))
        components_resolvable = t.get(
            "components_resolvable", t.get("resolvable", True))
        settlement_ok = covered and identifiers(p, "settlement_ids", "settlement_id") == identifiers(
            t, "settlement_ids", "settlement_id"
        )
        bank_group_ok = covered and identifiers(p, "bank_txn_ids", "bank_txn_id") == identifiers(
            t, "bank_txn_ids", "bank_txn_id"
        )
        batch_ok = settlement_ok and bank_group_ok
        comp_ok = batch_ok and components(p) == components(t)
        component_status = (p or {}).get(
            "component_status",
            "reconciled" if decision == "matched" else "not_evaluated",
        )
        component_claimed = component_status == "reconciled"
        component_exception = component_status == "exception"

        if batch_resolvable:
            if decision == "matched":
                outcome = TRUE_MATCH if batch_ok else FALSE_MATCH
            else:
                outcome = MISS
        else:
            outcome = TRUE_REFUSAL if decision == "escalated" \
                else FALSE_MATCH_UNRESOLVABLE

        if components_resolvable:
            component_outcome = (
                "true_component_closure"
                if decision == "matched" and component_claimed and comp_ok
                else "component_miss"
            )
        else:
            component_outcome = (
                "true_component_refusal"
                if component_exception
                else "false_component_closure"
                if component_claimed
                else "missed_component_exception"
            )

        rows.append(dict(
            bank_txn_id=bid, tier=t["tier"], topology=t.get("topology", "1:1"),
            batch_resolvable=batch_resolvable,
            components_resolvable=components_resolvable,
            covered=covered, decision=decision, outcome=outcome,
            batch_ok=batch_ok, comp_ok=comp_ok, confidence=conf,
            component_status=component_status,
            component_outcome=component_outcome,
            layer=(p or {}).get("layer", ""), reason=(p or {}).get("reason", ""),
            truth_reason=t.get("unresolvable_reason"),
            component_issues=(p or {}).get("component_issues", []),
            approval_status=(p or {}).get("approval_status", ""),
            unresolved_amount=(p or {}).get(
                "unresolved_amount",
                str(abs(Decimal(t.get("credit", "0"))))
                if decision == "escalated" else "0",
            ),
            n_truth_components=len(components(t)),
            n_pred_components=len(components(p)) if covered else 0,
        ))
    return rows


def pct(num, den):
    return f"{100.0 * num / den:.1f}%" if den else "n/a"


def summarise(rows):
    n = len(rows)
    o = Counter(r["outcome"] for r in rows)
    matched = sum(1 for r in rows if r["decision"] == "matched")
    escalated = n - matched
    resolvable = sum(1 for r in rows if r["batch_resolvable"])
    component_resolvable = sum(1 for r in rows if r["components_resolvable"])
    component_unresolvable = n - component_resolvable

    true_match = o[TRUE_MATCH]
    false_match = o[FALSE_MATCH] + o[FALSE_MATCH_UNRESOLVABLE]
    component_closed = sum(1 for r in rows if r["component_status"] == "reconciled")
    true_component = sum(
        1 for r in rows if r["component_outcome"] == "true_component_closure")
    component_exceptions = sum(1 for r in rows if r["component_status"] == "exception")
    true_component_refusals = sum(
        1 for r in rows if r["component_outcome"] == "true_component_refusal")
    false_component_closures = sum(
        1 for r in rows if r["component_outcome"] == "false_component_closure")
    false_auto_closures = sum(
        1 for r in rows
        if r["component_status"] == "reconciled"
        and (not r["batch_ok"] or not r["comp_ok"] or not r["components_resolvable"])
    )
    unresolved_value = sum(
        (Decimal(r.get("unresolved_amount") or "0") for r in rows),
        Decimal("0"),
    )

    return {
        "records": n,
        "coverage": pct(sum(1 for r in rows if r["covered"]), n),
        "bank_match_rate": pct(matched, n),
        "bank_match_precision": pct(true_match, matched),
        "bank_recall_on_resolvable": pct(true_match, resolvable),
        "bank_false_matches": false_match,
        "bank_escalated": escalated,
        "component_closure_rate": pct(component_closed, n),
        "component_closure_precision": pct(true_component, component_closed),
        "component_recall_on_resolvable": pct(true_component, component_resolvable),
        "false_component_closures": false_component_closures,
        "component_exceptions": component_exceptions,
        "component_exception_precision": pct(true_component_refusals, component_exceptions),
        "component_unresolvable_recall": pct(true_component_refusals, component_unresolvable),
        "false_auto_closures": false_auto_closures,
        "unresolved_value_inr": f"{unresolved_value:.2f}",
    }


def per_tier(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["tier"]].append(r)
    out = []
    for tier in sorted(by):
        rs = by[tier]
        o = Counter(r["outcome"] for r in rs)
        matched = sum(1 for r in rs if r["decision"] == "matched")
        # Count credited outcomes only. A correct settlement_id on an
        # unresolvable record is still scored as a false match, so it must
        # not be counted here or the table contradicts itself.
        out.append(dict(
            tier=tier, n=len(rs),
            matched=matched,
            batch_ok=o[TRUE_MATCH],
            comp_ok=sum(1 for r in rs
                        if r["component_outcome"] == "true_component_closure"),
            false=o[FALSE_MATCH] + o[FALSE_MATCH_UNRESOLVABLE],
            miss=o[MISS],
            refusal=sum(1 for r in rs
                        if r["component_outcome"] == "true_component_refusal"),
            batch_acc=pct(o[TRUE_MATCH], len(rs)),
        ))
    return out


def calibration(rows, bins=5):
    """When the agent says 0.9, is it right 90% of the time?"""
    matched = [r for r in rows if r["decision"] == "matched"]
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [r for r in matched
               if (lo <= r["confidence"] < hi)
               or (i == bins - 1 and r["confidence"] == 1.0)]
        if not sel:
            out.append(dict(band=f"{lo:.1f}-{hi:.1f}", n=0,
                            mean_conf="n/a", actual="n/a"))
            continue
        acc = sum(1 for r in sel if r["batch_ok"]) / len(sel)
        out.append(dict(
            band=f"{lo:.1f}-{hi:.1f}", n=len(sel),
            mean_conf=f"{sum(r['confidence'] for r in sel) / len(sel):.2f}",
            actual=f"{acc:.2f}"))
    return out


def render(summary, tiers, calib, label):
    L = [f"# Metrics: {label}", "", "## Headline", "",
         "| Metric | Value |", "|---|---|"]
    for k, v in summary.items():
        L.append(f"| {k.replace('_', ' ')} | {v} |")

    L += ["", "## Per tier", "",
          "| Tier | n | Matched | Batch ok | Component ok | False | Miss | Refusal | Batch acc |",
          "|---|---|---|---|---|---|---|---|---|"]
    for t in tiers:
        L.append(f"| {t['tier']} | {t['n']} | {t['matched']} | {t['batch_ok']} "
                 f"| {t['comp_ok']} | {t['false']} | {t['miss']} | "
                 f"{t['refusal']} | {t['batch_acc']} |")

    L += ["", "## Calibration", "",
          "| Confidence band | n | Mean confidence | Actual accuracy |",
          "|---|---|---|---|"]
    for c in calib:
        L.append(f"| {c['band']} | {c['n']} | {c['mean_conf']} | {c['actual']} |")
    return "\n".join(L) + "\n"


def exceptions_md(rows, truth):
    tmap = {t["bank_txn_id"]: t for t in truth}
    esc = [r for r in rows
           if r["decision"] == "escalated"
           or r["component_status"] == "exception"
           or r["approval_status"] == "needs_review"]
    groups = defaultdict(list)
    for r in esc:
        key = (
            r["component_issues"][0]["reason"]
            if r["component_issues"]
            else "approval policy requires manual review"
            if r["approval_status"] == "needs_review"
            else r["reason"] or "(no reason given)"
        )
        groups[key].append(r)

    L = ["# Exceptions", "",
         f"{len(esc)} of {len(rows)} records require review.", ""]
    for key in sorted(groups, key=lambda k: -len(groups[k])):
        rs = groups[key]
        truly = sum(1 for r in rs if not r["components_resolvable"])
        L += [f"## {key}", "",
              f"{len(rs)} records. {truly} contain a planted component exception.", "",
              "| Record | Tier | Bank decision | Component status | Approval | Unresolved INR | Truth note |",
              "|---|---|---|---|---|---|---|"]
        for r in sorted(rs, key=lambda x: x["bank_txn_id"]):
            note = tmap[r["bank_txn_id"]].get("unresolvable_reason") or ""
            L.append(f"| {r['bank_txn_id']} | {r['tier']} | "
                     f"{r['decision']} | {r['component_status']} | "
                     f"{r['approval_status']} | {r['unresolved_amount']} | {note} |")
        L.append("")
    return "\n".join(L) + "\n"


def score_paths(predictions, truth_path="data/ground_truth.json",
                outdir="results", label=None):
    truth = load(truth_path)
    preds = load(predictions)
    errs = validate(preds)
    if errs:
        raise ValueError(
            "predictions file is malformed: " + "; ".join(errs[:20]))

    rows = grade(truth, preds)
    summary = summarise(rows)
    tiers = per_tier(rows)
    calib = calibration(rows)
    label = label or os.path.basename(predictions).replace(".json", "")

    md = render(summary, tiers, calib, label)
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/metrics.md", "w") as f:
        f.write(md)
    with open(f"{outdir}/exceptions.md", "w") as f:
        f.write(exceptions_md(rows, truth))
    with open(f"{outdir}/graded.json", "w") as f:
        json.dump(rows, f, indent=2)
    return summary, md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--truth", default="data/ground_truth.json")
    ap.add_argument("--outdir", default="results")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()

    try:
        summary, md = score_paths(
            a.predictions, a.truth, a.outdir, a.label)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    print(md)
    if summary["false_auto_closures"]:
        print(f"WARNING: {summary['false_auto_closures']} unsafe auto-closure(s).")


if __name__ == "__main__":
    main()
