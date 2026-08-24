"""Post-freeze synthetic fraud holdout for GraphShield.

The detector implementation is hash-locked before these mutation families are
applied. A detector change invalidates the suite instead of allowing iterative
tuning on the holdout. These cases remain synthetic and are not a proxy for
production fraud prevalence or performance.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from agent.ledger import run_pipeline
from agent.risk import scan_bank_risk
from eval.challenge import pct, read_csv, recompute_balances, wilson_95, write_csv
from eval.risk_score import score_risk
from generator.generate import Generator, money


HOLDOUT_SEEDS = (20260911, 20260912, 20260913, 20260914, 20260915)
DETECTOR_PATH = Path(__file__).resolve().parents[1] / "agent" / "graph_intelligence.py"
FROZEN_GRAPHSHIELD_SHA256 = "59526f93d4ab45e37f3c61f44d8f239945f8ce4413e8814dffbcd4ab95bedbe1"
FROZEN_DETECTOR_VERSION = "graphshield-v1-before-fresh-holdout"


def detector_sha256() -> str:
    return hashlib.sha256(DETECTOR_PATH.read_bytes()).hexdigest()


def assert_detector_frozen() -> str:
    observed = detector_sha256()
    if observed != FROZEN_GRAPHSHIELD_SHA256:
        raise RuntimeError(
            "GraphShield changed after the fraud holdout was frozen. Create a new "
            "versioned holdout; do not rescore this partition with the modified detector."
        )
    return observed


def mutate_fresh_holdout(data_dir: Path, seed: int) -> dict[str, Any]:
    """Add novel temporal/aggregate/control-plane cases without detector access."""
    bank_fields, bank = read_csv(data_dir / "bank_statement.csv")
    cashbook_fields, cashbook = read_csv(data_dir / "cashbook.csv")
    truth = json.loads((data_dir / "risk_truth.json").read_text(encoding="utf-8"))
    latest = max(datetime.fromisoformat(row["txn_timestamp_utc"]) for row in bank)
    start = latest + timedelta(days=1)
    sequence = 0
    manifest: list[dict[str, Any]] = []

    def add_case(
        mutation: str,
        *,
        dubious: bool,
        direction: str,
        amount: Decimal,
        counterparty: str,
        purpose: str,
        timestamp: datetime,
    ) -> None:
        nonlocal sequence
        sequence += 1
        suffix = f"{seed % 1000:03d}{sequence:02d}"
        reference = f"FH{suffix}"
        bank_id = f"BNKFH{suffix}"
        cashbook.append({
            "event_id": f"CBKFH{suffix}",
            "event_timestamp_utc": (timestamp - timedelta(minutes=20)).isoformat(),
            "value_date": timestamp.strftime("%d/%m/%Y"),
            "direction": direction,
            "amount": str(money(amount)),
            "counterparty": counterparty,
            "reference": reference,
            "purpose": purpose,
            "approved_by": "synthetic-controller-policy",
        })
        bank.append({
            "bank_txn_id": bank_id,
            "txn_date": timestamp.strftime("%d/%m/%Y"),
            "value_date": timestamp.strftime("%d/%m/%Y"),
            "txn_timestamp_utc": timestamp.isoformat(),
            "transaction_type": (
                "OPERATING_CREDIT" if direction == "credit" else "OPERATING_DEBIT"
            ),
            "narration": f"{'IMPS' if direction == 'credit' else 'NEFT'}-{reference}-{counterparty.upper()}",
            "ref_no": reference,
            "debit": str(money(amount)) if direction == "debit" else "",
            "credit": str(money(amount)) if direction == "credit" else "",
            "balance": "0.00",
        })
        truth.append({
            "bank_txn_id": bank_id,
            "is_dubious": dubious,
            "direction": direction,
            "anomaly_type": mutation if dubious else "none",
            "amount": str(money(amount)),
            "transaction_timestamp_utc": timestamp.isoformat(),
            "truth_text": (
                f"Fresh post-freeze holdout mutation: {mutation}."
                if dubious else f"Fresh post-freeze benign control: {mutation}."
            ),
        })
        manifest.append({
            "seed": seed,
            "bank_txn_id": bank_id,
            "mutation": mutation,
            "truth": "dubious" if dubious else "clean",
        })

    # New family 1: several distinct approvals in 90 seconds. Each row is
    # locally valid; detecting the burst needs temporal approver-velocity state.
    for index, (amount, counterparty) in enumerate((
        (Decimal("18431.00"), "Aster Industrial Supply"),
        (Decimal("26719.00"), "Brookfield Office Goods"),
        (Decimal("31907.00"), "Cobalt Facility Services"),
    )):
        add_case(
            "approver_velocity_burst",
            dubious=True,
            direction="debit",
            amount=amount,
            counterparty=counterparty,
            purpose="rapid vendor approval cluster",
            timestamp=start + timedelta(seconds=45 * index),
        )

    # New family 2: one economic obligation split across independent-looking
    # references and unequal amounts. Detection needs cross-event aggregation.
    for index, amount in enumerate((Decimal("24001.00"), Decimal("25999.00"))):
        add_case(
            "structured_split_payment",
            dubious=True,
            direction="debit",
            amount=amount,
            counterparty="Delta Infrastructure Works",
            purpose="split invoice designed to evade aggregate approval limit",
            timestamp=start + timedelta(hours=2, minutes=index * 4),
        )

    # New family 3: bank and cashbook agree after a compromised vendor-master
    # edit. Independent beneficiary-account master data would be required.
    add_case(
        "coordinated_vendor_master_takeover",
        dubious=True,
        direction="debit",
        amount=Decimal("71321.00"),
        counterparty="Northlake Services Alias",
        purpose="vendor master and approval evidence changed together",
        timestamp=start + timedelta(hours=5),
    )

    # New family 4: locally consistent approval at an anomalous time. Current
    # GraphShield deliberately has no temporal behavior model.
    sunday = start + timedelta(days=(6 - start.weekday()) % 7)
    sunday = sunday.replace(hour=2, minute=15, second=0, microsecond=0)
    add_case(
        "out_of_hours_approval",
        dubious=True,
        direction="credit",
        amount=Decimal("44817.00"),
        counterparty="Orchid Channel Finance",
        purpose="approval outside established operating hours",
        timestamp=sunday,
    )

    # Fresh hard negatives: uncommon but legitimate evidence paths must remain
    # clear. They are part of the frozen partition and count toward specificity.
    for index, (direction, amount, counterparty) in enumerate((
        ("credit", Decimal("17311.00"), "Acme Retail Partner"),
        ("debit", Decimal("22117.00"), "Harbor Logistics India"),
        ("credit", Decimal("19519.00"), "Bluebird Distribution"),
    )):
        add_case(
            "benign_uncommon_operating_path",
            dubious=False,
            direction=direction,
            amount=amount,
            counterparty=counterparty,
            purpose="legitimate post-freeze holdout control",
            timestamp=start + timedelta(days=2, hours=index + 9),
        )

    bank.sort(key=lambda row: datetime.fromisoformat(row["txn_timestamp_utc"]))
    recompute_balances(bank)
    write_csv(data_dir / "bank_statement.csv", bank_fields, bank)
    write_csv(data_dir / "cashbook.csv", cashbook_fields, cashbook)
    (data_dir / "risk_truth.json").write_text(
        json.dumps(truth, indent=2), encoding="utf-8"
    )
    return {
        "manifest": manifest,
        "holdout_bank_ids": [item["bank_txn_id"] for item in manifest],
        "bank_entries": len(bank),
    }


def run_fraud_holdout(
    outdir: str | Path = "results/fraud_holdout",
    seeds: tuple[int, ...] = HOLDOUT_SEEDS,
) -> dict[str, Any]:
    detector_hash = assert_detector_frozen()
    started = time.perf_counter()
    all_rows: list[dict[str, Any]] = []
    all_baseline_rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []

    for seed in seeds:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir, results_dir = root / "data", root / "results"
            generator = Generator(seed=seed).run()
            generator.write(data_dir)
            mutation = mutate_fresh_holdout(data_dir, seed)
            predictions, _ = run_pipeline(data_dir, results_dir)

            scan_bank_risk(
                data_dir, results_dir, predictions, enable_graph_intelligence=False
            )
            _, baseline_graded = score_risk(
                results_dir / "risk_assessments.json",
                data_dir / "risk_truth.json",
                results_dir / "risk_baseline",
            )
            scan_bank_risk(
                data_dir, results_dir, predictions, enable_graph_intelligence=True
            )
            _, graph_graded = score_risk(
                results_dir / "risk_assessments.json",
                data_dir / "risk_truth.json",
                results_dir / "risk_graph",
            )

            holdout_ids = set(mutation["holdout_bank_ids"])
            all_rows.extend(
                {"seed": seed, **row} for row in graph_graded
                if row["bank_txn_id"] in holdout_ids
            )
            all_baseline_rows.extend(
                {"seed": seed, **row} for row in baseline_graded
                if row["bank_txn_id"] in holdout_ids
            )
            manifest.extend(mutation["manifest"])

    outcomes = Counter(row["outcome"] for row in all_rows)
    baseline_outcomes = Counter(row["outcome"] for row in all_baseline_rows)
    tp, fp = outcomes["true_positive"], outcomes["false_positive"]
    fn, tn = outcomes["false_negative"], outcomes["true_negative"]
    positive_count = tp + fn
    by_class = {}
    for mutation in sorted({item["mutation"] for item in manifest}):
        ids = {
            item["bank_txn_id"] for item in manifest if item["mutation"] == mutation
        }
        rows = [row for row in all_rows if row["bank_txn_id"] in ids]
        by_class[mutation] = {
            "records": len(rows),
            "dubious_records": sum(row["truth_dubious"] for row in rows),
            "detected": sum(row["predicted_dubious"] for row in rows),
            "recall": pct(
                sum(row["predicted_dubious"] and row["truth_dubious"] for row in rows),
                sum(row["truth_dubious"] for row in rows),
            ),
        }

    summary = {
        "suite": "post_freeze_synthetic_fraud_holdout",
        "partition_status": "never used to modify the frozen detector",
        "detector_version": FROZEN_DETECTOR_VERSION,
        "detector_sha256": detector_hash,
        "seed_count": len(seeds),
        "holdout_records": len(all_rows),
        "holdout_positive_records": positive_count,
        "holdout_negative_records": tn + fp,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": pct(tp, tp + fp),
        "recall": pct(tp, positive_count),
        "recall_95_ci": wilson_95(tp, positive_count),
        "specificity": pct(tn, tn + fp),
        "baseline_without_graph": {
            "true_positives": baseline_outcomes["true_positive"],
            "false_positives": baseline_outcomes["false_positive"],
            "false_negatives": baseline_outcomes["false_negative"],
            "true_negatives": baseline_outcomes["true_negative"],
        },
        "missed_classes": dict(Counter(
            row["truth_class"] for row in all_rows
            if row["outcome"] == "false_negative"
        )),
        "by_mutation_class": by_class,
        "methodological_limit": (
            "This post-freeze partition tests new synthetic temporal, aggregate, and "
            "control-plane families without changing GraphShield. It is stronger than "
            "the known-miss replay but still does not estimate production fraud recall."
        ),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }

    lines = [
        "# Post-freeze fraud holdout", "",
        f"Detector: `{FROZEN_DETECTOR_VERSION}` / `{detector_hash}`", "",
        "The detector hash is enforced before evaluation. These mutation families were not used to modify the detector.",
        "This remains a synthetic post-freeze test, not production fraud validation.", "",
        "| Metric | Value |", "|---|---|",
    ]
    for key in (
        "seed_count", "holdout_records", "holdout_positive_records",
        "holdout_negative_records", "true_positives", "false_positives",
        "false_negatives", "true_negatives", "precision", "recall",
        "recall_95_ci", "specificity", "duration_ms",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {summary[key]} |")
    lines += ["", "## Results by frozen mutation family", ""]
    for name, values in by_class.items():
        lines.append(
            f"- {name}: {values['detected']}/{values['dubious_records']} dubious rows detected; "
            f"recall {values['recall']}"
        )
    lines += ["", summary["methodological_limit"], ""]

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "fraud_holdout_metrics.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (outdir / "fraud_holdout_metrics.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    (outdir / "fraud_holdout_graded.json").write_text(
        json.dumps(all_rows, indent=2), encoding="utf-8"
    )
    (outdir / "fraud_holdout_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run_fraud_holdout(), indent=2))
