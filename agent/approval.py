"""Fail-closed policy for journal proposal eligibility."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


DEFAULT_APPROVAL_THRESHOLD = Decimal("100000.00")


def approval_decision(
    *,
    confidence: float,
    component_status: str,
    bank_credit: Decimal,
    journal_balanced: bool,
    threshold: Decimal = DEFAULT_APPROVAL_THRESHOLD,
) -> dict[str, Any]:
    """Return policy state; this function never posts anything."""
    blockers = []
    if confidence < 0.90:
        blockers.append("bank match confidence below 0.90")
    if component_status != "reconciled":
        blockers.append("settlement components are not fully reconciled")
    if not journal_balanced:
        blockers.append("journal does not balance")
    if bank_credit <= 0:
        blockers.append("non-positive bank credit requires manual treatment")

    if blockers:
        return {
            "status": "needs_review",
            "human_approval_required": True,
            "blockers": blockers,
        }

    return {
        "status": "awaiting_human_approval",
        "human_approval_required": True,
        "blockers": [],
        "reason": (
            f"amount is at or above INR {threshold}"
            if bank_credit >= threshold
            else "deterministic checks passed; posting remains outside demo scope"
        ),
    }
