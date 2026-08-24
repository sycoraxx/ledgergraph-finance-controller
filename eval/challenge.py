"""Known-miss regression replay for bank-risk controls.

Unlike the generator's closed-world cases, these mutations live in the eval
package and are applied after source generation. GraphShield's features were
informed by misses in this set, so its result is a regression control—not an
independent estimate of generalization.
"""

from __future__ import annotations

import csv
import json
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from math import sqrt
from pathlib import Path
from typing import Any

from agent.ledger import run_pipeline
from agent.risk import scan_bank_risk
from eval.risk_score import score_risk
from generator.generate import Generator, money


CHALLENGE_SEEDS = (20260831, 20260832, 20260833, 20260834, 20260835)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def recompute_balances(rows: list[dict[str, str]]) -> None:
    balance = Decimal("250000.00")
    for row in rows:
        balance = money(
            balance + Decimal(row.get("credit") or "0") - Decimal(row.get("debit") or "0")
        )
        row["balance"] = str(balance)


def mutate_challenge(data_dir: Path, seed: int) -> dict[str, Any]:
    bank_fields, bank = read_csv(data_dir / "bank_statement.csv")
    cashbook_fields, cashbook = read_csv(data_dir / "cashbook.csv")
    truth = json.loads((data_dir / "risk_truth.json").read_text(encoding="utf-8"))
    truth_by_bank = {row["bank_txn_id"]: row for row in truth}
    clean_operating = [
        row for row in bank
        if row["transaction_type"].startswith("OPERATING_")
        and not truth_by_bank[row["bank_txn_id"]]["is_dubious"]
    ]
    mutations = []

    # Hard negative: a normal one-day posting delay must not become a false positive.
    delayed = next(row for row in clean_operating if Decimal(row.get("credit") or "0") > 0)
    delayed_time = datetime.fromisoformat(delayed["txn_timestamp_utc"]) + timedelta(days=1)
    delayed["txn_timestamp_utc"] = delayed_time.isoformat()
    delayed["txn_date"] = delayed_time.strftime("%d/%m/%Y")
    delayed["value_date"] = delayed_time.strftime("%d/%m/%Y")
    mutations.append({"bank_txn_id": delayed["bank_txn_id"], "mutation": "benign_one_day_posting_lag", "truth": "clean"})

    # Hard positive: reference, amount and date still agree, but the beneficiary text changes.
    swapped = next(row for row in clean_operating if Decimal(row.get("debit") or "0") > 0)
    swapped["narration"] = f"NEFT-{swapped['ref_no']}-UNRELATED BENEFICIARY"
    swapped_truth = truth_by_bank[swapped["bank_txn_id"]]
    swapped_truth.update({
        "is_dubious": True,
        "anomaly_type": "counterparty_substitution",
        "truth_text": "Reference and amount agree, but the observed beneficiary is not the approved counterparty.",
    })
    mutations.append({"bank_txn_id": swapped["bank_txn_id"], "mutation": "counterparty_substitution", "truth": "dubious"})

    # Hard positive caught by statement arithmetic: alter one balance and carry the distortion forward.
    tamper_index = next(
        index for index, row in enumerate(bank)
        if row["transaction_type"] == "PAYMENT_GATEWAY_SETTLEMENT" and index > 20
    )
    tamper_id = bank[tamper_index]["bank_txn_id"]
    truth_by_bank[tamper_id].update({
        "is_dubious": True,
        "anomaly_type": "balance_rollforward_mismatch",
        "truth_text": "The reported closing balance was shifted without a corresponding transaction.",
    })
    mutations.append({"bank_txn_id": tamper_id, "mutation": "balance_tamper", "truth": "dubious"})

    # Hard positive beyond current deterministic evidence: an apparently valid
    # cashbook approval is created for a duplicate payment. This should remain
    # an honest miss until approval-identity/segregation evidence is available.
    source = next(row for row in clean_operating if Decimal(row.get("credit") or "0") > 0 and row is not delayed)
    source_cashbook = next(item for item in cashbook if item["reference"] == source["ref_no"])
    challenge_ref = f"COLL{seed % 100000:05d}"
    challenge_id = "BNK900000"
    challenge_time = datetime.fromisoformat(bank[-1]["txn_timestamp_utc"]) + timedelta(days=1)
    cashbook.append({
        **source_cashbook,
        "event_id": "CBK900000",
        "event_timestamp_utc": (challenge_time - timedelta(hours=5)).isoformat(),
        "value_date": challenge_time.strftime("%d/%m/%Y"),
        "reference": challenge_ref,
        "purpose": "duplicate remittance disguised as a new approval",
        "approved_by": "compromised-single-approver",
    })
    bank.append({
        **source,
        "bank_txn_id": challenge_id,
        "txn_date": challenge_time.strftime("%d/%m/%Y"),
        "value_date": challenge_time.strftime("%d/%m/%Y"),
        "txn_timestamp_utc": challenge_time.isoformat(),
        "narration": f"IMPS-{challenge_ref}-{source_cashbook['counterparty'].upper()}",
        "ref_no": challenge_ref,
    })
    truth.append({
        "bank_txn_id": challenge_id,
        "is_dubious": True,
        "direction": "credit",
        "anomaly_type": "collusive_duplicate",
        "amount": source_cashbook["amount"],
        "transaction_timestamp_utc": challenge_time.isoformat(),
        "truth_text": "A duplicate remittance is backed by a newly created single-approver cashbook record.",
    })
    mutations.append({"bank_txn_id": challenge_id, "mutation": "collusive_duplicate", "truth": "dubious"})

    recompute_balances(bank)
    distortion = Decimal("113.00")
    for index in range(tamper_index, len(bank)):
        bank[index]["balance"] = str(money(Decimal(bank[index]["balance"]) + distortion))

    write_csv(data_dir / "bank_statement.csv", bank_fields, bank)
    write_csv(data_dir / "cashbook.csv", cashbook_fields, cashbook)
    (data_dir / "risk_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return {"mutations": mutations, "challenge_bank_entries": len(bank)}


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def wilson_95(successes: int, total: int) -> list[str]:
    """Return a Wilson 95% interval without pretending synthetic rows are IID production traffic."""
    if not total:
        return ["n/a", "n/a"]
    z = 1.959963984540054
    estimate = successes / total
    denominator = 1 + z * z / total
    centre = (estimate + z * z / (2 * total)) / denominator
    margin = z * sqrt((estimate * (1 - estimate) + z * z / (4 * total)) / total) / denominator
    return [f"{100 * max(0, centre - margin):.1f}%", f"{100 * min(1, centre + margin):.1f}%"]


def run_challenge(
    outdir: str | Path = "results/challenge",
    seeds: tuple[int, ...] = CHALLENGE_SEEDS,
) -> dict[str, Any]:
    all_graded = []
    all_baseline_graded = []
    per_seed = []
    mutation_manifest = []
    started = time.perf_counter()
    for seed in seeds:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir, results_dir = root / "data", root / "results"
            generator = Generator(seed=seed).run()
            generator.write(data_dir)
            manifest = mutate_challenge(data_dir, seed)
            predictions, _ = run_pipeline(data_dir, results_dir)
            scan_bank_risk(
                data_dir, results_dir, predictions, enable_graph_intelligence=False
            )
            baseline_summary, baseline_graded = score_risk(
                results_dir / "risk_assessments.json",
                data_dir / "risk_truth.json",
                results_dir / "risk_baseline",
            )
            scan_bank_risk(
                data_dir, results_dir, predictions, enable_graph_intelligence=True
            )
            risk_summary, graded = score_risk(
                results_dir / "risk_assessments.json", data_dir / "risk_truth.json", results_dir / "risk"
            )
            all_graded.extend({"seed": seed, **row} for row in graded)
            all_baseline_graded.extend({"seed": seed, **row} for row in baseline_graded)
            mutation_manifest.extend({"seed": seed, **item} for item in manifest["mutations"])
            per_seed.append({
                "seed": seed,
                "bank_entries": manifest["challenge_bank_entries"],
                "precision": risk_summary["precision"],
                "recall": risk_summary["recall"],
                "false_positives": risk_summary["false_positives"],
                "false_negatives": risk_summary["false_negatives"],
                "baseline_recall": baseline_summary["recall"],
                "baseline_false_negatives": baseline_summary["false_negatives"],
            })

    outcomes = Counter(row["outcome"] for row in all_graded)
    tp, fp = outcomes["true_positive"], outcomes["false_positive"]
    fn, tn = outcomes["false_negative"], outcomes["true_negative"]
    misses = [row for row in all_graded if row["outcome"] == "false_negative"]
    false_positive_rows = [row for row in all_graded if row["outcome"] == "false_positive"]
    false_negative_exposure = sum(Decimal(row["amount"]) for row in misses)
    false_positive_review_value = sum(Decimal(row["amount"]) for row in false_positive_rows)
    baseline_outcomes = Counter(row["outcome"] for row in all_baseline_graded)
    baseline_tp = baseline_outcomes["true_positive"]
    baseline_fp = baseline_outcomes["false_positive"]
    baseline_fn = baseline_outcomes["false_negative"]
    baseline_tn = baseline_outcomes["true_negative"]
    classes = sorted({row["truth_class"] for row in all_graded if row["truth_dubious"]})
    by_mutation_class = {}
    for name in classes:
        enhanced_rows = [row for row in all_graded if row["truth_class"] == name]
        baseline_rows = [row for row in all_baseline_graded if row["truth_class"] == name]
        by_mutation_class[name] = {
            "records": len(enhanced_rows),
            "baseline_detected": sum(row["predicted_dubious"] for row in baseline_rows),
            "graph_detected": sum(row["predicted_dubious"] for row in enhanced_rows),
            "baseline_recall": pct(sum(row["predicted_dubious"] for row in baseline_rows), len(baseline_rows)),
            "graph_recall": pct(sum(row["predicted_dubious"] for row in enhanced_rows), len(enhanced_rows)),
        }
    summary = {
        "suite": "known_miss_control_replay",
        "seed_count": len(seeds),
        "bank_entries": len(all_graded),
        "mutations": len(mutation_manifest),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": pct(tp, tp + fp),
        "precision_95_ci": wilson_95(tp, tp + fp),
        "recall": pct(tp, tp + fn),
        "recall_95_ci": wilson_95(tp, tp + fn),
        "specificity": pct(tn, tn + fp),
        "false_negative_exposure_inr": f"{false_negative_exposure:.2f}",
        "false_positive_review_value_inr": f"{false_positive_review_value:.2f}",
        "missed_classes": dict(Counter(row["truth_class"] for row in misses)),
        "false_positive_classes": dict(Counter(row["predicted_class"] for row in false_positive_rows)),
        "baseline_without_graph": {
            "true_positives": baseline_tp,
            "true_negatives": baseline_tn,
            "false_positives": baseline_fp,
            "false_negatives": baseline_fn,
            "precision": pct(baseline_tp, baseline_tp + baseline_fp),
            "recall": pct(baseline_tp, baseline_tp + baseline_fn),
        },
        "graph_intelligence_delta": {
            "additional_true_positives": tp - baseline_tp,
            "false_negatives_removed": baseline_fn - fn,
            "false_positives_added": fp - baseline_fp,
            "recall_change": f"{pct(baseline_tp, baseline_tp + baseline_fn)} -> {pct(tp, tp + fn)}",
        },
        "by_mutation_class": by_mutation_class,
        "known_control_gap": (
            "GraphShield closes the two declared identity/motif gaps in this synthetic replay. "
            "Its features were designed after analysis of these misses, so this is regression "
            "evidence only—not validation on unseen fraud families."
        ),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "per_seed": per_seed,
    }

    lines = [
        "# Known-miss control replay", "",
        "This suite mutates generated exports after generation, but GraphShield's features were informed by these misses.",
        "Intervals describe this synthetic challenge only and are not production confidence bounds.", "",
        "| Metric | Value |", "|---|---|",
    ]
    for key in (
        "seed_count", "bank_entries", "mutations", "true_positives", "true_negatives",
        "false_positives", "false_negatives", "precision", "precision_95_ci", "recall",
        "recall_95_ci", "specificity", "false_negative_exposure_inr",
        "false_positive_review_value_inr", "duration_ms",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {summary[key]} |")
    lines += ["", "## Before/after graph intelligence", ""]
    lines.append(
        f"- deterministic controls: recall {summary['baseline_without_graph']['recall']}, "
        f"false negatives {summary['baseline_without_graph']['false_negatives']}"
    )
    lines.append(
        f"- GraphShield: recall {summary['recall']}, false negatives {summary['false_negatives']}, "
        f"additional false positives {summary['graph_intelligence_delta']['false_positives_added']}"
    )
    lines += ["", "## Known misses", ""]
    for name, count in summary["missed_classes"].items():
        lines.append(f"- {name}: {count}")
    lines += ["", summary["known_control_gap"], "", "## Mutations", ""]
    for item in mutation_manifest:
        lines.append(f"- seed {item['seed']} · {item['bank_txn_id']} · {item['mutation']} · truth={item['truth']}")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "challenge_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (outdir / "challenge_metrics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (outdir / "challenge_graded.json").write_text(json.dumps(all_graded, indent=2), encoding="utf-8")
    (outdir / "mutation_manifest.json").write_text(json.dumps(mutation_manifest, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_challenge(), indent=2))
