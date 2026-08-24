"""Deterministic candidate search for records that L0 cannot resolve."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


EXCEL_EPOCH = datetime(1899, 12, 30)


def parse_date_candidates(value: str | None) -> set[str]:
    """Return possible ISO dates without pretending ambiguous dates are exact."""
    value = (value or "").strip()
    if not value:
        return set()

    try:
        serial = float(value)
    except ValueError:
        pass
    else:
        return {(EXCEL_EPOCH + timedelta(days=serial)).date().isoformat()}

    out: set[str] = set()
    head = value.split()[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            out.add(datetime.strptime(head, fmt).date().isoformat())
        except ValueError:
            continue

    # The source deliberately contains YYYY-DD-MM values which are
    # indistinguishable from ISO when both fields are <= 12. Preserve both.
    parts = head.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        year, second, third = map(int, parts)
        for month, day in ((second, third), (third, second)):
            try:
                out.add(datetime(year, month, day).date().isoformat())
            except ValueError:
                continue
    return out


def _date_agrees(bank_row: dict[str, str], settlement: dict[str, Any]) -> bool:
    bank_dates = parse_date_candidates(bank_row.get("value_date"))
    if not bank_dates:
        bank_dates = parse_date_candidates(bank_row.get("txn_date"))
    return bool(bank_dates & settlement.get("settled_dates", set()))


def reconcile_search(
    bank_row: dict[str, str],
    settlements: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Match by exact net, using date and partial UTR only to break ties."""
    credit = Decimal(bank_row.get("credit") or "0") - Decimal(bank_row.get("debit") or "0")
    narration = (bank_row.get("narration") or "").upper()
    amount_hits = [
        (sid, settlement)
        for sid, settlement in settlements.items()
        if settlement["net"] == credit
    ]
    if not amount_hits:
        return None

    if len(amount_hits) == 1:
        sid, settlement = amount_hits[0]
        date_ok = _date_agrees(bank_row, settlement)
        return {
            "settlement_id": sid,
            "settlement": settlement,
            "confidence": 0.97 if date_ok else 0.90,
            "layer": "L1-structured-search",
            "reason": (
                "globally unique exact net and compatible settlement date"
                if date_ok
                else "globally unique exact net; date representation was ambiguous"
            ),
        }

    scored = []
    for sid, settlement in amount_hits:
        score = 0
        evidence = []
        if _date_agrees(bank_row, settlement):
            score += 3
            evidence.append("date")
        utr = (settlement.get("utr") or "").upper()
        if len(utr) >= 11 and utr[:11] in narration:
            score += 1
            evidence.append("UTR date prefix")
        scored.append((score, sid, settlement, evidence))

    scored.sort(key=lambda item: item[0], reverse=True)
    if scored[0][0] < 3 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None

    _, sid, settlement, evidence = scored[0]
    return {
        "settlement_id": sid,
        "settlement": settlement,
        "confidence": 0.88,
        "layer": "L1-structured-search",
        "reason": "exact-net collision resolved by " + " and ".join(evidence),
    }
