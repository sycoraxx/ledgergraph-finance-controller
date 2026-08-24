"""
Deliberately dumb baseline.

Matches a bank credit to a settlement only when BOTH hold:
  1. a UTR from the recon report appears verbatim in the bank narration, and
  2. the credit amount equals that settlement's (sum of credits - sum of debits)

No fuzzy matching, no subset search, no fee inversion, no model. Nothing that
is not a literal string or an exact decimal.

This exists to establish a floor. Every later result is quoted against it.
If this scores highly, the dataset is too easy and the tiers need hardening.
"""

import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def load_recon(path):
    """Settlement id -> {utr, net, payments, refunds, disputes, adjustments}."""
    agg = defaultdict(lambda: dict(
        utr=None, net=Decimal("0"), payments=[], refunds=[],
        disputes=[], adjustments=[]))
    bucket = {"payment": "payments", "refund": "refunds",
              "dispute": "disputes", "adjustment": "adjustments"}

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            sid = row["settlement_id"]
            s = agg[sid]
            s["utr"] = s["utr"] or row["settlement_utr"]
            s["net"] += (Decimal(row["credit"] or "0")
                         - Decimal(row["debit"] or "0"))
            key = bucket.get(row["transaction_entity"])
            if key:
                s[key].append(row["entity_id"])
    return agg


def run(recon_path, bank_path):
    settlements = load_recon(recon_path)
    recon_source = Path(recon_path)
    portable_recon_source = (
        f"{recon_source.parent.name}/{recon_source.name}"
        if recon_source.parent.name else recon_source.name
    )

    # Only settlements whose UTR is unique are candidates. A duplicate UTR is
    # ambiguous and the baseline refuses to guess.
    by_utr = defaultdict(list)
    for sid, s in settlements.items():
        if s["utr"]:
            by_utr[s["utr"]].append(sid)

    preds = []
    with open(bank_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("transaction_type") and row.get("transaction_type") != "PAYMENT_GATEWAY_SETTLEMENT":
                continue
            narration = row["narration"] or ""
            credit = Decimal(row["credit"] or "0") - Decimal(row["debit"] or "0")

            hit = None
            for utr, sids in by_utr.items():
                if len(sids) != 1:
                    continue
                if utr in narration:                      # verbatim only
                    s = settlements[sids[0]]
                    if s["net"].quantize(Decimal("0.01")) == credit:
                        hit = (sids[0], s)
                        break

            if hit:
                sid, s = hit
                preds.append(dict(
                    bank_txn_id=row["bank_txn_id"], decision="matched",
                    settlement_id=sid,
                    component_payments=s["payments"],
                    component_refunds=s["refunds"],
                    component_disputes=s["disputes"],
                    component_adjustments=s["adjustments"],
                    confidence=1.0, layer="L0-baseline",
                    reason="exact utr in narration and exact amount",
                    citations=[f"{portable_recon_source}:settlement_id={sid}"]))
            else:
                preds.append(dict(
                    bank_txn_id=row["bank_txn_id"], decision="escalated",
                    settlement_id=None, component_payments=[],
                    component_refunds=[], component_disputes=[],
                    component_adjustments=[], confidence=0.0,
                    layer="L0-baseline",
                    reason="no verbatim utr in narration, or amount mismatch",
                    citations=[]))
    return preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recon", default="data/settlement_recon.csv")
    ap.add_argument("--bank", default="data/bank_statement.csv")
    ap.add_argument("--out", default="results/preds_baseline.json")
    a = ap.parse_args()

    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    preds = run(a.recon, a.bank)
    with open(a.out, "w") as f:
        json.dump(preds, f, indent=2)

    m = sum(1 for p in preds if p["decision"] == "matched")
    print(f"{len(preds)} records, {m} matched, {len(preds) - m} escalated")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
