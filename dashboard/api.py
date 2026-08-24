"""FastAPI surface for the LangGraph controller dashboard."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.qa import answer_question
from agent.scenario_catalog import scenario_catalog, scenario_context
from agent.workflow import REQUIRED_SOURCES, WorkflowRuntime, file_sha256, row_count
from eval.score import grade, per_tier, summarise
from integrations.razorpay_feed import RazorpayFeedError, feed_status, sync_feed


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
runtime = WorkflowRuntime(ROOT)

app = FastAPI(
    title="Finance Controller API",
    version="1.0.0",
    description="Local, evidence-first orchestration for Razorpay settlement reconciliation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(default="local-reviewer", min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    use_model: bool = True


class RazorpaySyncRequest(BaseModel):
    max_records: int = Field(default=1000, ge=1, le=10000)


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def inr(value: Decimal | str | int) -> str:
    amount = Decimal(str(value))
    return f"₹{amount:,.2f}"


def current_metrics(predictions: list[dict[str, Any]], truth: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rows = grade(truth, predictions)
    return summarise(rows), per_tier(rows), rows


def source_summary() -> list[dict[str, Any]]:
    provenance = load_json(DATA / "provenance.json", {})
    provenance_by_name = {
        item["name"]: item for item in provenance.get("sources", [])
    }
    output = []
    for name in REQUIRED_SOURCES:
        path = DATA / name
        if path.exists():
            source = provenance_by_name.get(name, {})
            output.append({
                "name": name,
                "rows": row_count(path),
                "sha256": file_sha256(path)[:12],
                "status": "verified",
                "modified_at_utc": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "extracted_at_utc": source.get(
                    "extracted_at_utc", provenance.get("extracted_at_utc")
                ),
                "coverage_start": source.get(
                    "coverage_start", provenance.get("coverage_start")
                ),
                "coverage_end": source.get(
                    "coverage_end", provenance.get("coverage_end")
                ),
                "source_system": source.get("source_system", "Local artifact"),
            })
    return output


def total_bank_credit() -> Decimal:
    total = Decimal("0")
    with (DATA / "bank_statement.csv").open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            total += Decimal(row.get("credit") or "0")
    return total


def bank_activity() -> dict[str, Any]:
    credit = debit = Decimal("0")
    credits = debits = 0
    with (DATA / "bank_statement.csv").open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row_credit = Decimal(row.get("credit") or "0")
        row_debit = Decimal(row.get("debit") or "0")
        credit += row_credit
        debit += row_debit
        credits += row_credit > 0
        debits += row_debit > 0
    return {
        "entries": len(rows), "credits": credits, "debits": debits,
        "credit_value": credit, "debit_value": debit,
    }


def pipeline_stages(latest: dict[str, Any]) -> list[dict[str, Any]]:
    reached = latest.get("current_stage", "human_approval") if latest else "human_approval"
    order = ["source_validation", "deterministic_reconciliation", "evaluation", "human_approval"]
    current = order.index(reached) if reached in order else len(order) - 1
    labels = [
        ("Sources", "3 simulated systems"),
        ("Reconcile", "LedgerGraph global solve"),
        ("Verify", "Metrics + honest misses"),
        ("Approve", "Human-only sandbox gate"),
    ]
    return [
        {
            "step": f"{index + 1:02}",
            "name": label,
            "note": note,
            "status": "complete" if index < current else "active" if index == current else "pending",
        }
        for index, (label, note) in enumerate(labels)
    ]


def dashboard_overview() -> dict[str, Any]:
    predictions = load_json(RESULTS / "preds_agent.json", [])
    journals = load_json(RESULTS / "journal_proposals.json", [])
    truth = load_json(DATA / "ground_truth.json", [])
    metrics, tiers, graded = current_metrics(predictions, truth) if predictions and truth else ({}, [], [])
    risk_metrics = load_json(RESULTS / "risk" / "risk_metrics.json", {})
    robustness = load_json(RESULTS / "robustness" / "robustness_metrics.json", {})
    challenge = load_json(RESULTS / "challenge" / "challenge_metrics.json", {})
    fraud_holdout = load_json(
        RESULTS / "fraud_holdout" / "fraud_holdout_metrics.json", {}
    )
    ledgergraph_artifact = load_json(RESULTS / "ledgergraph.json", {})
    ledgergraph_metrics = load_json(
        RESULTS / "ledgergraph" / "ledgergraph_metrics.json", {}
    )
    ledgergraph_cases = load_json(
        RESULTS / "ledgergraph" / "ledgergraph_cases.json", []
    )
    graph_ood_summary = load_json(RESULTS / "graph_ood_summary.json", {})
    if risk_metrics:
        metrics = {
            **metrics,
            "risk_precision": risk_metrics.get("precision"),
            "risk_recall": risk_metrics.get("recall"),
            "risk_specificity": risk_metrics.get("specificity"),
            "risk_f1": risk_metrics.get("f1"),
            "risk_false_positives": risk_metrics.get("false_positives"),
            "risk_false_negatives": risk_metrics.get("false_negatives"),
            "risk_credit_recall": risk_metrics.get("by_direction", {}).get("credit", {}).get("recall"),
            "risk_debit_recall": risk_metrics.get("by_direction", {}).get("debit", {}).get("recall"),
            "risk_safety_gate_passed": risk_metrics.get("safety_gate_passed"),
            "challenge_precision": challenge.get("precision"),
            "challenge_recall": challenge.get("recall"),
            "challenge_false_positives": challenge.get("false_positives"),
            "challenge_false_negatives": challenge.get("false_negatives"),
        }
    tier_by_bank = {item["bank_txn_id"]: item["tier"] for item in truth}
    graded_by_bank = {item["bank_txn_id"]: item for item in graded}
    ledger = runtime.ledger_state()

    review = []
    for item in predictions:
        if not (
            item["decision"] == "escalated"
            or item.get("component_status") == "exception"
            or item.get("approval_status") == "needs_review"
        ):
            continue
        issues = item.get("component_issues", [])
        review.append({
            "bank_txn_id": item["bank_txn_id"],
            "settlement_id": item.get("settlement_id"),
            "tier": tier_by_bank.get(item["bank_txn_id"]),
            "reason": issues[0]["reason"] if issues else item["reason"],
            "detail": item["reason"],
            "component_status": item.get("component_status"),
            "approval_status": item.get("approval_status"),
            "unresolved_amount": item.get("unresolved_amount", "0.00"),
            "unresolved_amount_display": inr(item.get("unresolved_amount", "0.00")),
            "confidence": item.get("confidence", 0),
            "citations": item.get("citations", []),
            "issues": issues,
            "is_true_refusal": graded_by_bank.get(item["bank_txn_id"], {}).get("component_outcome") == "true_component_refusal",
        })

    approval_queue = []
    for item in journals:
        external = ledger.get(item["proposal_id"], {})
        approval_queue.append({
            **item,
            "display_amount": inr(item["total_debit"]),
            "workflow_status": external.get("status", item["approval"]["status"]),
            "ledger_entry_id": external.get("ledger_entry_id"),
            "reviewer": external.get("reviewer"),
            "decided_at": external.get("decided_at"),
        })

    raw_audit = []
    audit_path = RESULTS / "audit.jsonl"
    if audit_path.exists():
        raw_audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line]
    audit = runtime.approval_events() + list(reversed(raw_audit[-24:]))
    latest = load_json(RESULTS / "workflow_latest.json", {})
    provenance = load_json(DATA / "provenance.json", {})
    activity = bank_activity()
    risk_findings = load_json(RESULTS / "risk_findings.json", [])
    risk_findings = [
        {
            **item,
            "amount_display": inr(item["amount"]),
            "scenario_context": scenario_context(item.get("anomaly_type", "")),
        }
        for item in risk_findings
    ]

    rows_by_source = {item["name"]: item["rows"] for item in source_summary()}
    posted = sum(item["workflow_status"] == "posted_to_sandbox_ledger" for item in approval_queue)
    rejected = sum(item["workflow_status"] == "rejected" for item in approval_queue)
    graph = ledgergraph_artifact.get("graph", {})
    graph_solution = ledgergraph_artifact.get("solution", {})
    selected_ids = {
        item.get("candidate_id") for item in graph_solution.get("selected", [])
    }
    certificates_by_candidate = {
        item.get("candidate_id"): item
        for item in graph_solution.get("certificates", [])
    }

    def decorate_graph_edge(item: dict[str, Any]) -> dict[str, Any]:
        is_selected = item.get("candidate_id") in selected_ids
        blockers = list(item.get("blockers", []))
        if is_selected:
            rejection_stage = "globally_selected"
        elif not item.get("eligible"):
            rejection_stage = "hard_gate_rejected"
        elif item.get("evidence_score", 0) < graph_solution.get("selection_threshold", 65):
            rejection_stage = "threshold_rejected"
            blockers.append("selection_threshold_not_met")
        else:
            rejection_stage = "global_solver_rejected"
            blockers.append("lower_global_objective_or_one_use_conflict")
        return {
            **item,
            "selected": is_selected,
            "rejection_stage": rejection_stage,
            "blockers": blockers,
            "certificate": certificates_by_candidate.get(item.get("candidate_id")),
        }

    selected_edges = [
        decorate_graph_edge(item)
        for item in graph_solution.get("selected", [])[:8]
    ]
    mesh_edges = [
        decorate_graph_edge(item)
        for item in graph.get("candidates", [])
    ]
    rejected_examples = [
        decorate_graph_edge(item) for item in graph.get("candidates", [])
        if item.get("candidate_id") not in selected_ids
    ][:20]
    bank_nodes_by_id = {
        item.get("id"): item for item in graph.get("bank_nodes", [])
    }
    settlement_nodes_by_id = {
        item.get("id"): item for item in graph.get("settlement_nodes", [])
    }
    settlement_nodes = graph.get("settlement_nodes", [])
    cycle_counts = {
        cycle: sum(item.get("settlement_cycle") == cycle for item in settlement_nodes)
        for cycle in ("T+1", "T+2")
    }
    chronology_violations = sum(
        item.get("chronology_valid") is False for item in settlement_nodes
    )
    thursday_t2_example = next((
        {
            "settlement_id": item.get("id"),
            "capture_date": item.get("capture_date"),
            "settled_at": item.get("settled_at"),
            "working_day_path": item.get("working_day_path"),
        }
        for item in settlement_nodes
        if item.get("settlement_cycle") == "T+2"
        and item.get("capture_date")
        and datetime.fromisoformat(item["capture_date"]).weekday() == 3
    ), None)
    candidates_by_bank: dict[str, list[dict[str, Any]]] = {}
    for candidate in graph.get("candidates", []):
        for bank_id in candidate.get("bank_ids", []):
            candidates_by_bank.setdefault(bank_id, []).append(candidate)
    contested_groups = []
    for bank_id, candidates in candidates_by_bank.items():
        if len(candidates) < 2:
            continue
        decorated = [
            {
                **decorate_graph_edge(candidate),
                "settlement_nodes": [
                    settlement_nodes_by_id.get(identifier, {"id": identifier})
                    for identifier in candidate.get("settlement_ids", [])
                ],
            }
            for candidate in candidates
        ]
        contested_groups.append({
            "bank_node": bank_nodes_by_id.get(bank_id, {"id": bank_id}),
            "candidates": sorted(
                decorated,
                key=lambda item: (
                    not item["selected"], -item.get("evidence_score", 0)
                ),
            ),
        })
    contested_groups.sort(
        key=lambda item: (-len(item["candidates"]), item["bank_node"].get("id", ""))
    )
    return {
        "generated_at": latest.get("completed_at"),
        "runtime": {
            "orchestrator": "LangGraph",
            "money_engine": "Deterministic Python",
            "language_model": "Qwen 3.5 4B Q4_K_M · HF GGUF",
            "ledger": "Local sandbox SQLite",
            "mode": "local",
        },
        "headline": {
            "bank_value": str(total_bank_credit()),
            "bank_value_display": inr(total_bank_credit()),
            "bank_records": len(predictions),
            "bank_entries": activity["entries"],
            "bank_credits": activity["credits"],
            "bank_debits": activity["debits"],
            "bank_debit_value": str(activity["debit_value"]),
            "bank_debit_value_display": inr(activity["debit_value"]),
            "orders": rows_by_source.get("orders.csv", 0),
            "recon_rows": rows_by_source.get("settlement_recon.csv", 0),
        },
        "metrics": metrics,
        "tiers": tiers,
        "sources": source_summary(),
        "stages": pipeline_stages(latest),
        "exceptions": review,
        "risk_findings": risk_findings,
        "risk_summary": risk_metrics,
        "robustness": robustness,
        "challenge": challenge,
        "fraud_holdout": fraud_holdout,
        "scenario_catalog": scenario_catalog(),
        "ledgergraph": {
            "solver": graph_solution.get("solver"),
            "solver_policy": graph_solution.get("solver_policy"),
            "all_components_proven": graph_solution.get("all_components_proven", False),
            "component_status_counts": {
                status: sum(
                    item.get("status") == status
                    for item in graph_solution.get("components", [])
                )
                for status in sorted({
                    item.get("status", "unknown")
                    for item in graph_solution.get("components", [])
                })
            },
            "selection_threshold": graph_solution.get("selection_threshold"),
            "bank_node_count": len(graph.get("bank_nodes", [])),
            "settlement_node_count": len(graph.get("settlement_nodes", [])),
            "candidate_count": graph_solution.get("candidate_count", 0),
            "selectable_candidate_count": graph_solution.get("selectable_candidate_count", 0),
            "selected_candidate_count": graph_solution.get("selected_candidate_count", 0),
            "candidate_topology_counts": graph_solution.get("candidate_topology_counts", {}),
            "selected_topology_counts": graph_solution.get("selected_topology_counts", {}),
            "hard_gate_rejected_topology_counts": graph_solution.get("hard_gate_rejected_topology_counts", {}),
            "global_rejected_topology_counts": graph_solution.get("global_rejected_topology_counts", {}),
            "generation_rejected_topology_counts": graph_solution.get("generation_rejected_topology_counts", {}),
            "candidate_generation": graph_solution.get("candidate_generation", graph.get("candidate_generation", {})),
            "candidate_generation_unsafe_node_count": graph_solution.get("candidate_generation_unsafe_node_count", 0),
            "timing_policy": {
                "policy_label": "Synthetic T+1/T+2 · Monday-Friday working days",
                "scope_note": "Demonstration policy, not a universal Razorpay merchant contract.",
                "cycle_counts": cycle_counts,
                "chronology_violations": chronology_violations,
                "thursday_t2_example": thursday_t2_example,
            },
            "abstained_bank_count": len(graph_solution.get("abstained_bank_ids", [])),
            "rejected_candidate_count": len(rejected_examples) + max(
                0,
                len(graph.get("candidates", []))
                - len(selected_ids)
                - len(rejected_examples),
            ),
            "money_conflict_count": sum(
                "money_conservation_failed" in item.get("blockers", [])
                for item in graph.get("candidates", [])
            ),
            "contested_bank_count": len(contested_groups),
            "global_constraints": graph_solution.get("global_constraints", []),
            "selected_edges": selected_edges,
            "rejected_examples": rejected_examples,
            "contested_groups": contested_groups[:10],
            "mesh": {
                "bank_nodes": graph.get("bank_nodes", []),
                "settlement_nodes": graph.get("settlement_nodes", []),
                "edges": mesh_edges,
            },
        },
        "ledgergraph_eval": {
            **ledgergraph_metrics,
            "cases": ledgergraph_cases,
        },
        "graph_intelligence": {
            **graph_ood_summary,
            "challenge_baseline": challenge.get("baseline_without_graph", {}),
            "challenge_delta": challenge.get("graph_intelligence_delta", {}),
            "challenge_by_class": challenge.get("by_mutation_class", {}),
            "challenge_enhanced": {
                "precision": challenge.get("precision"),
                "recall": challenge.get("recall"),
                "false_positives": challenge.get("false_positives"),
                "false_negatives": challenge.get("false_negatives"),
                "recall_95_ci": challenge.get("recall_95_ci"),
            },
            "fresh_holdout": fraud_holdout,
        },
        "razorpay_feed": feed_status(),
        "provenance": {
            **provenance,
            "run_started_at_utc": latest.get("started_at"),
            "run_completed_at_utc": latest.get("completed_at"),
            "source_fingerprint": latest.get("source_fingerprint"),
        },
        "approval_queue": approval_queue,
        "approval_summary": {
            "total": len(approval_queue),
            "pending": sum(
                item["workflow_status"] == "awaiting_human_approval"
                for item in approval_queue
            ),
            "posted": posted,
            "rejected": rejected,
        },
        "audit": audit,
        "latest_run": latest,
        "architecture": {
            "nodes": ["validate", "reconcile", "measure", "review", "human gate", "sandbox post"],
            "authority": "Only deterministic code constructs or validates money. Only a human can resume a posting interrupt.",
        },
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "orchestrator": "langgraph",
        "model_backend": "huggingface-gguf/llama.cpp",
        "model_device": "CUDA0",
        "mode": "local",
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    return dashboard_overview()


@app.get("/api/razorpay/status")
def razorpay_status() -> dict[str, Any]:
    return feed_status()


@app.post("/api/razorpay/sync")
def razorpay_sync(request: RazorpaySyncRequest) -> dict[str, Any]:
    try:
        sync = sync_feed(max_records=request.max_records)
        return {"sync": sync, "overview": dashboard_overview()}
    except RazorpayFeedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs")
def start_run() -> dict[str, Any]:
    try:
        run = runtime.start_run()
        return {"run": run, "overview": dashboard_overview()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = runtime.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.post("/api/approvals/{proposal_id}")
def decide(proposal_id: str, request: DecisionRequest) -> dict[str, Any]:
    try:
        result = runtime.decide(proposal_id, request.decision, request.reviewer, request.note)
        return {"approval": result, "overview": dashboard_overview()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/qa")
def ask(request: QuestionRequest) -> dict[str, Any]:
    return {
        "question": request.question,
        "answer": answer_question(request.question, RESULTS, use_model=request.use_model),
        "mode": "qwen_grounded" if request.use_model else "deterministic_evidence",
    }
