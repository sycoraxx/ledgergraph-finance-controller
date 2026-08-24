"""Exact, high-precision bank-to-settlement matching."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def reconcile_exact(
    bank_row: dict[str, str],
    settlements: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a match only when full UTR and amount independently agree."""
    narration = (bank_row.get("narration") or "").upper()
    credit = Decimal(bank_row.get("credit") or "0") - Decimal(bank_row.get("debit") or "0")
    candidates = []

    for settlement_id, settlement in settlements.items():
        utr = (settlement.get("utr") or "").upper()
        if utr and utr in narration and settlement["net"] == credit:
            candidates.append((settlement_id, settlement))

    if len(candidates) != 1:
        return None

    settlement_id, settlement = candidates[0]
    return {
        "settlement_id": settlement_id,
        "settlement": settlement,
        "confidence": 1.0,
        "layer": "L0-exact",
        "reason": "full UTR in bank narration and exact settlement net",
    }
