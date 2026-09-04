"""Constrained settlement Q&A over deterministic reconciliation artifacts."""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import load_project_env
from .model_gateway import ExplanationModelClient, LocalModelUnavailable


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_settlement_summary",
            "description": "Read reconciliation evidence for one exact settlement id.",
            "parameters": {
                "type": "object",
                "properties": {"settlement_id": {"type": "string"}},
                "required": ["settlement_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bank_transaction",
            "description": "Read reconciliation evidence for one exact bank transaction id.",
            "parameters": {
                "type": "object",
                "properties": {"bank_txn_id": {"type": "string"}},
                "required": ["bank_txn_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_exceptions",
            "description": "List settlements that need human review.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics",
            "description": "Read the measured reconciliation metrics.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]


class EvidenceStore:
    def __init__(self, results_dir: str | Path = "results"):
        self.results_dir = Path(results_dir)
        self.predictions = json.loads(
            (self.results_dir / "preds_agent.json").read_text(encoding="utf-8"))
        self.journals = json.loads(
            (self.results_dir / "journal_proposals.json").read_text(encoding="utf-8"))
        risk_path = self.results_dir / "risk_assessments.json"
        findings_path = self.results_dir / "risk_findings.json"
        self.risk_assessments = json.loads(risk_path.read_text(encoding="utf-8")) if risk_path.exists() else []
        self.risk_findings = json.loads(findings_path.read_text(encoding="utf-8")) if findings_path.exists() else []
        self.by_bank = {item["bank_txn_id"]: item for item in self.predictions}
        self.by_settlement = {
            settlement_id: item
            for item in self.predictions
            for settlement_id in (item.get("settlement_ids") or [item.get("settlement_id")])
            if settlement_id
        }
        self.journal_by_settlement = {
            settlement_id: item
            for item in self.journals
            for settlement_id in (item.get("settlement_ids") or [item.get("settlement_id")])
            if settlement_id
        }
        self.journal_by_bank = {
            bank_id: item
            for item in self.journals
            for bank_id in (item.get("bank_txn_ids") or [item.get("bank_txn_id")])
            if bank_id
        }
        self.risk_by_bank = {item["bank_txn_id"]: item for item in self.risk_assessments}

    def execute(self, call: dict[str, Any]) -> dict[str, Any]:
        name, arguments = call["name"], call["arguments"]
        if name == "get_settlement_summary":
            item = self.by_settlement.get(arguments["settlement_id"])
            if not item:
                return {"found": False, "settlement_id": arguments["settlement_id"]}
            return {
                "found": True,
                "reconciliation": item,
                "journal_proposal": self.journal_by_settlement.get(arguments["settlement_id"]),
                "citations": item.get("citations", []),
            }
        if name == "get_bank_transaction":
            item = self.by_bank.get(arguments["bank_txn_id"])
            risk = self.risk_by_bank.get(arguments["bank_txn_id"])
            if not item and not risk:
                return {"found": False, "bank_txn_id": arguments["bank_txn_id"]}
            return {
                "found": True,
                "reconciliation": item,
                "risk_assessment": risk,
                "journal_proposal": self.journal_by_bank.get(arguments["bank_txn_id"]) if item else None,
                "citations": list(dict.fromkeys(
                    (item.get("citations", []) if item else [])
                    + (risk.get("citations", []) if risk else [])
                )),
            }
        if name == "list_exceptions":
            items = [
                {
                    "bank_txn_id": item["bank_txn_id"],
                    "direction": item["direction"],
                    "amount": item["amount"],
                    "transaction_timestamp_utc": item["transaction_timestamp_utc"],
                    "risk_title": item["risk_title"],
                    "reason": item["reason"],
                    "observed_text": item["observed_text"],
                    "expected_text": item["expected_text"],
                    "recommended_action": item["recommended_action"],
                    "severity": item["severity"],
                    "citations": item.get("citations", [])[:3],
                }
                for item in self.risk_findings
            ]
            return {"count": len(items), "exceptions": items}
        if name == "get_metrics":
            path = self.results_dir / "agent" / "metrics.md"
            return {
                "metrics_markdown": (
                    (path.read_text(encoding="utf-8") if path.exists() else "not generated")
                    + "\n"
                    + ((self.results_dir / "risk" / "risk_metrics.md").read_text(encoding="utf-8")
                       if (self.results_dir / "risk" / "risk_metrics.md").exists() else "")
                ),
                "citations": ["results/agent/metrics.md", "results/risk/risk_metrics.md"],
            }
        raise ValueError("tool was not allowlisted")


def validate_call(call: dict[str, Any]) -> tuple[bool, str]:
    specs = {
        "get_settlement_summary": ("settlement_id", r"setl_[A-Za-z0-9]+"),
        "get_bank_transaction": ("bank_txn_id", r"BNK\d{6}"),
        "list_exceptions": (None, None),
        "get_metrics": (None, None),
    }
    if not isinstance(call, dict) or call.get("name") not in specs:
        return False, "unknown or malformed tool"
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return False, "arguments must be an object"
    required, pattern = specs[call["name"]]
    if required is None:
        return (not arguments, "unexpected arguments" if arguments else "")
    if set(arguments) != {required}:
        return False, "arguments do not match the strict schema"
    if not re.fullmatch(pattern, str(arguments[required])):
        return False, "identifier format rejected"
    return True, ""


def deterministic_route(question: str) -> dict[str, Any] | None:
    settlement = re.search(r"\bsetl_[A-Za-z0-9]+\b", question)
    bank = re.search(r"\bBNK\d{6}\b", question, re.IGNORECASE)
    if settlement:
        return {"name": "get_settlement_summary", "arguments": {"settlement_id": settlement.group(0)}}
    if bank:
        return {"name": "get_bank_transaction", "arguments": {"bank_txn_id": bank.group(0).upper()}}
    lowered = question.lower()
    if any(word in lowered for word in ("exception", "unresolved", "review")):
        return {"name": "list_exceptions", "arguments": {}}
    if any(word in lowered for word in ("metric", "accuracy", "precision", "recall")):
        return {"name": "get_metrics", "arguments": {}}
    return None


def append_audit(results_dir: Path, event: dict[str, Any]) -> None:
    with (results_dir / "qa_audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def format_inr(value: str | int | float) -> str:
    amount = Decimal(str(value or "0"))
    return f"₹{amount:,.2f}"


def render_evidence(evidence: dict[str, Any]) -> str:
    """Render deterministic evidence concisely when the model is unavailable."""
    if "metrics_markdown" in evidence:
        return evidence["metrics_markdown"]

    if "exceptions" in evidence:
        lines = [f"{evidence['count']} records require human review:"]
        for item in evidence["exceptions"]:
            lines.append(
                f"- {item['bank_txn_id']} · {item['direction']} · "
                f"{format_inr(item['amount'])} · {item['transaction_timestamp_utc']}: "
                f"{item['risk_title']}. {item['reason']}"
            )
        return "\n".join(lines)

    if not evidence.get("found"):
        identifier = evidence.get("bank_txn_id") or evidence.get("settlement_id")
        return f"No reconciliation evidence was found for {identifier}."

    item = evidence.get("reconciliation")
    risk = evidence.get("risk_assessment")
    if item is None and risk:
        lines = [
            f"{risk['bank_txn_id']} is a {risk['direction']} of {format_inr(risk['amount'])} "
            f"at {risk['transaction_timestamp_utc']}.",
            risk["risk_title"] + ": " + risk["reason"],
            "Observed: " + risk["observed_text"],
            "Expected: " + risk["expected_text"],
            "Action: " + risk["recommended_action"],
        ]
        if risk.get("citations"):
            lines.append("Evidence: " + ", ".join(risk["citations"]) + ".")
        return "\n".join(lines)
    bank_ids = item.get("bank_txn_ids") or [item["bank_txn_id"]]
    settlement_ids = item.get("settlement_ids") or ([item["settlement_id"]] if item.get("settlement_id") else [])
    bank_id = " + ".join(bank_ids)
    settlement_id = " + ".join(settlement_ids) or "no settlement"
    payment_count = len(item.get("component_payments", []))
    refund_count = len(item.get("component_refunds", []))
    dispute_count = len(item.get("component_disputes", []))
    adjustment_count = len(item.get("component_adjustments", []))
    lines = [
        f"{bank_id} was matched to {settlement_id} as an atomic "
        f"{item.get('topology', '1:1')} reconciliation group by {item['layer']} "
        f"(confidence {float(item.get('confidence', 0)):.0%}).",
        f"The settlement contains {payment_count} payments, {refund_count} refunds, "
        f"{dispute_count} disputes, and {adjustment_count} adjustments.",
    ]

    issues = item.get("component_issues", [])
    if issues:
        lines.append("It was held for review because:")
        for component_issue in issues:
            lines.append(
                f"- {component_issue['entity_id']}: {component_issue['reason']} "
                f"({format_inr(component_issue['unresolved_amount'])}; "
                f"{component_issue['citation']})."
            )
    elif item.get("approval_status") == "needs_review":
        journal = evidence.get("journal_proposal") or {}
        blockers = journal.get("approval", {}).get("blockers", [])
        lines.append("The components reconcile, but approval policy blocked posting:")
        lines.extend(f"- {blocker}." for blocker in blockers)
    else:
        lines.append("All components reconciled successfully.")

    unresolved = item.get("unresolved_amount", "0")
    lines.append(f"Unresolved amount: {format_inr(unresolved)}.")
    if item.get("journal_proposal_id"):
        lines.append(
            f"Journal proposal: {item['journal_proposal_id']} "
            f"({item.get('approval_status', 'unknown')}; not posted)."
        )
    else:
        lines.append("No journal was proposed, so nothing can be posted.")

    bank_citation = next(
        (value for value in item.get("citations", []) if "bank_statement" in value),
        None,
    )
    issue_citations = [issue["citation"] for issue in issues]
    citations = [value for value in [bank_citation, *issue_citations] if value]
    if citations:
        lines.append("Evidence: " + ", ".join(citations) + ".")
    return "\n".join(lines)


def answer_question(
    question: str,
    results_dir: str | Path = "results",
    use_model: bool = True,
) -> str:
    load_project_env()
    results_dir = Path(results_dir)
    store = EvidenceStore(results_dir)
    client = ExplanationModelClient()
    # Routing stays deterministic. The optional model receives evidence only
    # after an allowlisted read operation has been selected and executed.
    call = deterministic_route(question)

    if call is not None:
        append_audit(results_dir, {
            "event": "deterministic_primary_route",
            "question": question,
            "call": call,
        })

    if call is None:
        return "I cannot route that question safely. Provide an exact BNK or setl identifier, or ask for metrics or exceptions."

    evidence = store.execute(call)
    if use_model:
        try:
            return client.grounded_answer(question, evidence)
        except LocalModelUnavailable as exc:
            append_audit(results_dir, {"event": "model_answer_failed", "reason": str(exc)})

    # Safe fallback: render only values already computed by deterministic code.
    note = "[Deterministic fallback: the optional AI assistant was unavailable.]\n" if use_model else ""
    return note + render_evidence(evidence)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--results", default="results")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args()
    print(answer_question(args.question, args.results, use_model=not args.no_model))


if __name__ == "__main__":
    main()
