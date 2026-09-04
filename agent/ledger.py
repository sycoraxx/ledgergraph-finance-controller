"""Deterministic reconciliation, verification, and journal proposal pipeline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .approval import approval_decision
from .l1_search import parse_date_candidates
from .ledger_graph import build_candidate_graph, solve_candidate_graph


CENT = Decimal("0.01")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bank_net(row: dict[str, str]) -> Decimal:
    return money(row.get("credit") or "0") - money(row.get("debit") or "0")


def money(value: str | Decimal | int) -> Decimal:
    return Decimal(value or "0").quantize(CENT, rounding=ROUND_HALF_UP)


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row_number, row in enumerate(rows, start=2):
        row["_row_number"] = str(row_number)
        row["_source"] = path.name
    return rows


def citation(row: dict[str, str]) -> str:
    return f"data/{row['_source']}:row={row['_row_number']}"


def load_sources(data_dir: str | Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    orders = read_csv(data_dir / "orders.csv")
    payments = read_csv(data_dir / "payments.csv")
    refunds = read_csv(data_dir / "refunds.csv")
    recon = read_csv(data_dir / "settlement_recon.csv")
    bank = read_csv(data_dir / "bank_statement.csv")
    cashbook_path = data_dir / "cashbook.csv"
    cashbook = read_csv(cashbook_path) if cashbook_path.exists() else []
    schedule_path = data_dir / "settlement_schedule.csv"
    schedule = read_csv(schedule_path) if schedule_path.exists() else []
    return {
        "orders": orders,
        "payments": payments,
        "refunds": refunds,
        "recon": recon,
        "bank": bank,
        "cashbook": cashbook,
        "schedule": schedule,
        "orders_by_id": {row["id"]: row for row in orders},
        "payments_by_id": {row["id"]: row for row in payments},
        "refunds_by_id": {row["id"]: row for row in refunds},
        "schedule_by_id": {row["settlement_id"]: row for row in schedule},
    }


def aggregate_settlements(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    settlements: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "rows": [],
            "net": Decimal("0.00"),
            "total_credit": Decimal("0.00"),
            "total_debit": Decimal("0.00"),
            "utr": "",
            "settled_dates": set(),
            "component_payments": [],
            "component_refunds": [],
            "component_disputes": [],
            "component_adjustments": [],
            "_declared_group_values": {
                "reconciliation_group_id": set(),
                "payout_id": set(),
                "batch_id": set(),
            },
        }
    )
    bucket = {
        "payment": "component_payments",
        "refund": "component_refunds",
        "dispute": "component_disputes",
        "adjustment": "component_adjustments",
    }

    for row in sources["recon"]:
        sid = row.get("settlement_id") or ""
        if not sid:
            continue
        settlement = settlements[sid]
        settlement["rows"].append(row)
        for field in ("reconciliation_group_id", "payout_id", "batch_id"):
            if row.get(field):
                settlement["_declared_group_values"][field].add(row[field].strip())
        settlement["utr"] = settlement["utr"] or row.get("settlement_utr", "")
        debit = money(row.get("debit") or "0")
        credit = money(row.get("credit") or "0")
        settlement["total_debit"] += debit
        settlement["total_credit"] += credit
        settlement["net"] += credit - debit
        settlement["settled_dates"] |= parse_date_candidates(row.get("settled_at"))
        component_bucket = bucket.get(row.get("transaction_entity", ""))
        if component_bucket and row.get("entity_id"):
            settlement[component_bucket].append(row["entity_id"])

    for settlement in settlements.values():
        settlement["net"] = money(settlement["net"])
        settlement["total_credit"] = money(settlement["total_credit"])
        settlement["total_debit"] = money(settlement["total_debit"])
    for settlement_id, settlement in settlements.items():
        schedule = sources.get("schedule_by_id", {}).get(settlement_id, {})
        for field in ("reconciliation_group_id", "payout_id", "batch_id"):
            if schedule.get(field):
                settlement["_declared_group_values"][field].add(schedule[field].strip())
            values = settlement["_declared_group_values"][field]
            if len(values) == 1:
                settlement[field] = next(iter(values))
            elif len(values) > 1:
                settlement[f"{field}_conflict"] = True
        settlement.pop("_declared_group_values", None)
        settlement["capture_date"] = schedule.get("capture_date", "")
        settlement["settlement_cycle"] = schedule.get("settlement_cycle", "")
        settlement["scheduled_business_days"] = schedule.get("scheduled_business_days", "")
        settlement["canonical_settled_at"] = schedule.get("settled_at", "")
        settlement["working_day_path"] = schedule.get("working_day_path", "")
        settlement["chronology_valid"] = (
            str(schedule.get("chronology_valid", "")).lower() == "true"
            if schedule else None
        )
    return dict(settlements)


def issue(row: dict[str, str], code: str, reason: str, amount: Decimal) -> dict[str, str]:
    return {
        "code": code,
        "entity_id": row.get("entity_id", ""),
        "reason": reason,
        "unresolved_amount": str(abs(money(amount))),
        "citation": citation(row),
    }


def verify_components(
    settlement: dict[str, Any], sources: dict[str, Any]
) -> dict[str, Any]:
    """Cross-check recon components against independent exports and invariants."""
    issues: list[dict[str, str]] = []
    orders = sources["orders_by_id"]
    payments = sources["payments_by_id"]
    refunds = sources["refunds_by_id"]
    seen: set[str] = set()

    for row in settlement["rows"]:
        entity_type = row.get("transaction_entity", "")
        entity_id = row.get("entity_id", "")
        amount = money(row.get("amount") or "0")
        fee = money(row.get("fee (exclusive tax)") or "0")
        tax = money(row.get("tax") or "0")
        debit = money(row.get("debit") or "0")
        credit = money(row.get("credit") or "0")

        if entity_id in seen:
            issues.append(issue(row, "duplicate_component", "duplicate entity in settlement recon", amount))
        seen.add(entity_id)

        if entity_type == "payment":
            source = payments.get(entity_id)
            if source is None:
                issues.append(issue(row, "missing_payment", "payment absent from payment export", amount))
                continue
            if money(source.get("amount") or "0") != amount:
                issues.append(issue(row, "payment_amount_mismatch", "payment amount differs across sources", amount))
            if source.get("order_id") not in orders:
                issues.append(issue(row, "missing_order", "payment references an absent order", amount))
            if money(amount - fee - tax) != credit or debit != 0:
                issues.append(issue(row, "payment_net_mismatch", "payment net does not equal amount minus fee and tax", amount))
            if money(source.get("fee") or "0") != fee or money(source.get("tax") or "0") != tax:
                issues.append(issue(row, "payment_fee_mismatch", "fee or tax differs across sources", fee + tax))

        elif entity_type == "refund":
            source = refunds.get(entity_id)
            if source is None:
                issues.append(issue(row, "missing_refund", "refund absent from refund export", amount))
                continue
            if money(source.get("amount") or "0") != amount:
                issues.append(issue(row, "refund_amount_mismatch", "refund amount differs across sources", amount))
            if source.get("payment_id") not in payments:
                issues.append(issue(row, "orphan_refund", "refund references an absent payment", amount))
            if money(amount + fee + tax) != debit or credit != 0:
                issues.append(issue(row, "refund_net_mismatch", "refund debit does not equal amount plus fee and tax", amount))

        elif entity_type == "dispute":
            if debit != amount or credit != 0 or row.get("dispute_id") != entity_id:
                issues.append(issue(row, "dispute_mismatch", "dispute fields do not agree within recon", amount))

        elif entity_type == "adjustment":
            issues.append(issue(
                row,
                "unattributed_adjustment",
                "adjustment has no attributable source record",
                debit - credit,
            ))
        else:
            issues.append(issue(row, "unknown_entity", f"unsupported recon entity {entity_type!r}", amount))

    unresolved = money(sum((money(item["unresolved_amount"]) for item in issues), Decimal("0")))
    return {
        "component_status": "reconciled" if not issues else "exception",
        "component_issues": issues,
        "unresolved_amount": unresolved,
    }


def combine_settlement_group(
    settlement_ids: list[str], settlements: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    items = [settlements[identifier] for identifier in settlement_ids]
    return {
        "rows": [row for item in items for row in item["rows"]],
        "net": money(sum((item["net"] for item in items), Decimal("0"))),
        "total_credit": money(sum((item["total_credit"] for item in items), Decimal("0"))),
        "total_debit": money(sum((item["total_debit"] for item in items), Decimal("0"))),
        "utrs": [item.get("utr", "") for item in items],
        "settled_dates": set().union(*(item.get("settled_dates", set()) for item in items)),
        "capture_dates": [item.get("capture_date", "") for item in items],
        "canonical_settled_dates": [item.get("canonical_settled_at", "") for item in items],
        "settlement_cycles": [item.get("settlement_cycle", "") for item in items],
        "scheduled_business_days": [item.get("scheduled_business_days", "") for item in items],
        "working_day_paths": [item.get("working_day_path", "") for item in items],
        "chronology_valid": all(item.get("chronology_valid") is True for item in items),
        "component_payments": [value for item in items for value in item["component_payments"]],
        "component_refunds": [value for item in items for value in item["component_refunds"]],
        "component_disputes": [value for item in items for value in item["component_disputes"]],
        "component_adjustments": [value for item in items for value in item["component_adjustments"]],
    }


def build_group_journal(
    bank_rows: list[dict[str, str]],
    settlement_ids: list[str],
    settlement: dict[str, Any],
) -> dict[str, Any]:
    """Build one atomic double-entry proposal for a selected graph hyperedge."""
    bank_credit = money(sum((bank_net(row) for row in bank_rows), Decimal("0")))
    payment_gross = payment_fees = payment_tax = Decimal("0")
    refunds = refund_fees = refund_tax = disputes = Decimal("0")

    for row in settlement["rows"]:
        entity_type = row.get("transaction_entity")
        amount = money(row.get("amount") or "0")
        fee = money(row.get("fee (exclusive tax)") or "0")
        tax = money(row.get("tax") or "0")
        if entity_type == "payment":
            payment_gross += amount
            payment_fees += fee
            payment_tax += tax
        elif entity_type == "refund":
            refunds += amount
            refund_fees += fee
            refund_tax += tax
        elif entity_type == "dispute":
            disputes += amount

    entries = []
    if bank_credit > 0:
        entries.append({"account": "Bank", "debit": bank_credit, "credit": Decimal("0")})
    elif bank_credit < 0:
        entries.append({"account": "Bank", "debit": Decimal("0"), "credit": abs(bank_credit)})

    debit_accounts = (
        ("Payment Processing Fees", payment_fees + refund_fees),
        ("Input GST", payment_tax + refund_tax),
        ("Refunds and Returns", refunds),
        ("Chargeback Losses", disputes),
    )
    for account, amount in debit_accounts:
        amount = money(amount)
        if amount:
            entries.append({"account": account, "debit": amount, "credit": Decimal("0")})
    if payment_gross:
        entries.append({"account": "Razorpay Sales Clearing", "debit": Decimal("0"), "credit": money(payment_gross)})

    total_debit = money(sum((entry["debit"] for entry in entries), Decimal("0")))
    total_credit = money(sum((entry["credit"] for entry in entries), Decimal("0")))
    bank_ids = [row["bank_txn_id"] for row in bank_rows]
    proposal_key = f"{'+'.join(bank_ids)}|{'+'.join(settlement_ids)}|{bank_credit}"
    return {
        "proposal_id": "jrn_" + hashlib.sha256(proposal_key.encode()).hexdigest()[:16],
        "bank_txn_id": bank_ids[0],
        "bank_txn_ids": bank_ids,
        "settlement_id": settlement_ids[0],
        "settlement_ids": settlement_ids,
        "topology": (
            "1:1" if len(bank_ids) == 1 and len(settlement_ids) == 1
            else "1:N" if len(bank_ids) == 1
            else "N:1" if len(settlement_ids) == 1
            else "N:M"
        ),
        "entries": jsonable(entries),
        "total_debit": str(total_debit),
        "total_credit": str(total_credit),
        "balanced": total_debit == total_credit,
        "posting_status": "not_posted",
    }


def build_journal(
    bank_row: dict[str, str], settlement_id: str, settlement: dict[str, Any]
) -> dict[str, Any]:
    """Backward-compatible wrapper for a one-to-one journal proposal."""
    return build_group_journal([bank_row], [settlement_id], settlement)


def run_pipeline(data_dir: str | Path = "data", outdir: str | Path = "results") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data_dir, outdir = Path(data_dir), Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    sources = load_sources(data_dir)
    settlements = aggregate_settlements(sources)
    predictions: list[dict[str, Any]] = []
    journals: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    settlement_bank_rows = [
        row for row in sources["bank"]
        if not row.get("transaction_type")
        or row.get("transaction_type") == "PAYMENT_GATEWAY_SETTLEMENT"
    ]
    candidate_graph = build_candidate_graph(
        settlement_bank_rows, settlements, max_group_size=2
    )
    graph_solution = solve_candidate_graph(candidate_graph)
    bank_rows_by_id = {row["bank_txn_id"]: row for row in settlement_bank_rows}
    selected_by_bank = {
        bank_id: candidate
        for candidate in graph_solution["selected"]
        for bank_id in candidate["bank_ids"]
    }
    certificates_by_candidate = {
        certificate["candidate_id"]: certificate
        for certificate in graph_solution["certificates"]
    }
    audit.append({
        "event": "ledgergraph_global_solve",
        "at": utc_now(),
        "solver": graph_solution["solver"],
        "solver_policy": graph_solution["solver_policy"],
        "candidate_count": graph_solution["candidate_count"],
        "selectable_candidate_count": graph_solution["selectable_candidate_count"],
        "selected_candidate_count": graph_solution["selected_candidate_count"],
        "abstained_bank_count": len(graph_solution["abstained_bank_ids"]),
        "candidate_generation": graph_solution["candidate_generation"],
        "all_components_proven": graph_solution["all_components_proven"],
        "component_statuses": [item["status"] for item in graph_solution["components"]],
        "constraints": graph_solution["global_constraints"],
    })

    candidate_bundles: dict[str, dict[str, Any]] = {}
    for candidate in graph_solution["selected"]:
        candidate_key = candidate["candidate_id"]
        certificate = certificates_by_candidate[candidate_key]
        group_bank_rows = [bank_rows_by_id[identifier] for identifier in candidate["bank_ids"]]
        group_settlement = combine_settlement_group(candidate["settlement_ids"], settlements)
        verification = verify_components(group_settlement, sources)
        journal = (
            build_group_journal(group_bank_rows, candidate["settlement_ids"], group_settlement)
            if verification["component_status"] == "reconciled"
            else None
        )
        group_bank_total = money(sum((bank_net(row) for row in group_bank_rows), Decimal("0")))
        policy = approval_decision(
            confidence=certificate["confidence"],
            component_status=verification["component_status"],
            bank_credit=group_bank_total,
            journal_balanced=bool(journal and journal["balanced"]),
        )
        if journal:
            journal["approval"] = policy
            journals.append(journal)
        group_citations = (
            [citation(row) for row in group_bank_rows]
            + [citation(row) for row in group_settlement["rows"]]
        )
        match_reason = (
            f"globally selected atomic {candidate['topology']} reconciliation group at "
            f"evidence score {candidate['evidence_score']}; signed group residual is INR 0.00 "
            "and every bank and settlement node is used once"
        )
        if verification["component_status"] == "exception":
            match_reason += "; component exception: " + "; ".join(
                item["reason"] for item in verification["component_issues"]
            )
        candidate_bundles[candidate_key] = {
            "certificate": certificate,
            "settlement": group_settlement,
            "verification": verification,
            "journal": journal,
            "policy": policy,
            "citations": group_citations,
            "reason": match_reason,
        }
        audit.extend([
            {
                "event": "reconciliation_group_selected",
                "at": utc_now(),
                "candidate_id": candidate_key,
                "topology": candidate["topology"],
                "bank_txn_ids": candidate["bank_ids"],
                "settlement_ids": candidate["settlement_ids"],
                "evidence_score": candidate["evidence_score"],
                "money_residual": candidate["residual"],
                "settlement_cycles": group_settlement["settlement_cycles"],
                "chronology_valid": group_settlement["chronology_valid"],
                "match_certificate_id": certificate["certificate_id"],
            },
            {
                "event": "component_group_verification",
                "at": utc_now(),
                "candidate_id": candidate_key,
                "topology": candidate["topology"],
                "status": verification["component_status"],
                "issues": verification["component_issues"],
            },
            {
                "event": "journal_group_policy",
                "at": utc_now(),
                "candidate_id": candidate_key,
                "proposal_id": journal["proposal_id"] if journal else None,
                "balanced": journal["balanced"] if journal else False,
                "decision": policy,
            },
        ])

    for bank_row in settlement_bank_rows:
        bank_id = bank_row["bank_txn_id"]
        candidate = selected_by_bank.get(bank_id)
        if candidate is None:
            bank_node = f"B:{bank_id}"
            generation_unsafe = bank_node in set(
                graph_solution["candidate_generation"].get("unsafe_nodes", [])
            )
            unresolved_component = next(
                (
                    component for component in graph_solution["components"]
                    if bank_node in component.get("node_ids", []) and component["exhausted"]
                ),
                None,
            )
            if generation_unsafe:
                abstention_reason = (
                    "candidate generation was truncated for this money-event neighbourhood; "
                    "LedgerGraph failed closed rather than optimize over an incomplete hypothesis set"
                )
            elif unresolved_component:
                abstention_reason = (
                    f"CP-SAT component status {unresolved_component['status']} did not prove a safe optimum; "
                    "LedgerGraph failed closed"
                )
            else:
                abstention_reason = (
                    "no unambiguous, money-conserving candidate above the evidence threshold"
                )
            prediction = {
                "bank_txn_id": bank_id,
                "bank_txn_ids": [bank_id],
                "decision": "escalated",
                "settlement_id": None,
                "settlement_ids": [],
                "topology": "unresolved",
                "component_status": "not_evaluated",
                "component_payments": [],
                "component_refunds": [],
                "component_disputes": [],
                "component_adjustments": [],
                "confidence": 0.0,
                "layer": "LedgerGraph-global",
                "reason": f"global solver abstained: {abstention_reason}",
                "citations": [citation(bank_row)],
                "unresolved_amount": str(abs(bank_net(bank_row))),
                "transaction_timestamp_utc": bank_row.get("txn_timestamp_utc"),
                "direction": "credit" if bank_net(bank_row) > 0 else "debit",
                "bank_amount": str(abs(bank_net(bank_row))),
                "bank_narration": bank_row.get("narration", ""),
            }
            predictions.append(prediction)
            audit.append({"event": "bank_match_escalated", "at": utc_now(), "bank_txn_id": bank_id, "reason": prediction["reason"]})
            continue

        sid = candidate["settlement_ids"][0]
        bundle = candidate_bundles[candidate["candidate_id"]]
        settlement = bundle["settlement"]
        certificate = bundle["certificate"]
        verification = bundle["verification"]
        journal = bundle["journal"]
        policy = bundle["policy"]
        prediction = {
            "bank_txn_id": bank_id,
            "bank_txn_ids": candidate["bank_ids"],
            "decision": "matched",
            "bank_match_status": "matched",
            "settlement_id": sid,
            "settlement_ids": candidate["settlement_ids"],
            "topology": candidate["topology"],
            "reconciliation_group_id": candidate["candidate_id"],
            "component_status": verification["component_status"],
            "component_payments": settlement["component_payments"],
            "component_refunds": settlement["component_refunds"],
            "component_disputes": settlement["component_disputes"],
            "component_adjustments": settlement["component_adjustments"],
            "confidence": certificate["confidence"],
            "layer": "LedgerGraph-global",
            "reason": bundle["reason"],
            "evidence_score": candidate["evidence_score"],
            "match_certificate_id": certificate["certificate_id"],
            "selection_threshold": graph_solution["selection_threshold"],
            "score_breakdown": candidate["features"],
            "citations": bundle["citations"],
            "component_issues": verification["component_issues"],
            "unresolved_amount": str(verification["unresolved_amount"]),
            "journal_proposal_id": journal["proposal_id"] if journal else None,
            "approval_status": policy["status"],
            "transaction_timestamp_utc": bank_row.get("txn_timestamp_utc"),
            "direction": "credit" if bank_net(bank_row) > 0 else "debit",
            "bank_amount": str(abs(bank_net(bank_row))),
            "bank_narration": bank_row.get("narration", ""),
            "capture_dates": settlement["capture_dates"],
            "settled_dates": settlement["canonical_settled_dates"],
            "settlement_cycles": settlement["settlement_cycles"],
            "working_day_paths": settlement["working_day_paths"],
            "chronology_valid": settlement["chronology_valid"],
        }
        predictions.append(prediction)
        audit.extend([
            {
                "event": "bank_match",
                "at": utc_now(),
                "bank_txn_id": bank_id,
                "settlement_id": sid,
                "bank_txn_ids": candidate["bank_ids"],
                "settlement_ids": candidate["settlement_ids"],
                "topology": candidate["topology"],
                "layer": "LedgerGraph-global",
                "confidence": certificate["confidence"],
                "reason": bundle["reason"],
                "match_certificate_id": certificate["certificate_id"],
                "evidence_score": candidate["evidence_score"],
            },
        ])

    (outdir / "preds_agent.json").write_text(json.dumps(jsonable(predictions), indent=2), encoding="utf-8")
    (outdir / "journal_proposals.json").write_text(json.dumps(jsonable(journals), indent=2), encoding="utf-8")
    (outdir / "ledgergraph.json").write_text(
        json.dumps(jsonable({"graph": candidate_graph, "solution": graph_solution}), indent=2),
        encoding="utf-8",
    )
    (outdir / "match_certificates.json").write_text(
        json.dumps(jsonable(graph_solution["certificates"]), indent=2),
        encoding="utf-8",
    )
    with (outdir / "audit.jsonl").open("w", encoding="utf-8") as handle:
        for event in audit:
            handle.write(json.dumps(jsonable(event)) + "\n")
    return predictions, journals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    parser.add_argument("--outdir", default="results")
    args = parser.parse_args()
    predictions, journals = run_pipeline(args.data, args.outdir)
    matched = sum(item["decision"] == "matched" for item in predictions)
    reconciled = sum(item.get("component_status") == "reconciled" for item in predictions)
    review = sum(item.get("approval_status") == "needs_review" for item in predictions)
    print(f"bank records       {len(predictions)}")
    print(f"bank matched       {matched}")
    print(f"component closed   {reconciled}")
    print(f"needs review       {review}")
    print("money actions      0 (journal proposals only)")


if __name__ == "__main__":
    main()
