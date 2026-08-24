"""LangGraph orchestration around the deterministic finance controller.

The graph controls sequencing, persistence, failure routing, and human gates.
All reconciliation, verification, money arithmetic, and journal construction
remain inside deterministic Python functions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from eval.suite import score_current_batch

from .ledger import run_pipeline
from .risk import scan_bank_risk


REQUIRED_SOURCES = (
    "orders.csv",
    "payments.csv",
    "refunds.csv",
    "settlement_recon.csv",
    "bank_statement.csv",
    "cashbook.csv",
    "ground_truth.json",
    "risk_truth.json",
    "provenance.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_count(path: Path) -> int:
    if path.suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 1
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return sum(1 for _ in csv.DictReader(handle))


class PipelineState(TypedDict, total=False):
    run_id: str
    data_dir: str
    results_dir: str
    status: str
    current_stage: str
    started_at: str
    completed_at: str
    duration_ms: int
    source_manifest: list[dict[str, Any]]
    source_fingerprint: str
    output_artifacts: list[str]
    counts: dict[str, int]
    metrics: dict[str, Any]
    risk_metrics: dict[str, Any]
    provenance: dict[str, Any]
    pending_approvals: list[dict[str, Any]]
    exceptions: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]
    errors: list[str]


class ApprovalState(TypedDict, total=False):
    proposal_id: str
    results_dir: str
    status: str
    journal: dict[str, Any]
    decision: Literal["approve", "reject"]
    reviewer: str
    note: str
    requested_at: str
    decided_at: str
    ledger_entry_id: str | None
    posting_result: str | None


def inspect_sources(state: PipelineState) -> PipelineState:
    data_dir = Path(state["data_dir"])
    provenance_path = data_dir / "provenance.json"
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.exists() else {}
    )
    provenance_by_name = {
        item["name"]: item for item in provenance.get("sources", [])
    }
    manifest: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in REQUIRED_SOURCES:
        path = data_dir / name
        if not path.exists():
            errors.append(f"missing required source: {name}")
            continue
        source_provenance = provenance_by_name.get(name, {})
        manifest.append({
            "name": name,
            "rows": row_count(path),
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
            "modified_at_utc": datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
            "extracted_at_utc": source_provenance.get(
                "extracted_at_utc", provenance.get("extracted_at_utc")
            ),
            "coverage_start": source_provenance.get(
                "coverage_start", provenance.get("coverage_start")
            ),
            "coverage_end": source_provenance.get(
                "coverage_end", provenance.get("coverage_end")
            ),
            "source_system": source_provenance.get("source_system", "Local artifact"),
        })
    fingerprint = hashlib.sha256(
        "|".join(item["sha256"] for item in manifest).encode()
    ).hexdigest() if manifest else ""
    return {
        "status": "failed" if errors else "running",
        "current_stage": "source_validation",
        "source_manifest": manifest,
        "source_fingerprint": fingerprint,
        "provenance": provenance,
        "errors": errors,
        "audit_events": [{
            "event": "source_validation",
            "at": utc_now(),
            "status": "failed" if errors else "passed",
            "source_count": len(manifest),
            "fingerprint": fingerprint,
        }],
    }


def route_after_sources(state: PipelineState) -> str:
    return "failed" if state.get("errors") else "reconcile"


def reconcile_batch(state: PipelineState) -> PipelineState:
    started = time.perf_counter()
    predictions, journals = run_pipeline(state["data_dir"], state["results_dir"])
    assessments, findings = scan_bank_risk(
        state["data_dir"], state["results_dir"], predictions
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    matched = sum(item["decision"] == "matched" for item in predictions)
    closed = sum(item.get("component_status") == "reconciled" for item in predictions)
    return {
        "current_stage": "deterministic_reconciliation",
        "duration_ms": elapsed,
        "counts": {
            "bank_records": len(predictions),
            "bank_matched": matched,
            "component_closed": closed,
            "component_exceptions": sum(
                item.get("component_status") == "exception" for item in predictions
            ),
            "journal_proposals": len(journals),
            "bank_entries_scanned": len(assessments),
            "dubious_entries": len(findings),
            "dubious_credits": sum(item["direction"] == "credit" for item in findings),
            "dubious_debits": sum(item["direction"] == "debit" for item in findings),
        },
        "output_artifacts": [
            "results/preds_agent.json",
            "results/journal_proposals.json",
            "results/audit.jsonl",
            "results/risk_assessments.json",
            "results/risk_findings.json",
            "results/graph_ood_assessments.json",
            "results/graph_ood_summary.json",
            "results/ledgergraph.json",
            "results/match_certificates.json",
        ],
        "audit_events": state.get("audit_events", []) + [{
            "event": "deterministic_reconciliation",
            "at": utc_now(),
            "records": len(predictions),
            "matched": matched,
            "component_closed": closed,
            "duration_ms": elapsed,
            "dubious_entries": len(findings),
        }],
    }


def measure_batch(state: PipelineState) -> PipelineState:
    results_dir = Path(state["results_dir"])
    data_dir = Path(state["data_dir"])
    evaluation = score_current_batch(
        data_dir,
        results_dir,
        system_name="langgraph_deterministic_controller",
    )
    metrics = evaluation["controller"]
    risk_metrics = evaluation["risk"]
    ledgergraph = evaluation["ledgergraph"]
    metrics = {
        **metrics,
        "evaluation_scope": "current_batch_only",
        "offline_eval_command": "python -m eval.suite",
        "risk_precision": risk_metrics["precision"],
        "risk_recall": risk_metrics["recall"],
        "risk_specificity": risk_metrics["specificity"],
        "risk_f1": risk_metrics["f1"],
        "risk_false_positives": risk_metrics["false_positives"],
        "risk_false_negatives": risk_metrics["false_negatives"],
        "risk_false_negative_exposure_inr": risk_metrics["false_negative_exposure_inr"],
        "risk_safety_gate_passed": risk_metrics["safety_gate_passed"],
        "risk_credit_recall": risk_metrics["by_direction"]["credit"]["recall"],
        "risk_debit_recall": risk_metrics["by_direction"]["debit"]["recall"],
        "ledgergraph_cases_exact": next(
            item["cases_exactly_correct"] for item in ledgergraph["comparison"]
            if item["system"] == "ledgergraph_global"
        ),
        "ledgergraph_case_count": ledgergraph["case_count"],
        "ledgergraph_false_selections": next(
            item["false_selections"] for item in ledgergraph["comparison"]
            if item["system"] == "ledgergraph_global"
        ),
    }
    return {
        "current_stage": "evaluation",
        "metrics": metrics,
        "risk_metrics": risk_metrics,
        "output_artifacts": state.get("output_artifacts", []) + [
            "results/agent/metrics.md",
            "results/agent/exceptions.md",
            "results/agent/graded.json",
            "results/risk/risk_metrics.md",
            "results/risk/risk_metrics.json",
            "results/risk/risk_graded.json",
            "results/ledgergraph/ledgergraph_metrics.md",
            "results/ledgergraph/ledgergraph_metrics.json",
            "results/ledgergraph/ledgergraph_cases.json",
            "results/ledgergraph/proof_certificates.json",
        ],
        "audit_events": state.get("audit_events", []) + [{
            "event": "current_batch_evaluation",
            "at": utc_now(),
            "false_auto_closures": metrics["false_auto_closures"],
            "bank_match_precision": metrics["bank_match_precision"],
            "component_closure_precision": metrics["component_closure_precision"],
            "risk_precision": risk_metrics["precision"],
            "risk_recall": risk_metrics["recall"],
            "risk_false_negatives": risk_metrics["false_negatives"],
            "evaluation_scope": "current_batch_only",
            "ledgergraph_cases_exact": metrics["ledgergraph_cases_exact"],
            "ledgergraph_false_selections": metrics["ledgergraph_false_selections"],
        }],
    }


def prepare_review_queue(state: PipelineState) -> PipelineState:
    results_dir = Path(state["results_dir"])
    journals = json.loads((results_dir / "journal_proposals.json").read_text(encoding="utf-8"))
    review = json.loads((results_dir / "risk_findings.json").read_text(encoding="utf-8"))
    approvals = [
        {
            "proposal_id": item["proposal_id"],
            "bank_txn_id": item["bank_txn_id"],
            "bank_txn_ids": item.get("bank_txn_ids", [item["bank_txn_id"]]),
            "settlement_id": item["settlement_id"],
            "settlement_ids": item.get("settlement_ids", [item["settlement_id"]]),
            "topology": item.get("topology", "1:1"),
            "total_debit": item["total_debit"],
            "balanced": item["balanced"],
            "status": item["approval"]["status"],
        }
        for item in journals
        if item.get("approval", {}).get("status") == "awaiting_human_approval"
    ]
    return {
        "status": "awaiting_approval" if approvals else "complete",
        "current_stage": "human_approval",
        "completed_at": utc_now(),
        "pending_approvals": approvals,
        "exceptions": review,
        "audit_events": state.get("audit_events", []) + [{
            "event": "approval_queue_prepared",
            "at": utc_now(),
            "pending_approvals": len(approvals),
            "review_exceptions": len(review),
            "authority": "human_only",
        }],
    }


def persist_run_summary(state: PipelineState) -> PipelineState:
    results_dir = Path(state["results_dir"])
    summary = dict(state)
    atomic_json(results_dir / "workflow_runs" / f"{state['run_id']}.json", summary)
    atomic_json(results_dir / "workflow_latest.json", summary)
    return {"current_stage": "human_approval"}


def mark_failed(state: PipelineState) -> PipelineState:
    result: PipelineState = {
        "status": "failed",
        "current_stage": "failed",
        "completed_at": utc_now(),
        "audit_events": state.get("audit_events", []) + [{
            "event": "workflow_failed",
            "at": utc_now(),
            "errors": state.get("errors", []),
        }],
    }
    results_dir = Path(state["results_dir"])
    atomic_json(results_dir / "workflow_runs" / f"{state['run_id']}.json", {**state, **result})
    atomic_json(results_dir / "workflow_latest.json", {**state, **result})
    return result


def build_pipeline_graph(checkpointer: SqliteSaver):
    builder = StateGraph(PipelineState)
    builder.add_node("inspect_sources", inspect_sources)
    builder.add_node("reconcile_batch", reconcile_batch)
    builder.add_node("measure_batch", measure_batch)
    builder.add_node("prepare_review_queue", prepare_review_queue)
    builder.add_node("persist_run_summary", persist_run_summary)
    builder.add_node("mark_failed", mark_failed)
    builder.add_edge(START, "inspect_sources")
    builder.add_conditional_edges(
        "inspect_sources",
        route_after_sources,
        {"reconcile": "reconcile_batch", "failed": "mark_failed"},
    )
    builder.add_edge("reconcile_batch", "measure_batch")
    builder.add_edge("measure_batch", "prepare_review_queue")
    builder.add_edge("prepare_review_queue", "persist_run_summary")
    builder.add_edge("persist_run_summary", END)
    builder.add_edge("mark_failed", END)
    return builder.compile(checkpointer=checkpointer, name="finance_controller_pipeline")


def find_journal(results_dir: Path, proposal_id: str) -> dict[str, Any]:
    journals = json.loads((results_dir / "journal_proposals.json").read_text(encoding="utf-8"))
    proposal = next((item for item in journals if item["proposal_id"] == proposal_id), None)
    if proposal is None:
        raise ValueError(f"unknown journal proposal: {proposal_id}")
    return proposal


def initialise_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS postings (
                proposal_id TEXT PRIMARY KEY,
                ledger_entry_id TEXT NOT NULL UNIQUE,
                posted_at TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                journal_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approval_events (
                event_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                note TEXT NOT NULL,
                decided_at TEXT NOT NULL
            );
        """)
        connection.commit()


def record_approval_event(
    ledger_path: Path, proposal_id: str, decision: str, reviewer: str, note: str
) -> str:
    decided_at = utc_now()
    event_key = f"{proposal_id}|{decision}|{reviewer}|{note}"
    event_id = "evt_" + hashlib.sha256(event_key.encode()).hexdigest()[:18]
    with closing(sqlite3.connect(ledger_path)) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO approval_events VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, proposal_id, decision, reviewer, note, decided_at),
        )
        connection.commit()
    return decided_at


def post_to_demo_ledger(
    ledger_path: Path, journal: dict[str, Any], reviewer: str, note: str
) -> tuple[str, str, str]:
    if not journal.get("balanced"):
        raise ValueError("unbalanced journals cannot be posted")
    if journal.get("approval", {}).get("blockers"):
        raise ValueError("journal has unresolved policy blockers")
    debit = sum(Decimal(str(entry["debit"])) for entry in journal["entries"])
    credit = sum(Decimal(str(entry["credit"])) for entry in journal["entries"])
    if debit != credit or debit != Decimal(str(journal["total_debit"])):
        raise ValueError("journal failed the final deterministic balance assertion")

    proposal_id = journal["proposal_id"]
    ledger_entry_id = "led_" + hashlib.sha256(proposal_id.encode()).hexdigest()[:18]
    posted_at = utc_now()
    payload = json.dumps(journal, sort_keys=True)
    with closing(sqlite3.connect(ledger_path)) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO postings VALUES (?, ?, ?, ?, ?)",
            (proposal_id, ledger_entry_id, posted_at, reviewer, payload),
        )
        posting_result = "posted" if cursor.rowcount == 1 else "duplicate_ignored"
        existing = connection.execute(
            "SELECT ledger_entry_id, posted_at FROM postings WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        connection.commit()
    record_approval_event(ledger_path, proposal_id, "approve", reviewer, note)
    return existing[0], existing[1], posting_result


def build_approval_graph(checkpointer: SqliteSaver, ledger_path: Path):
    def load_proposal(state: ApprovalState) -> ApprovalState:
        journal = find_journal(Path(state["results_dir"]), state["proposal_id"])
        if journal.get("approval", {}).get("status") != "awaiting_human_approval":
            raise ValueError("proposal is not eligible for human approval")
        return {
            "journal": journal,
            "status": "awaiting_human_approval",
            "requested_at": utc_now(),
        }

    def human_gate(state: ApprovalState) -> ApprovalState:
        response = interrupt({
            "kind": "journal_approval",
            "proposal_id": state["proposal_id"],
            "bank_txn_id": state["journal"]["bank_txn_id"],
            "settlement_id": state["journal"]["settlement_id"],
            "total_debit": state["journal"]["total_debit"],
            "balanced": state["journal"]["balanced"],
            "allowed_decisions": ["approve", "reject"],
            "editable_financial_fields": [],
        })
        if not isinstance(response, dict) or response.get("decision") not in {"approve", "reject"}:
            raise ValueError("approval response must contain approve or reject")
        reviewer = str(response.get("reviewer") or "local-reviewer").strip()[:80]
        note = str(response.get("note") or "").strip()[:500]
        return {
            "decision": response["decision"],
            "reviewer": reviewer,
            "note": note,
            "decided_at": utc_now(),
        }

    def route_decision(state: ApprovalState) -> str:
        return state["decision"]

    def approve(state: ApprovalState) -> ApprovalState:
        entry_id, posted_at, result = post_to_demo_ledger(
            ledger_path, state["journal"], state["reviewer"], state.get("note", "")
        )
        return {
            "status": "posted_to_sandbox_ledger",
            "ledger_entry_id": entry_id,
            "decided_at": posted_at,
            "posting_result": result,
        }

    def reject(state: ApprovalState) -> ApprovalState:
        decided_at = record_approval_event(
            ledger_path,
            state["proposal_id"],
            "reject",
            state["reviewer"],
            state.get("note", ""),
        )
        return {
            "status": "rejected",
            "ledger_entry_id": None,
            "decided_at": decided_at,
            "posting_result": "not_posted",
        }

    builder = StateGraph(ApprovalState)
    builder.add_node("load_proposal", load_proposal)
    builder.add_node("human_gate", human_gate)
    builder.add_node("post_demo_ledger", approve)
    builder.add_node("record_rejection", reject)
    builder.add_edge(START, "load_proposal")
    builder.add_edge("load_proposal", "human_gate")
    builder.add_conditional_edges(
        "human_gate",
        route_decision,
        {"approve": "post_demo_ledger", "reject": "record_rejection"},
    )
    builder.add_edge("post_demo_ledger", END)
    builder.add_edge("record_rejection", END)
    return builder.compile(checkpointer=checkpointer, name="journal_approval")


class WorkflowRuntime:
    """Thread-safe facade used by the local API and CLI."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.results_dir = self.root / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.results_dir / "workflow_checkpoints.sqlite"
        self.ledger_path = self.results_dir / "demo_ledger.sqlite"
        initialise_ledger(self.ledger_path)
        self.connection = sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection)
        self.checkpointer.setup()
        self.pipeline = build_pipeline_graph(self.checkpointer)
        self.approvals = build_approval_graph(self.checkpointer, self.ledger_path)
        self.lock = threading.RLock()

    @staticmethod
    def pipeline_config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"pipeline::{run_id}"}}

    @staticmethod
    def approval_config(proposal_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"approval::{proposal_id}"}}

    def start_run(self, run_id: str | None = None) -> dict[str, Any]:
        run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        initial: PipelineState = {
            "run_id": run_id,
            "data_dir": str(self.root / "data"),
            "results_dir": str(self.results_dir),
            "status": "running",
            "current_stage": "starting",
            "started_at": utc_now(),
            "errors": [],
            "audit_events": [],
        }
        with self.lock:
            return dict(self.pipeline.invoke(initial, self.pipeline_config(run_id)))

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self.lock:
            snapshot = self.pipeline.get_state(self.pipeline_config(run_id))
            return dict(snapshot.values) if snapshot.values else {}

    def decide(self, proposal_id: str, decision: str, reviewer: str, note: str = "") -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        config = self.approval_config(proposal_id)
        with self.lock:
            snapshot = self.approvals.get_state(config)
            if not snapshot.values:
                self.approvals.invoke(
                    {"proposal_id": proposal_id, "results_dir": str(self.results_dir)},
                    config,
                )
                snapshot = self.approvals.get_state(config)
            if snapshot.next:
                self.approvals.invoke(
                    Command(resume={"decision": decision, "reviewer": reviewer, "note": note}),
                    config,
                )
            final = self.approvals.get_state(config)
            return dict(final.values)

    def ledger_state(self) -> dict[str, dict[str, Any]]:
        with closing(sqlite3.connect(self.ledger_path)) as connection:
            postings = connection.execute(
                "SELECT proposal_id, ledger_entry_id, posted_at, reviewer FROM postings"
            ).fetchall()
            events = connection.execute(
                "SELECT proposal_id, decision, reviewer, note, decided_at FROM approval_events ORDER BY decided_at"
            ).fetchall()
        state: dict[str, dict[str, Any]] = {}
        for proposal_id, decision, reviewer, note, decided_at in events:
            state[proposal_id] = {
                "status": "rejected" if decision == "reject" else "approved",
                "decision": decision,
                "reviewer": reviewer,
                "note": note,
                "decided_at": decided_at,
            }
        for proposal_id, entry_id, posted_at, reviewer in postings:
            state[proposal_id] = {
                "status": "posted_to_sandbox_ledger",
                "decision": "approve",
                "reviewer": reviewer,
                "decided_at": posted_at,
                "ledger_entry_id": entry_id,
            }
        return state

    def approval_events(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.ledger_path)) as connection:
            rows = connection.execute(
                "SELECT proposal_id, decision, reviewer, note, decided_at FROM approval_events ORDER BY decided_at DESC"
            ).fetchall()
        return [
            {
                "event": "human_approval",
                "proposal_id": proposal_id,
                "decision": decision,
                "reviewer": reviewer,
                "note": note,
                "at": decided_at,
            }
            for proposal_id, decision, reviewer, note, decided_at in rows
        ]
