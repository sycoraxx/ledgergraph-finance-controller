"""Multi-seed closed-world conformance evaluation for the full controller."""

from __future__ import annotations

import json
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from agent.ledger import run_pipeline
from agent.risk import scan_bank_risk
from eval.risk_score import score_risk
from eval.score import grade, summarise
from generator.generate import Generator, self_check


DEFAULT_HOLDOUT_SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def run_robustness(
    outdir: str | Path = "results/robustness",
    seeds: tuple[int, ...] = DEFAULT_HOLDOUT_SEEDS,
) -> dict[str, Any]:
    per_seed = []
    all_reconciliation = []
    all_risk = []
    started = time.perf_counter()

    for seed in seeds:
        seed_started = time.perf_counter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir, results_dir = root / "data", root / "results"
            generator = Generator(seed=seed).run()
            truth = generator.write(data_dir)
            invariant_errors = self_check(generator, data_dir)
            if invariant_errors:
                raise RuntimeError(
                    f"holdout seed {seed} failed generator invariants: {invariant_errors[:3]}"
                )
            predictions, _ = run_pipeline(data_dir, results_dir)
            assessments, _ = scan_bank_risk(data_dir, results_dir, predictions)
            risk_summary, risk_graded = score_risk(
                results_dir / "risk_assessments.json",
                data_dir / "risk_truth.json",
                results_dir / "risk",
            )
            recon_graded = grade(truth, predictions)
            recon_summary = summarise(recon_graded)
            all_reconciliation.extend({"seed": seed, **row} for row in recon_graded)
            all_risk.extend({"seed": seed, **row} for row in risk_graded)
            per_seed.append({
                "seed": seed,
                "settlement_records": len(predictions),
                "bank_entries": len(assessments),
                "bank_match_precision": recon_summary["bank_match_precision"],
                "bank_recall": recon_summary["bank_recall_on_resolvable"],
                "false_auto_closures": recon_summary["false_auto_closures"],
                "risk_precision": risk_summary["precision"],
                "risk_recall": risk_summary["recall"],
                "risk_false_positives": risk_summary["false_positives"],
                "risk_false_negatives": risk_summary["false_negatives"],
                "duration_ms": int((time.perf_counter() - seed_started) * 1000),
            })

    recon_summary = summarise(all_reconciliation)
    risk_outcomes = Counter(row["outcome"] for row in all_risk)
    tp = risk_outcomes["true_positive"]
    fp = risk_outcomes["false_positive"]
    fn = risk_outcomes["false_negative"]
    tn = risk_outcomes["true_negative"]
    exact_classes = sum(row["class_correct"] for row in all_risk if row["truth_dubious"])
    positives = tp + fn
    directions = {}
    for direction in ("credit", "debit"):
        rows = [row for row in all_risk if row["direction"] == direction]
        direction_tp = sum(row["outcome"] == "true_positive" for row in rows)
        direction_fp = sum(row["outcome"] == "false_positive" for row in rows)
        direction_fn = sum(row["outcome"] == "false_negative" for row in rows)
        directions[direction] = {
            "records": len(rows),
            "dubious_records": sum(row["truth_dubious"] for row in rows),
            "precision": pct(direction_tp, direction_tp + direction_fp),
            "recall": pct(direction_tp, direction_tp + direction_fn),
            "false_positives": direction_fp,
            "false_negatives": direction_fn,
        }

    summary = {
        "seeds": list(seeds),
        "seed_count": len(seeds),
        "settlement_records": len(all_reconciliation),
        "bank_entries": len(all_risk),
        "dubious_entries": positives,
        "bank_match_precision": recon_summary["bank_match_precision"],
        "bank_recall_on_resolvable": recon_summary["bank_recall_on_resolvable"],
        "component_closure_precision": recon_summary["component_closure_precision"],
        "false_auto_closures": recon_summary["false_auto_closures"],
        "risk_precision": pct(tp, tp + fp),
        "risk_recall": pct(tp, positives),
        "risk_specificity": pct(tn, tn + fp),
        "risk_exact_class_accuracy": pct(exact_classes, positives),
        "risk_false_positives": fp,
        "risk_false_negatives": fn,
        "by_direction": directions,
        "safety_gate_passed": (
            recon_summary["false_auto_closures"] == 0
            and fp == 0 and fn == 0 and exact_classes == positives
        ),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "per_seed": per_seed,
    }

    lines = [
        "# Multi-seed closed-world conformance", "",
        (
            f"{len(seeds)} varied seeds; {len(all_reconciliation)} settlement records; "
            f"{len(all_risk)} total bank entries; {positives} planted dubious entries."
        ), "",
        "The controller never reads either reconciliation or risk ground truth during detection.", "",
        "| Metric | Value |", "|---|---|",
    ]
    for key in (
        "bank_match_precision", "bank_recall_on_resolvable", "component_closure_precision",
        "false_auto_closures", "risk_precision", "risk_recall", "risk_specificity",
        "risk_exact_class_accuracy", "risk_false_positives", "risk_false_negatives",
        "safety_gate_passed", "duration_ms",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {summary[key]} |")
    lines += ["", "## Per seed", "", "| Seed | Settlements | Bank entries | Bank precision | Bank recall | Unsafe closes | Risk precision | Risk recall | FP | FN | ms |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in per_seed:
        lines.append(
            f"| {row['seed']} | {row['settlement_records']} | {row['bank_entries']} | "
            f"{row['bank_match_precision']} | {row['bank_recall']} | {row['false_auto_closures']} | "
            f"{row['risk_precision']} | {row['risk_recall']} | {row['risk_false_positives']} | "
            f"{row['risk_false_negatives']} | {row['duration_ms']} |"
        )

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "robustness_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (outdir / "robustness_metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (outdir / "robustness_risk_graded.json").write_text(json.dumps(all_risk, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    result = run_robustness()
    print(json.dumps(result, indent=2))
