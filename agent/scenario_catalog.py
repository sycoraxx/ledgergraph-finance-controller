"""Declared realism and observability boundaries for synthetic scenarios.

The catalog prevents the demo from presenting every planted discrepancy as a
native Razorpay failure.  It is explanatory metadata only and never affects a
reconciliation or risk decision.
"""

from __future__ import annotations

from typing import Any


CATEGORY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "razorpay_native_mechanic",
        "label": "Razorpay-native mechanic",
        "short_label": "Native mechanic",
        "description": "A documented payment or settlement lifecycle behavior reproduced with simulated money.",
        "examples": ["working-day settlement cycles", "net fees and refunds", "partial settlement"],
    },
    {
        "id": "cross_system_integration_failure",
        "label": "Cross-system integration failure",
        "short_label": "Integration failure",
        "description": "A plausible bank, ERP, export, pagination, or ETL discrepancy—not asserted to be emitted by Razorpay.",
        "examples": ["missing support", "duplicate import", "amount or balance mismatch"],
    },
    {
        "id": "adversarial_stress_case",
        "label": "Adversarial stress case",
        "short_label": "Stress case",
        "description": "A deliberately difficult topology used to test global reconciliation, not to estimate production frequency.",
        "examples": ["one-to-many bank grouping", "many-to-many netting", "competing exact-money edges"],
    },
    {
        "id": "erp_control_anomaly",
        "label": "ERP control / fraud anomaly",
        "short_label": "ERP control anomaly",
        "description": "A plausible merchant-control pattern requiring independent ERP, approval, or vendor-master evidence.",
        "examples": ["counterparty substitution", "unusual approver velocity", "structured splitting"],
    },
]


def _scenario(
    scenario_id: str,
    label: str,
    category: str,
    required_sources: list[str],
    realism_basis: str,
    frequency_note: str,
    claim_boundary: str,
) -> dict[str, Any]:
    category_item = next(item for item in CATEGORY_DEFINITIONS if item["id"] == category)
    return {
        "id": scenario_id,
        "label": label,
        "category": category,
        "category_label": category_item["label"],
        "category_short_label": category_item["short_label"],
        "required_sources": required_sources,
        "realism_basis": realism_basis,
        "frequency_note": frequency_note,
        "claim_boundary": claim_boundary,
    }


SCENARIOS: dict[str, dict[str, Any]] = {
    "settlement_cycle": _scenario(
        "settlement_cycle", "Working-day settlement cycle", "razorpay_native_mechanic",
        ["Razorpay settlement schedule", "bank statement", "bank-holiday calendar"],
        "Razorpay documents working-day settlement cycles whose exact schedule varies by merchant and product.",
        "Routine lifecycle behavior; the demo's Monday-Friday calendar is simplified.",
        "The synthetic T+1/T+2 mix is a policy fixture, not a universal merchant contract.",
    ),
    "settlement_components": _scenario(
        "settlement_components", "Net settlement components", "razorpay_native_mechanic",
        ["Razorpay settlement reconciliation report", "payments", "refunds", "fees and tax"],
        "A bank settlement can be the net result of captured payments and deductions such as fees or refunds.",
        "Routine reconciliation behavior.",
        "Only the component arithmetic is represented; production product configuration can differ.",
    ),
    "partial_settlement": _scenario(
        "partial_settlement", "Partial settlement", "razorpay_native_mechanic",
        ["Razorpay settlement report", "payment and refund lifecycle", "bank statement"],
        "Razorpay documents partial settlement behavior when available live balance is below the scheduled amount.",
        "Possible lifecycle behavior rather than an anomaly by itself.",
        "The demo does not infer merchant eligibility or actual settlement configuration.",
    ),
    "benign_one_day_posting_lag": _scenario(
        "benign_one_day_posting_lag", "Benign posting lag", "razorpay_native_mechanic",
        ["settlement timestamp", "bank value date", "bank-holiday calendar"],
        "Bank posting and settlement timestamps can cross business-day boundaries.",
        "Plausible benign timing variation.",
        "A lag is not fraud and should not be flagged without contradictory evidence.",
    ),
    "amount_mismatch": _scenario(
        "amount_mismatch", "Amount mismatch", "cross_system_integration_failure",
        ["bank statement", "Razorpay settlement report", "component-level fee/refund evidence"],
        "The bank amount disagrees with the independently recomputed settlement net.",
        "Plausible ingestion, mapping, adjustment, or accounting exception.",
        "The demo does not claim Razorpay generated the incorrect value.",
    ),
    "duplicate_reference": _scenario(
        "duplicate_reference", "Duplicate reference", "cross_system_integration_failure",
        ["bank statement", "gateway export", "ingestion audit log"],
        "The same external reference appears on multiple economic events or imports.",
        "Plausible duplicate-file, replay, manual-entry, or upstream-reference issue.",
        "A duplicate reference is a review signal, not proof of provider or customer fraud.",
    ),
    "unsupported_transaction": _scenario(
        "unsupported_transaction", "Unsupported transaction", "cross_system_integration_failure",
        ["bank statement", "cashbook or ERP", "gateway/processor report"],
        "A bank movement lacks independent operational support in the supplied systems.",
        "Common reconciliation exception when feeds are late, incomplete, or mapped incorrectly.",
        "Absence in a simulated extract is not proof the real transaction is unauthorized.",
    ),
    "unattributed_settlement_component": _scenario(
        "unattributed_settlement_component", "Unattributed settlement component", "cross_system_integration_failure",
        ["settlement reconciliation report", "payments", "refunds", "adjustment source record"],
        "The settlement balances, but one adjustment cannot be attributed to an independent source record.",
        "Plausible close-control exception caused by incomplete component evidence.",
        "The controller refuses component closure; it does not label the adjustment fraudulent.",
    ),
    "balance_rollforward_mismatch": _scenario(
        "balance_rollforward_mismatch", "Balance roll-forward mismatch", "cross_system_integration_failure",
        ["ordered bank statement", "opening balance", "debit and credit columns"],
        "A statement row does not reconcile to the previous running balance.",
        "Plausible export corruption, missing row, sign error, or ingestion-order defect.",
        "This is a bank-data integrity check, not a Razorpay-native anomaly.",
    ),
    "counterparty_substitution": _scenario(
        "counterparty_substitution", "Counterparty substitution", "erp_control_anomaly",
        ["bank narration", "ERP counterparty", "approved beneficiary or vendor master"],
        "Money and reference can agree while the observed payee identity conflicts with approved merchant evidence.",
        "Plausible control breach, data-entry error, or beneficiary substitution pattern.",
        "Razorpay settlement data alone cannot establish this; independent ERP evidence is required.",
    ),
    "collusive_duplicate": _scenario(
        "collusive_duplicate", "Collusive duplicate", "erp_control_anomaly",
        ["bank statement", "ERP cashbook", "invoice lineage", "approval history"],
        "A new-looking reference and approval can still repeat an earlier economic amount/counterparty motif.",
        "Plausible duplicate-payment or collusion control scenario.",
        "The graph signal only requests review and cannot prove intent or collusion.",
    ),
    "approver_velocity_burst": _scenario(
        "approver_velocity_burst", "Approver velocity burst", "erp_control_anomaly",
        ["timestamped approval history", "ERP cashbook", "approver identity"],
        "One approver authorizes an unusual cluster of events in a short period.",
        "Plausible behavioral-control signal with legitimate end-of-period alternatives.",
        "Velocity requires historical context and is never fraud proof by itself.",
    ),
    "structured_split_payment": _scenario(
        "structured_split_payment", "Structured split payment", "erp_control_anomaly",
        ["bank transactions", "invoice or purchase-order linkage", "approval thresholds"],
        "Related payments are divided into smaller events that may avoid a control threshold.",
        "Plausible control-circumvention pattern with legitimate installment alternatives.",
        "The required linkage is unavailable from Razorpay settlement data alone.",
    ),
    "coordinated_vendor_master_takeover": _scenario(
        "coordinated_vendor_master_takeover", "Vendor-master takeover", "erp_control_anomaly",
        ["vendor-master change log", "beneficiary history", "ERP approvals", "bank transaction"],
        "A beneficiary change precedes coordinated payments to the modified vendor identity.",
        "Plausible accounts-payable control scenario.",
        "Detection requires independent, timestamped vendor-master evidence not present in a normal settlement export.",
    ),
    "out_of_hours_approval": _scenario(
        "out_of_hours_approval", "Out-of-hours approval", "erp_control_anomaly",
        ["approval timestamp", "user timezone", "work calendar", "ERP event"],
        "An approval occurs outside the declared operating calendar.",
        "Plausible weak signal with many benign explanations.",
        "Operating-hours deviation must be combined with stronger evidence before escalation.",
    ),
    "benign_uncommon_operating_path": _scenario(
        "benign_uncommon_operating_path", "Benign uncommon operating path", "erp_control_anomaly",
        ["ERP event", "approval history", "declared operating policy"],
        "An uncommon but legitimate path is included as a hard negative.",
        "Necessary to measure false-positive cost around rare behavior.",
        "Uncommon does not mean dubious; this row must remain unflagged.",
    ),
    "topology:1:1": _scenario(
        "topology:1:1", "One bank entry → one settlement", "razorpay_native_mechanic",
        ["bank statement", "settlement report", "settlement UTR/reference"],
        "The ordinary settlement-to-bank reconciliation shape.",
        "Expected primary topology in a clean direct settlement feed.",
        "Its presence is realistic; the demo does not estimate its production share.",
    ),
    "topology:1:N": _scenario(
        "topology:1:N", "One bank entry → many settlements", "adversarial_stress_case",
        ["bank statement", "settlement report", "treasury aggregation or sweep evidence"],
        "Possible when an external bank or treasury layer aggregates separately identified settlements.",
        "Plausible cross-system shape, but not asserted as standard Razorpay settlement behavior.",
        "Included to prove grouped reconciliation, not to model production frequency.",
    ),
    "topology:N:1": _scenario(
        "topology:N:1", "Many bank entries → one settlement", "adversarial_stress_case",
        ["bank statement", "settlement lifecycle", "partial/retry or posting evidence"],
        "Possible when posting, partial-credit, retry, or intermediate-ledger behavior splits one economic settlement.",
        "Adversarial integration topology rather than the expected clean path.",
        "Included to test global grouping; actual frequency is unknown.",
    ),
    "topology:N:M": _scenario(
        "topology:N:M", "Many bank entries ↔ many settlements", "adversarial_stress_case",
        ["bank statement", "settlement report", "treasury/netting ledger", "component evidence"],
        "A bounded netting or aggregation layer can create an irreducible many-to-many explanation.",
        "High-complexity stress case and not claimed as a routine native feed shape.",
        "The balanced demo count deliberately over-samples this topology.",
    ),
}


UNKNOWN_SCENARIO = _scenario(
    "unclassified", "Unclassified synthetic scenario", "adversarial_stress_case",
    ["scenario-specific independent evidence"],
    "No declared realism mapping exists yet.",
    "Unknown.",
    "Do not make a production claim until the scenario is classified.",
)


def scenario_context(scenario_id: str) -> dict[str, Any]:
    """Return non-authoritative explanatory metadata for one scenario."""
    return dict(SCENARIOS.get(scenario_id, {**UNKNOWN_SCENARIO, "id": scenario_id}))


def scenario_catalog() -> dict[str, Any]:
    return {
        "authority": "explanatory metadata only; never changes a financial decision",
        "frequency_boundary": "Balanced synthetic counts are test coverage, not production prevalence estimates.",
        "categories": CATEGORY_DEFINITIONS,
        "scenarios": SCENARIOS,
        "references": [
            {
                "label": "Razorpay payment settlements",
                "url": "https://razorpay.com/docs/payments/settlements/?preferred-country=IN",
            },
            {
                "label": "Razorpay reports data schema",
                "url": "https://razorpay.com/docs/payments/dashboard/reports/data-schema/?preferred-country=IN",
            },
        ],
    }
