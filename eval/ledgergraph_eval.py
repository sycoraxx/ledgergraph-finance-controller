"""Adversarial, synthetic evaluation for global reconciliation hypotheses.

This suite measures reconciliation structure, not production fraud detection.
Cases are deliberately small so every expected graph edge can be inspected.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from agent.l0_exact import reconcile_exact
from agent.l1_search import reconcile_search
from agent.ledger_graph import build_candidate_graph, solve_candidate_graph


def settlement(amount: str, utr: str, settled_date: str = "2026-01-01") -> dict[str, Any]:
    return {"net": Decimal(amount), "utr": utr, "settled_dates": {settled_date}, "rows": []}


def bank(identifier: str, amount: str, narration: str, value_date: str = "01/01/2026") -> dict[str, str]:
    signed = Decimal(amount)
    return {
        "bank_txn_id": identifier,
        "credit": str(signed) if signed >= 0 else "",
        "debit": str(abs(signed)) if signed < 0 else "",
        "value_date": value_date,
        "narration": narration,
    }


def signature(bank_ids: list[str] | tuple[str, ...], settlement_ids: list[str] | tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return tuple(sorted(bank_ids)), tuple(sorted(settlement_ids))


def cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "exact_reference",
            "partition": "calibration",
            "claim": "Full UTR and signed amount agree.",
            "banks": [bank("B-EXACT", "100.00", "NEFT UTR-EXACT-001")],
            "settlements": {"S-EXACT": settlement("100.00", "UTR-EXACT-001")},
            "truth": {signature(["B-EXACT"], ["S-EXACT"])},
        },
        {
            "id": "global_collision",
            "partition": "held_out",
            "claim": "A strong edge disambiguates a same-amount batch globally; row order must not decide.",
            "banks": [
                bank("B-UNKNOWN", "250.00", "SETTLEMENT CREDIT"),
                bank("B-KNOWN", "250.00", "NEFT UTR-KNOWN-002"),
            ],
            "settlements": {
                "S-KNOWN": settlement("250.00", "UTR-KNOWN-002"),
                "S-RESIDUAL": settlement("250.00", "UTR-RESIDUAL-002"),
            },
            "truth": {
                signature(["B-KNOWN"], ["S-KNOWN"]),
                signature(["B-UNKNOWN"], ["S-RESIDUAL"]),
            },
        },
        {
            "id": "reference_typo",
            "partition": "calibration",
            "claim": "A one-character UTR mutation may propose a candidate but exact money remains mandatory.",
            "banks": [bank("B-TYPO", "315.00", "NEFT UTRTYPO0008X")],
            "settlements": {"S-TYPO": settlement("315.00", "UTRTYPO00081")},
            "truth": {signature(["B-TYPO"], ["S-TYPO"])},
        },
        {
            "id": "posting_window",
            "partition": "held_out",
            "claim": "A two-day posting delay is supported without changing the amount invariant.",
            "banks": [bank("B-DELAY", "480.00", "BATCH CREDIT", "03/01/2026")],
            "settlements": {"S-DELAY": settlement("480.00", "UTR-DELAY-004")},
            "truth": {signature(["B-DELAY"], ["S-DELAY"])},
        },
        {
            "id": "many_to_one",
            "partition": "held_out",
            "claim": "Two gateway settlements arrive as one aggregated bank credit.",
            "banks": [bank("B-MERGED", "100.00", "AGGREGATED CREDIT")],
            "settlements": {
                "S-40": settlement("40.00", "UTR-MERGE-40"),
                "S-60": settlement("60.00", "UTR-MERGE-60"),
            },
            "truth": {signature(["B-MERGED"], ["S-40", "S-60"])},
        },
        {
            "id": "one_to_many",
            "partition": "held_out",
            "claim": "One gateway settlement arrives as two partial bank credits.",
            "banks": [
                bank("B-SPLIT-40", "40.00", "PARTIAL CREDIT 1"),
                bank("B-SPLIT-60", "60.00", "PARTIAL CREDIT 2"),
            ],
            "settlements": {"S-SPLIT": settlement("100.00", "UTR-SPLIT-100")},
            "truth": {signature(["B-SPLIT-40", "B-SPLIT-60"], ["S-SPLIT"])},
        },
        {
            "id": "many_to_many",
            "partition": "held_out",
            "claim": "Two bank postings jointly settle two gateway batches; only the atomic group conserves money.",
            "banks": [
                bank("B-NM-45", "45.00", "NET GROUP UTR-NM-50 UTR-NM-70"),
                bank("B-NM-75", "75.00", "NET GROUP UTR-NM-50 UTR-NM-70"),
            ],
            "settlements": {
                "S-NM-50": settlement("50.00", "UTR-NM-50"),
                "S-NM-70": settlement("70.00", "UTR-NM-70"),
            },
            "truth": {signature(["B-NM-45", "B-NM-75"], ["S-NM-50", "S-NM-70"])},
        },
        {
            "id": "signed_debit",
            "partition": "held_out",
            "claim": "Debit direction is conserved, not silently compared as an unsigned magnitude.",
            "banks": [bank("B-DEBIT", "-75.00", "REVERSAL UTR-DEBIT-007")],
            "settlements": {"S-DEBIT": settlement("-75.00", "UTR-DEBIT-007")},
            "truth": {signature(["B-DEBIT"], ["S-DEBIT"])},
        },
        {
            "id": "amount_only_abstention",
            "partition": "calibration",
            "claim": "A unique amount without date or reference corroboration is insufficient.",
            "banks": [bank("B-AMOUNT", "999.00", "UNEXPLAINED CREDIT", "15/02/2026")],
            "settlements": {"S-AMOUNT": settlement("999.00", "UTR-NO-EVIDENCE", "2026-01-01")},
            "truth": set(),
        },
        {
            "id": "tied_optimum",
            "partition": "calibration",
            "claim": "Two indistinguishable candidates produce an explicit abstention.",
            "banks": [bank("B-TIE", "10.00", "UNKNOWN")],
            "settlements": {
                "S-TIE-A": settlement("10.00", "A"),
                "S-TIE-B": settlement("10.00", "B"),
            },
            "truth": set(),
        },
        {
            "id": "fuzzy_money_conflict",
            "partition": "held_out",
            "claim": "A close UTR cannot override a ₹10 money residual.",
            "banks": [bank("B-CONFLICT", "100.00", "UTRCONFLICT09")],
            "settlements": {"S-CONFLICT": settlement("90.00", "UTRCONFLICT01")},
            "truth": set(),
        },
    ]


def rowwise(case: dict[str, Any], matcher: Callable[..., dict[str, Any] | None]) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    available = dict(case["settlements"])
    output = set()
    for row in case["banks"]:
        match = matcher(row, available)
        if match:
            sid = match["settlement_id"]
            output.add(signature([row["bank_txn_id"]], [sid]))
            available.pop(sid)
    return output


def layered_rowwise(case: dict[str, Any]) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
    available = dict(case["settlements"])
    output = set()
    for row in case["banks"]:
        match = reconcile_exact(row, available) or reconcile_search(row, available)
        if match:
            sid = match["settlement_id"]
            output.add(signature([row["bank_txn_id"]], [sid]))
            available.pop(sid)
    return output


def graph_predictions(case: dict[str, Any], threshold: int = 65) -> tuple[set[Any], dict[str, Any], dict[str, Any]]:
    graph = build_candidate_graph(case["banks"], case["settlements"], max_group_size=2)
    solution = solve_candidate_graph(graph, selection_threshold=threshold)
    predicted = {
        signature(candidate["bank_ids"], candidate["settlement_ids"])
        for candidate in solution["selected"]
    }
    return predicted, graph, solution


def summarise(results: list[dict[str, Any]], system: str) -> dict[str, Any]:
    predicted = sum(item[system]["predicted"] for item in results)
    correct = sum(item[system]["correct"] for item in results)
    false = sum(item[system]["false"] for item in results)
    expected = sum(item["expected"] for item in results)
    return {
        "system": system,
        "expected_hypotheses": expected,
        "selected_hypotheses": predicted,
        "correct_hypotheses": correct,
        "false_selections": false,
        "hypothesis_recall": f"{(correct / expected if expected else 1):.1%}",
        "selection_precision": f"{(correct / predicted if predicted else 1):.1%}",
        "cases_exactly_correct": sum(item[system]["exact"] for item in results),
        "case_count": len(results),
    }


def evaluate(output_dir: str | Path = "results/ledgergraph") -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    certificates = []
    for case in cases():
        systems = {
            "exact_reference_baseline": rowwise(case, reconcile_exact),
            "rowwise_l0_l1": layered_rowwise(case),
        }
        graph_selected, graph, solution = graph_predictions(case)
        systems["ledgergraph_global"] = graph_selected
        truth = case["truth"]
        record: dict[str, Any] = {
            "case_id": case["id"],
            "partition": case["partition"],
            "claim": case["claim"],
            "expected": len(truth),
            "truth": [[list(left), list(right)] for left, right in sorted(truth)],
            "ledgergraph_candidate_count": len(graph["candidates"]),
            "ledgergraph_abstained_banks": solution["abstained_bank_ids"],
        }
        for name, selected in systems.items():
            record[name] = {
                "predicted": len(selected),
                "correct": len(selected & truth),
                "false": len(selected - truth),
                "exact": selected == truth,
                "selected": [[list(left), list(right)] for left, right in sorted(selected)],
            }
        results.append(record)
        certificates.extend({**item, "case_id": case["id"]} for item in solution["certificates"])

    comparison = [
        summarise(results, "exact_reference_baseline"),
        summarise(results, "rowwise_l0_l1"),
        summarise(results, "ledgergraph_global"),
    ]
    risk_coverage = []
    for threshold in (55, 65, 70, 90):
        selections = []
        for case in (item for item in cases() if item["partition"] == "calibration"):
            selected, _, _ = graph_predictions(case, threshold)
            selections.append((selected, case["truth"]))
        predicted = sum(len(selected) for selected, _ in selections)
        correct = sum(len(selected & truth) for selected, truth in selections)
        false = sum(len(selected - truth) for selected, truth in selections)
        expected = sum(len(truth) for _, truth in selections)
        risk_coverage.append({
            "threshold": threshold,
            "coverage_of_expected": f"{correct / expected:.1%}",
            "selection_precision": f"{(correct / predicted if predicted else 1):.1%}",
            "false_selections": false,
            "selected_hypotheses": predicted,
        })

    held_out_results = [item for item in results if item["partition"] == "held_out"]
    held_out_graph = summarise(held_out_results, "ledgergraph_global")
    metrics = {
        "suite": "LedgerGraph adversarial reconciliation suite",
        "data_classification": "fully_synthetic",
        "case_count": len(results),
        "selection_threshold": 65,
        "threshold_policy": "lowest tested threshold with zero false selections on the four-case calibration partition",
        "calibration_case_count": 4,
        "held_out_case_count": len(held_out_results),
        "held_out_ledgergraph": held_out_graph,
        "comparison": comparison,
        "risk_coverage": risk_coverage,
        "grouped_topology_cases": 3,
        "grouped_topology_cases_correct": sum(
            item["ledgergraph_global"]["exact"] for item in results
            if item["case_id"] in {"many_to_one", "one_to_many", "many_to_many"}
        ),
        "proof_certificate_count": len(certificates),
        "money_residual_failures": sum(
            certificate["money_conservation"]["residual"] != "0.00"
            for certificate in certificates
        ),
        "scope_boundary": "Measures reconciliation hypotheses and abstention; it is not a production fraud benchmark.",
    }
    (output_dir / "ledgergraph_cases.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (output_dir / "proof_certificates.json").write_text(json.dumps(certificates, indent=2), encoding="utf-8")
    (output_dir / "ledgergraph_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    table = "\n".join(
        f"| {item['system']} | {item['cases_exactly_correct']}/{item['case_count']} | {item['hypothesis_recall']} | {item['selection_precision']} | {item['false_selections']} |"
        for item in comparison
    )
    markdown = f"""# LedgerGraph adversarial evaluation

All records are synthetic. This evaluates reconciliation structure—not production fraud detection.

| System | Exact cases | Hypothesis recall | Selection precision | False selections |
|---|---:|---:|---:|---:|
{table}

- Selection threshold: 65.
- Threshold rule: {metrics['threshold_policy']}.
- Held-out cases exact: {held_out_graph['cases_exactly_correct']}/{held_out_graph['case_count']} with {held_out_graph['false_selections']} false selections.
- Grouped topology cases correct: {metrics['grouped_topology_cases_correct']}/{metrics['grouped_topology_cases']}.
- Selected certificate residual failures: {metrics['money_residual_failures']}.
"""
    (output_dir / "ledgergraph_metrics.md").write_text(markdown, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default="results/ledgergraph")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.outdir), indent=2))


if __name__ == "__main__":
    main()
