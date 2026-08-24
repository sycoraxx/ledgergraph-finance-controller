"""Deterministic, bidirectional bank-entry risk detection.

The detector never reads benchmark truth. It cross-checks settlement entries
against reconciliation results and operating entries against an independent
ERP cashbook, then emits auditor-readable evidence for every flagged row.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .ledger import bank_net, citation, jsonable, load_sources, money
from .l1_search import parse_date_candidates
from .graph_intelligence import assess_graph_ood


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def inr(value: Decimal) -> str:
    return f"INR {abs(value):,.2f}"


def dates_within(left: set[str], right: set[str], days: int = 2) -> bool:
    """Allow normal bank posting lag without weakening amount/reference checks."""
    for left_value in left:
        for right_value in right:
            try:
                if abs((date.fromisoformat(left_value) - date.fromisoformat(right_value)).days) <= days:
                    return True
            except ValueError:
                continue
    return False


def risk_finding(
    row: dict[str, str],
    code: str,
    title: str,
    reason: str,
    expected_text: str,
    citations: list[str],
    severity: str,
    recommended_action: str,
    detected_at: str,
    extracted_at: str | None,
) -> dict[str, Any]:
    net = bank_net(row)
    direction = "credit" if net > 0 else "debit"
    timestamp = row.get("txn_timestamp_utc") or row.get("value_date") or row.get("txn_date")
    return {
        "bank_txn_id": row["bank_txn_id"],
        "is_dubious": True,
        "direction": direction,
        "amount": str(abs(net)),
        "transaction_timestamp_utc": timestamp,
        "source_extracted_at_utc": extracted_at,
        "anomaly_type": code,
        "risk_title": title,
        "reason": reason,
        "observed_text": (
            f"Bank {direction} of {inr(net)} at {timestamp}; "
            f"narration {row.get('narration', '')!r}; reference {row.get('ref_no', '')!r}."
        ),
        "expected_text": expected_text,
        "severity": severity,
        "recommended_action": recommended_action,
        "citations": citations,
        "detected_at_utc": detected_at,
        "status": "needs_review",
    }


def scan_bank_risk(
    data_dir: str | Path = "data",
    outdir: str | Path = "results",
    predictions: list[dict[str, Any]] | None = None,
    enable_graph_intelligence: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data_dir, outdir = Path(data_dir), Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    sources = load_sources(data_dir)
    cashbook = sources.get("cashbook", [])
    cashbook_by_reference = {row["reference"]: row for row in cashbook}
    if predictions is None:
        predictions = json.loads((outdir / "preds_agent.json").read_text(encoding="utf-8"))
    prediction_by_bank = {row["bank_txn_id"]: row for row in predictions}
    provenance_path = data_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    extracted_at = provenance.get("extracted_at_utc")
    detected_at = utc_now()
    graph_assessments, graph_summary = (
        assess_graph_ood(sources)
        if enable_graph_intelligence
        else ({}, {
            "engine": "disabled comparator",
            "authority": "review signal only",
            "threshold": None,
            "topology": {},
            "operating_paths_scored": 0,
            "flagged_paths": 0,
            "signal_counts": {},
            "method": "Graph intelligence disabled for baseline comparison.",
        })
    )

    assessments: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    seen_references: set[str] = set()
    previous_balance: Decimal | None = None

    for row in sources["bank"]:
        net = bank_net(row)
        direction = "credit" if net > 0 else "debit" if net < 0 else "zero"
        reference = row.get("ref_no", "")
        transaction_type = row.get("transaction_type", "")
        graph_assessment = graph_assessments.get(row["bank_txn_id"])
        finding = None
        graph_promoted = False

        debit = money(row.get("debit") or "0")
        credit = money(row.get("credit") or "0")
        if net == 0 or (debit > 0 and credit > 0) or debit < 0 or credit < 0:
            finding = risk_finding(
                row, "malformed_sides", "Invalid debit/credit representation",
                "The row does not contain exactly one positive debit or credit value.",
                "A valid bank row must have one positive side and a zero or blank opposite side.",
                [citation(row)], "critical", "Quarantine the row and request a corrected bank export.",
                detected_at, extracted_at,
            )

        observed_balance = money(row.get("balance") or "0")
        if previous_balance is not None:
            expected_balance = money(previous_balance + credit - debit)
            if observed_balance != expected_balance and finding is None:
                finding = risk_finding(
                    row, "balance_rollforward_mismatch", "Bank balance does not roll forward",
                    f"Reported balance differs from the prior balance plus this row by {inr(observed_balance - expected_balance)}.",
                    f"Expected closing balance {inr(expected_balance)} from the preceding statement row.",
                    [citation(row)], "critical", "Stop the import and obtain a complete, untampered statement.",
                    detected_at, extracted_at,
                )
        previous_balance = observed_balance

        if finding is None and transaction_type == "PAYMENT_GATEWAY_SETTLEMENT":
            prediction = prediction_by_bank.get(row["bank_txn_id"])
            if prediction is None or prediction.get("decision") != "matched":
                finding = risk_finding(
                    row, "unmatched_settlement", "Settlement has no unique source match",
                    "The bank entry could not be tied uniquely to a Razorpay settlement batch.",
                    "A settlement must agree on signed amount and deterministic reference/date evidence.",
                    [citation(row)], "high", "Hold posting and investigate the settlement export and bank reference.",
                    detected_at, extracted_at,
                )
            elif prediction.get("component_status") == "exception":
                issues = prediction.get("component_issues", [])
                issue_text = "; ".join(item["reason"] for item in issues)
                issue_citations = [item["citation"] for item in issues]
                finding = risk_finding(
                    row, "unattributed_settlement_component", "Settlement contains unsupported money",
                    f"The bank amount matches a settlement, but its components do not close: {issue_text}.",
                    "Every payment, refund, dispute, fee, tax, and adjustment must have independent source evidence.",
                    [citation(row), *issue_citations], "high",
                    "Keep the settlement out of the ledger until every component is attributed.",
                    detected_at, extracted_at,
                )

        if finding is None and transaction_type != "PAYMENT_GATEWAY_SETTLEMENT":
            expected = cashbook_by_reference.get(reference)
            if reference and reference in seen_references:
                finding = risk_finding(
                    row, "duplicate_reference", f"Duplicate operating {direction}",
                    "This bank reference already appeared in an earlier statement row.",
                    "Each approved cashbook reference may clear the bank only once.",
                    [citation(row), citation(expected)] if expected else [citation(row)],
                    "high" if direction == "debit" else "medium",
                    "Block automatic posting and confirm whether the bank duplicated the transaction.",
                    detected_at, extracted_at,
                )
            elif expected is None:
                finding = risk_finding(
                    row, "unsupported_transaction", f"Unsupported operating {direction}",
                    "No approved ERP cashbook event carries this bank reference.",
                    "An operating bank transaction must be backed by an approved cashbook event.",
                    [citation(row)], "critical" if direction == "debit" else "high",
                    "Escalate to treasury and verify the counterparty before recording the entry.",
                    detected_at, extracted_at,
                )
            else:
                expected_amount = money(expected["amount"])
                expected_direction = expected["direction"]
                bank_dates = parse_date_candidates(row.get("value_date"))
                expected_dates = parse_date_candidates(expected.get("value_date"))
                source_citations = [citation(row), citation(expected)]
                if direction != expected_direction:
                    finding = risk_finding(
                        row, "direction_mismatch", "Debit/credit direction contradicts the cashbook",
                        f"The bank reports a {direction}, while the approved cashbook event is a {expected_direction}.",
                        f"Cashbook {expected['event_id']} expects a {expected_direction} of {inr(expected_amount)}.",
                        source_citations, "critical", "Do not post; obtain bank and ERP owner confirmation.",
                        detected_at, extracted_at,
                    )
                elif abs(net) != expected_amount:
                    difference = abs(abs(net) - expected_amount)
                    finding = risk_finding(
                        row, "amount_mismatch", f"Operating {direction} amount differs from approval",
                        f"The bank amount differs from the approved cashbook amount by {inr(difference)}.",
                        (
                            f"Cashbook {expected['event_id']} approves {inr(expected_amount)} for "
                            f"{expected['counterparty']} ({expected['purpose']})."
                        ),
                        source_citations, "high", "Hold the difference and reconcile it with the cashbook owner.",
                        detected_at, extracted_at,
                    )
                elif not dates_within(bank_dates, expected_dates):
                    finding = risk_finding(
                        row, "date_mismatch", f"Operating {direction} cleared outside its approved date",
                        "The bank value date does not agree with the cashbook event date.",
                        f"Cashbook {expected['event_id']} expects value date {expected['value_date']}.",
                        source_citations, "medium", "Confirm the bank processing date before posting.",
                        detected_at, extracted_at,
                    )
            if reference:
                seen_references.add(reference)

        if finding is None and graph_assessment and graph_assessment["is_graph_ood"]:
            signal_codes = {item["code"] for item in graph_assessment["signals"]}
            if "identity_edge_disagreement" in signal_codes:
                title = "Observed beneficiary breaks the approved identity edge"
                reason = (
                    "The bank entry balances and its reference is approved, but the observed "
                    "beneficiary text does not agree with the linked cashbook counterparty."
                )
                action = "Verify beneficiary/account ownership independently before posting."
            elif {"novel_approver_node", "repeated_economic_motif"} <= signal_codes:
                title = "Novel approver completes a repeated economic motif"
                reason = (
                    "The entry is arithmetically valid, but a previously unseen approver backs "
                    "a repeated direction/amount/counterparty pattern under a new reference."
                )
                action = "Escalate for segregation-of-duty and approver-identity verification."
            else:
                title = "Evidence path is out of distribution"
                reason = "; ".join(item["detail"] for item in graph_assessment["signals"])
                action = "Review the novel graph nodes and edges before accepting the entry."
            finding = risk_finding(
                row,
                "graph_ood_anomaly",
                title,
                reason,
                "A normal evidence path should preserve counterparty identity and use established approval motifs.",
                graph_assessment["citations"],
                "critical" if graph_assessment["score"] >= 60 else "high",
                action,
                detected_at,
                extracted_at,
            )
            graph_promoted = True

        assessment = finding or {
            "bank_txn_id": row["bank_txn_id"],
            "is_dubious": False,
            "direction": direction,
            "amount": str(abs(net)),
            "transaction_timestamp_utc": row.get("txn_timestamp_utc"),
            "source_extracted_at_utc": extracted_at,
            "anomaly_type": "none",
            "risk_title": "Evidence checks passed",
            "reason": "The transaction agrees with its independent settlement or cashbook evidence.",
            "observed_text": (
                f"Bank {direction} of {inr(net)} at {row.get('txn_timestamp_utc')}; "
                f"reference {reference!r}."
            ),
            "expected_text": "Independent source evidence agrees on direction, amount, date, and reference.",
            "severity": "none",
            "recommended_action": "No risk intervention required.",
            "citations": [citation(row)],
            "detected_at_utc": detected_at,
            "status": "clear",
        }
        assessment["graph_ood"] = graph_assessment or {
            "score": 0,
            "threshold": graph_summary.get("threshold"),
            "is_graph_ood": False,
            "signals": [],
            "features": {},
            "evidence_path": [],
            "citations": [],
        }
        assessment["risk_engine"] = (
            "GraphShield relational open-set detector"
            if graph_promoted
            else "deterministic evidence controls + GraphShield corroboration"
            if graph_assessment and graph_assessment["is_graph_ood"]
            else "deterministic evidence controls"
        )
        assessments.append(assessment)
        if assessment["is_dubious"]:
            findings.append(assessment)

    (outdir / "risk_assessments.json").write_text(
        json.dumps(jsonable(assessments), indent=2), encoding="utf-8"
    )
    (outdir / "risk_findings.json").write_text(
        json.dumps(jsonable(findings), indent=2), encoding="utf-8"
    )
    (outdir / "graph_ood_assessments.json").write_text(
        json.dumps(jsonable(list(graph_assessments.values())), indent=2), encoding="utf-8"
    )
    (outdir / "graph_ood_summary.json").write_text(
        json.dumps(jsonable(graph_summary), indent=2), encoding="utf-8"
    )
    return assessments, findings
