"""Shared current-batch scoring and explicit offline evaluation entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval.baseline import run as run_baseline
from eval.challenge import run_challenge
from eval.fraud_holdout import run_fraud_holdout
from eval.ledgergraph_eval import evaluate as evaluate_ledgergraph
from eval.risk_score import score_risk
from eval.robustness import run_robustness
from eval.score import score_paths


def sync_legacy_agent_outputs(results_dir: Path) -> None:
    """Keep documented historical paths current from one canonical source."""
    for name in ("metrics.md", "exceptions.md", "graded.json"):
        (results_dir / name).write_bytes((results_dir / "agent" / name).read_bytes())


def score_current_batch(
    data_dir: str | Path,
    results_dir: str | Path,
    *,
    system_name: str = "deterministic_controller",
) -> dict[str, Any]:
    """Score already-produced artifacts; never run multi-seed or mutation suites."""
    data_dir, results_dir = Path(data_dir), Path(results_dir)
    baseline = run_baseline(
        data_dir / "settlement_recon.csv", data_dir / "bank_statement.csv"
    )
    baseline_path = results_dir / "preds_baseline.json"
    baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    baseline_summary, _ = score_paths(
        baseline_path,
        data_dir / "ground_truth.json",
        results_dir / "baseline",
        "exact_utr_baseline",
    )
    agent_summary, _ = score_paths(
        results_dir / "preds_agent.json",
        data_dir / "ground_truth.json",
        results_dir / "agent",
        system_name,
    )
    risk_summary, _ = score_risk(
        results_dir / "risk_assessments.json",
        data_dir / "risk_truth.json",
        results_dir / "risk",
    )
    ledgergraph = evaluate_ledgergraph(results_dir / "ledgergraph")
    sync_legacy_agent_outputs(results_dir)
    return {
        "scope": "current_batch_only",
        "baseline": baseline_summary,
        "controller": agent_summary,
        "risk": risk_summary,
        "ledgergraph": ledgergraph,
    }


def run_offline_suites(results_dir: str | Path = "results") -> dict[str, Any]:
    """Run expensive regression and mutation suites outside the dashboard loop."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "scope": "offline_evaluation_only",
        "robustness": run_robustness(results_dir / "robustness"),
        "known_miss_replay": run_challenge(results_dir / "challenge"),
        "post_freeze_fraud_holdout": run_fraud_holdout(results_dir / "fraud_holdout"),
    }
    (results_dir / "offline_suite_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run expensive multi-seed and mutation evaluations explicitly."
    )
    parser.add_argument("--results", default="results")
    args = parser.parse_args()
    summary = run_offline_suites(args.results)
    print(
        json.dumps({
            "robustness_gate": summary["robustness"]["safety_gate_passed"],
            "known_miss_replay_recall": summary["known_miss_replay"]["recall"],
            "fresh_holdout_recall": summary["post_freeze_fraud_holdout"]["recall"],
            "fresh_holdout_false_negatives": summary["post_freeze_fraud_holdout"]["false_negatives"],
        }, indent=2)
    )


if __name__ == "__main__":
    main()
