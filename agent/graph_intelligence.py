"""Explainable open-set risk signals over the reconciliation evidence graph.

LedgerGraph remains the authoritative money reconciler.  This module never
changes a match, amount, journal, or approval state.  It inspects relational
motifs around otherwise-valid bank/cashbook paths and emits review signals for
identity disagreement and graph nodes that are novel relative to the batch.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from .ledger import bank_net, citation, money


GRAPH_OOD_THRESHOLD = 50


def normalize_words(value: str | None) -> list[str]:
    cleaned = "".join(
        character.upper() if character.isalnum() else " "
        for character in (value or "")
    )
    return [token for token in cleaned.split() if len(token) >= 2]


def counterparty_similarity(narration: str, counterparty: str) -> float:
    """Coverage of approved counterparty tokens in observed bank text."""
    expected = set(normalize_words(counterparty))
    observed = set(normalize_words(narration))
    if not expected:
        return 1.0
    return len(expected & observed) / len(expected)


def economic_motif(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row.get("direction", "").lower(),
        str(money(row.get("amount") or "0")),
        " ".join(normalize_words(row.get("counterparty"))),
    )


def build_evidence_topology(sources: dict[str, Any]) -> dict[str, Any]:
    bank = sources["bank"]
    cashbook = sources.get("cashbook", [])
    references = {
        row.get("ref_no", "") for row in bank if row.get("ref_no")
    } | {
        row.get("reference", "") for row in cashbook if row.get("reference")
    }
    counterparties = {
        " ".join(normalize_words(row.get("counterparty")))
        for row in cashbook if row.get("counterparty")
    }
    approvers = {row.get("approved_by", "") for row in cashbook if row.get("approved_by")}
    # Bank->reference, cashbook->reference, cashbook->counterparty, cashbook->approver.
    edge_count = (
        sum(bool(row.get("ref_no")) for row in bank)
        + sum(bool(row.get("reference")) for row in cashbook)
        + sum(bool(row.get("counterparty")) for row in cashbook)
        + sum(bool(row.get("approved_by")) for row in cashbook)
    )
    return {
        "bank_nodes": len(bank),
        "cashbook_event_nodes": len(cashbook),
        "reference_nodes": len(references),
        "counterparty_nodes": len(counterparties),
        "approver_nodes": len(approvers),
        "edges": edge_count,
    }


def assess_graph_ood(sources: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Score every operating bank path without consulting benchmark truth."""
    bank_rows = sources["bank"]
    cashbook = sources.get("cashbook", [])
    cashbook_by_reference = {row.get("reference", ""): row for row in cashbook}
    approver_support = Counter(row.get("approved_by", "") for row in cashbook)
    motif_support = Counter(economic_motif(row) for row in cashbook)
    bank_reference_degree = Counter(row.get("ref_no", "") for row in bank_rows)
    assessments: dict[str, dict[str, Any]] = {}

    for bank in bank_rows:
        if not bank.get("transaction_type", "").startswith("OPERATING_"):
            continue
        reference = bank.get("ref_no", "")
        cashbook_row = cashbook_by_reference.get(reference)
        signals: list[dict[str, Any]] = []
        score = 0
        similarity: float | None = None
        approver_count = 0
        motif_count = 0
        evidence_path = [f"bank:{bank['bank_txn_id']}", f"reference:{reference or 'missing'}"]

        if cashbook_row is None:
            score += 100
            signals.append({
                "code": "orphan_reference_node",
                "points": 100,
                "detail": "bank reference has no linked approved cashbook event",
            })
        else:
            evidence_path.extend([
                f"cashbook:{cashbook_row.get('event_id', '')}",
                f"counterparty:{cashbook_row.get('counterparty', '')}",
                f"approver:{cashbook_row.get('approved_by', '')}",
            ])
            similarity = counterparty_similarity(
                bank.get("narration", ""), cashbook_row.get("counterparty", "")
            )
            if similarity < 0.5:
                score += 60
                signals.append({
                    "code": "identity_edge_disagreement",
                    "points": 60,
                    "detail": (
                        f"only {similarity:.0%} of approved counterparty tokens appear "
                        "in the observed bank narration"
                    ),
                })

            approver = cashbook_row.get("approved_by", "")
            approver_count = approver_support[approver]
            if len(cashbook) >= 8 and approver and approver_count == 1:
                score += 40
                signals.append({
                    "code": "novel_approver_node",
                    "points": 40,
                    "detail": "this approver appears on only one event in the evidence graph",
                })

            motif_count = motif_support[economic_motif(cashbook_row)]
            if motif_count > 1:
                score += 20
                signals.append({
                    "code": "repeated_economic_motif",
                    "points": 20,
                    "detail": (
                        f"{motif_count} cashbook events share direction, amount, and counterparty "
                        "but use different references"
                    ),
                })

            if bank_reference_degree[reference] > 1:
                score += 20
                signals.append({
                    "code": "reference_fanout",
                    "points": 20,
                    "detail": f"reference connects to {bank_reference_degree[reference]} bank entries",
                })

        assessments[bank["bank_txn_id"]] = {
            "bank_txn_id": bank["bank_txn_id"],
            "score": min(score, 100),
            "threshold": GRAPH_OOD_THRESHOLD,
            "is_graph_ood": score >= GRAPH_OOD_THRESHOLD,
            "signals": signals,
            "features": {
                "counterparty_token_coverage": similarity,
                "approver_batch_support": approver_count,
                "economic_motif_degree": motif_count,
                "bank_reference_degree": bank_reference_degree[reference],
                "signed_amount": str(bank_net(bank)),
            },
            "evidence_path": evidence_path,
            "citations": [
                citation(bank),
                *([citation(cashbook_row)] if cashbook_row else []),
            ],
        }

    flagged = [item for item in assessments.values() if item["is_graph_ood"]]
    summary = {
        "engine": "GraphShield relational open-set detector",
        "authority": "review signal only; cannot change reconciliation or post money",
        "threshold": GRAPH_OOD_THRESHOLD,
        "topology": build_evidence_topology(sources),
        "operating_paths_scored": len(assessments),
        "flagged_paths": len(flagged),
        "signal_counts": dict(Counter(
            signal["code"] for item in flagged for signal in item["signals"]
        )),
        "method": (
            "Relational nonconformity over counterparty identity, approver support, "
            "economic motif repetition, and reference fan-out. No fraud labels or LLM calls."
        ),
    }
    return assessments, summary
