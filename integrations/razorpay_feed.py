"""Read-only Razorpay Test Mode simulated-data snapshot ingestion.

Credentials are read from environment variables (or the ignored project .env
file), used only for HTTP Basic authentication, and never persisted or logged.
The adapter deliberately stages Razorpay data separately from the synthetic
benchmark because Razorpay does not provide the independent bank statement or
ERP cashbook required for a genuine three-way reconciliation.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://api.razorpay.com/v1"
ALLOWED_PATHS = {
    "/orders",
    "/payments",
    "/refunds/",
    "/settlements/",
    "/settlements/recon/combined",
}
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "razorpay_api"
STATUS_PATH = ROOT / "results" / "razorpay_feed_status.json"
Transport = Callable[[Request, float], bytes]


class RazorpayFeedError(RuntimeError):
    """A credential, transport, or response-contract error safe to show in UI."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_project_env(path: Path = ROOT / ".env") -> None:
    """Load only missing values from a simple KEY=VALUE file."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def credentials() -> tuple[str, str]:
    load_project_env()
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise RazorpayFeedError(
            "Razorpay Test Mode credentials are not configured. Add RAZORPAY_KEY_ID "
            "and RAZORPAY_KEY_SECRET to the ignored project .env file."
        )
    if not key_id.startswith("rzp_test_"):
        raise RazorpayFeedError(
            "Only rzp_test_ credentials are accepted by this demo connector; live-mode keys are blocked."
        )
    return key_id, key_secret


def default_transport(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed host + whitelist
        return response.read()


def safe_error_detail(payload: bytes) -> str:
    try:
        parsed = json.loads(payload.decode("utf-8", errors="replace"))
        detail = parsed.get("error", {}).get("description") or parsed.get("error", {}).get("reason")
        if detail:
            return str(detail)[:300]
    except (json.JSONDecodeError, AttributeError):
        pass
    return "Razorpay rejected the read-only request."


class RazorpayReadOnlyClient:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        timeout: float = 15.0,
        transport: Transport = default_transport,
    ) -> None:
        if not key_id.startswith("rzp_test_"):
            raise RazorpayFeedError("Only Razorpay Test Mode keys are permitted.")
        self.key_id = key_id
        self._secret = key_secret
        self.timeout = timeout
        self.transport = transport

    def get(self, path: str, params: dict[str, int]) -> dict[str, Any]:
        if path not in ALLOWED_PATHS:
            raise RazorpayFeedError(f"Endpoint is not in the read-only allowlist: {path}")
        token = base64.b64encode(f"{self.key_id}:{self._secret}".encode()).decode("ascii")
        url = f"{API_BASE}{path}?{urlencode(params)}"
        request = Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "User-Agent": "finance-controller-buildathon/1.0",
            },
        )
        try:
            raw = self.transport(request, self.timeout)
        except HTTPError as exc:
            body = exc.read()
            raise RazorpayFeedError(
                f"Razorpay API returned HTTP {exc.code}: {safe_error_detail(body)}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RazorpayFeedError("Could not reach the Razorpay API within the timeout.") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RazorpayFeedError("Razorpay returned a non-JSON response.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
            raise RazorpayFeedError("Razorpay response did not match the expected collection contract.")
        return payload

    def paginate(
        self,
        path: str,
        params: dict[str, int],
        *,
        page_size: int,
        max_records: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        skip = 0
        while len(items) < max_records:
            requested = min(page_size, max_records - len(items))
            payload = self.get(path, {**params, "count": requested, "skip": skip})
            page = payload.get("items", [])
            items.extend(item for item in page if isinstance(item, dict))
            if len(page) < requested:
                break
            skip += len(page)
        return items


def subunits(value: Any) -> str:
    return f"{(Decimal(str(value or 0)) / Decimal('100')):.2f}"


def timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()


def compact(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def project(item: dict[str, Any], fields: list[str]) -> dict[str, str]:
    row = {}
    for field in fields:
        value = item.get(field)
        if field in {"amount", "amount_paid", "amount_due", "amount_refunded", "amount_transferred", "fee", "fees", "tax", "debit", "credit"}:
            row[field] = subunits(value)
        elif field.endswith("_at"):
            row[field] = timestamp(value)
        else:
            row[field] = compact(value)
    return row


ORDER_FIELDS = [
    "id", "amount", "amount_paid", "amount_due", "currency", "receipt", "offer_id",
    "status", "attempts", "notes", "created_at",
]
PAYMENT_FIELDS = [
    "id", "amount", "currency", "status", "order_id", "invoice_id", "international",
    "method", "amount_refunded", "amount_transferred", "refund_status", "captured",
    "description", "card_id", "card", "bank", "wallet", "vpa", "email", "contact",
    "notes", "fee", "tax", "error_code", "error_description", "created_at",
]
REFUND_FIELDS = [
    "id", "amount", "currency", "payment_id", "notes", "receipt", "created_at",
    "contact", "email", "arn", "status", "speed_processed", "speed_requested",
]
SETTLEMENT_FIELDS = ["id", "entity", "amount", "status", "fees", "tax", "utr", "created_at"]
RECON_FIELDS = [
    "transaction_entity", "entity_id", "amount", "currency", "fee (exclusive tax)",
    "tax", "debit", "credit", "payment_method", "card_type", "issuer_name",
    "entity_created_at", "payment_captured_at", "payment_notes", "refund_notes", "arn",
    "entity_description", "order_id", "order_receipt", "order_notes", "dispute_id",
    "dispute_created_at", "dispute_reason", "settlement_id", "settled_at",
    "settlement_utr", "settled_by",
]


def recon_row(item: dict[str, Any]) -> dict[str, str]:
    mapped = {
        "transaction_entity": item.get("type"),
        "entity_id": item.get("entity_id"),
        "amount": subunits(item.get("amount")),
        "currency": item.get("currency"),
        "fee (exclusive tax)": subunits(item.get("fee")),
        "tax": subunits(item.get("tax")),
        "debit": subunits(item.get("debit")),
        "credit": subunits(item.get("credit")),
        "payment_method": item.get("method"),
        "card_type": item.get("card_type"),
        "issuer_name": item.get("card_issuer"),
        "entity_created_at": timestamp(item.get("created_at")),
        "payment_notes": compact(item.get("notes")) if item.get("type") == "payment" else "",
        "refund_notes": compact(item.get("notes")) if item.get("type") == "refund" else "",
        "entity_description": item.get("description"),
        "order_id": item.get("order_id"),
        "order_receipt": item.get("order_receipt"),
        "dispute_id": item.get("dispute_id"),
        "settlement_id": item.get("settlement_id"),
        "settled_at": timestamp(item.get("settled_at")),
        "settlement_utr": item.get("settlement_utr"),
    }
    return {field: compact(mapped.get(field)) for field in RECON_FIELDS}


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        json.dump(value, handle, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)


def feed_status() -> dict[str, Any]:
    load_project_env()
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    last = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    return {
        "configured": bool(key_id and os.getenv("RAZORPAY_KEY_SECRET", "").strip()),
        "mode": "test",
        "data_classification": "simulated_test_data",
        "real_money": False,
        "api_base": API_BASE,
        "key_id_hint": f"{key_id[:12]}…" if key_id else None,
        "read_only": True,
        "live_keys_blocked": True,
        "last_sync": last or None,
        "controller_ready": bool(last.get("controller_ready")),
        "missing_independent_sources": last.get(
            "missing_independent_sources", ["bank_statement.csv", "cashbook.csv"]
        ),
    }


def sync_feed(
    *,
    output_root: Path = DEFAULT_OUTPUT,
    status_path: Path = STATUS_PATH,
    now: datetime | None = None,
    max_records: int = 1000,
    client: RazorpayReadOnlyClient | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now - timedelta(days=31)
    if client is None:
        key_id, key_secret = credentials()
        client = RazorpayReadOnlyClient(key_id, key_secret)
    common = {"from": int(start.timestamp()), "to": int(now.timestamp())}
    collections = {
        "orders": client.paginate("/orders", common, page_size=100, max_records=max_records),
        "payments": client.paginate("/payments", common, page_size=100, max_records=max_records),
        "refunds": client.paginate("/refunds/", common, page_size=100, max_records=max_records),
        "settlements": client.paginate("/settlements/", common, page_size=100, max_records=max_records),
        "settlement_recon": client.paginate(
            "/settlements/recon/combined",
            {"year": now.year, "month": now.month},
            page_size=1000,
            max_records=max_records,
        ),
    }
    extracted_at = utc_now()
    snapshot_id = now.strftime("%Y%m%dT%H%M%SZ")
    snapshot = output_root / "snapshots" / snapshot_id
    suffix = 1
    while snapshot.exists():
        snapshot = output_root / "snapshots" / f"{snapshot_id}-{suffix}"
        suffix += 1
    raw_dir = snapshot / "raw"
    raw_dir.mkdir(parents=True)
    for name, items in collections.items():
        atomic_json(raw_dir / f"{name}.json", {"entity": "collection", "count": len(items), "items": items})

    write_csv(snapshot / "orders.csv", ORDER_FIELDS, [project(item, ORDER_FIELDS) for item in collections["orders"]])
    write_csv(snapshot / "payments.csv", PAYMENT_FIELDS, [project(item, PAYMENT_FIELDS) for item in collections["payments"]])
    write_csv(snapshot / "refunds.csv", REFUND_FIELDS, [project(item, REFUND_FIELDS) for item in collections["refunds"]])
    write_csv(snapshot / "settlements.csv", SETTLEMENT_FIELDS, [project(item, SETTLEMENT_FIELDS) for item in collections["settlements"]])
    write_csv(snapshot / "settlement_recon.csv", RECON_FIELDS, [recon_row(item) for item in collections["settlement_recon"]])

    csv_files = ["orders.csv", "payments.csv", "refunds.csv", "settlements.csv", "settlement_recon.csv"]
    currencies = sorted({str(item.get("currency")) for values in collections.values() for item in values if item.get("currency")})
    try:
        displayed_snapshot_path = str(snapshot.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        displayed_snapshot_path = str(snapshot)
    status = {
        "status": "connected",
        "mode": "test",
        "read_only": True,
        "data_classification": "simulated_test_data",
        "real_money": False,
        "api_base": API_BASE,
        "snapshot_id": snapshot.name,
        "snapshot_path": displayed_snapshot_path,
        "extracted_at_utc": extracted_at,
        "coverage_start_utc": start.isoformat(),
        "coverage_end_utc": now.isoformat(),
        "counts": {name: len(items) for name, items in collections.items()},
        "currencies": currencies,
        "normalization": "API currency subunits converted to 2-decimal major units; intended for INR demo data.",
        "files": [
            {"name": name, "rows": len(collections["settlement_recon"] if name == "settlement_recon.csv" else collections[name.removesuffix(".csv")]), "sha256": sha256(snapshot / name)}
            for name in csv_files
        ],
        "controller_ready": False,
        "missing_independent_sources": ["bank_statement.csv", "cashbook.csv"],
        "limitation": (
            "Razorpay Test Mode does not create a real bank receipt or ERP authorization. This demo uses "
            "a disclosed simulated bank emulator and simulated merchant ERP fixture for those sources."
        ),
    }
    atomic_json(snapshot / "provenance.json", status)
    atomic_json(output_root / "latest.json", status)
    atomic_json(status_path, status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a read-only Razorpay Test Mode snapshot")
    parser.add_argument("--max-records", type=int, default=1000)
    args = parser.parse_args()
    if not 1 <= args.max_records <= 10000:
        raise SystemExit("--max-records must be between 1 and 10000")
    try:
        print(json.dumps(sync_feed(max_records=args.max_records), indent=2))
    except RazorpayFeedError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
