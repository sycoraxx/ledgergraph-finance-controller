"""Closed-world conformance scoring for bidirectional bank-entry controls."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def score_risk(
    assessments_path: str | Path,
    truth_path: str | Path,
    outdir: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assessments = json.loads(Path(assessments_path).read_text(encoding="utf-8"))
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    predicted = {row["bank_txn_id"]: row for row in assessments}
    expected = {row["bank_txn_id"]: row for row in truth}
    if len(predicted) != len(assessments) or set(predicted) != set(expected):
        missing = sorted(set(expected) - set(predicted))
        extra = sorted(set(predicted) - set(expected))
        raise ValueError(f"risk assessment coverage mismatch; missing={missing[:5]}, extra={extra[:5]}")

    graded = []
    for bank_id, expected_row in expected.items():
        actual = predicted[bank_id]
        truth_positive = bool(expected_row["is_dubious"])
        predicted_positive = bool(actual["is_dubious"])
        outcome = (
            "true_positive" if truth_positive and predicted_positive
            else "false_negative" if truth_positive
            else "false_positive" if predicted_positive
            else "true_negative"
        )
        graded.append({
            "bank_txn_id": bank_id,
            "direction": expected_row["direction"],
            "amount": expected_row["amount"],
            "truth_dubious": truth_positive,
            "predicted_dubious": predicted_positive,
            "truth_class": expected_row["anomaly_type"],
            "predicted_class": actual.get("anomaly_type", ""),
            "class_correct": actual.get("anomaly_type") == expected_row["anomaly_type"],
            "outcome": outcome,
            "reason": actual.get("reason", ""),
            "transaction_timestamp_utc": expected_row["transaction_timestamp_utc"],
        })

    outcomes = Counter(row["outcome"] for row in graded)
    tp, fp = outcomes["true_positive"], outcomes["false_positive"]
    fn, tn = outcomes["false_negative"], outcomes["true_negative"]
    positive = tp + fn
    negative = tn + fp
    false_negative_exposure = sum(
        Decimal(row["amount"]) for row in graded if row["outcome"] == "false_negative"
    )
    false_positive_review_value = sum(
        Decimal(row["amount"]) for row in graded if row["outcome"] == "false_positive"
    )
    exact_class = sum(row["class_correct"] for row in graded if row["truth_dubious"])

    by_direction = {}
    for direction in ("credit", "debit"):
        rows = [row for row in graded if row["direction"] == direction]
        positives = [row for row in rows if row["truth_dubious"]]
        by_direction[direction] = {
            "records": len(rows),
            "dubious_records": len(positives),
            "precision": pct(
                sum(row["outcome"] == "true_positive" for row in rows),
                sum(row["predicted_dubious"] for row in rows),
            ),
            "recall": pct(
                sum(row["outcome"] == "true_positive" for row in rows),
                len(positives),
            ),
            "false_positives": sum(row["outcome"] == "false_positive" for row in rows),
            "false_negatives": sum(row["outcome"] == "false_negative" for row in rows),
        }

    class_rows = defaultdict(list)
    for row in graded:
        if row["truth_dubious"]:
            class_rows[row["truth_class"]].append(row)
    by_class = {
        name: {
            "records": len(rows),
            "detected": sum(row["predicted_dubious"] for row in rows),
            "exact_class": sum(row["class_correct"] for row in rows),
            "recall": pct(sum(row["predicted_dubious"] for row in rows), len(rows)),
            "class_accuracy": pct(sum(row["class_correct"] for row in rows), len(rows)),
        }
        for name, rows in sorted(class_rows.items())
    }

    summary = {
        "records": len(graded),
        "dubious_records": positive,
        "clean_records": negative,
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": pct(tp, tp + fp),
        "recall": pct(tp, positive),
        "specificity": pct(tn, negative),
        "f1": pct(2 * tp, 2 * tp + fp + fn),
        "exact_anomaly_class_accuracy": pct(exact_class, positive),
        "false_negative_exposure_inr": f"{false_negative_exposure:.2f}",
        "false_positive_review_value_inr": f"{false_positive_review_value:.2f}",
        "safety_gate_passed": fn == 0 and fp == 0 and exact_class == positive,
        "by_direction": by_direction,
        "by_class": by_class,
    }

    lines = [
        "# Bidirectional bank-risk closed-world conformance", "",
        "Ground truth is generated before detection and is never read by the detector.", "",
        "| Metric | Value |", "|---|---|",
    ]
    for key in (
        "records", "dubious_records", "clean_records", "true_positives", "true_negatives",
        "false_positives", "false_negatives", "precision", "recall", "specificity", "f1",
        "exact_anomaly_class_accuracy", "false_negative_exposure_inr",
        "false_positive_review_value_inr", "safety_gate_passed",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {summary[key]} |")
    lines += ["", "## Direction breakdown", "", "| Direction | Records | Dubious | Precision | Recall | FP | FN |", "|---|---:|---:|---:|---:|---:|---:|"]
    for direction, row in by_direction.items():
        lines.append(
            f"| {direction} | {row['records']} | {row['dubious_records']} | {row['precision']} | "
            f"{row['recall']} | {row['false_positives']} | {row['false_negatives']} |"
        )
    lines += ["", "## Anomaly-class breakdown", "", "| Class | n | Detected | Exact class | Recall | Class accuracy |", "|---|---:|---:|---:|---:|---:|"]
    for name, row in by_class.items():
        lines.append(
            f"| {name} | {row['records']} | {row['detected']} | {row['exact_class']} | "
            f"{row['recall']} | {row['class_accuracy']} |"
        )

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "risk_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (outdir / "risk_metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (outdir / "risk_graded.json").write_text(json.dumps(graded, indent=2), encoding="utf-8")
    return summary, graded
