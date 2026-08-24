"""
Synthetic reconciliation data generator, v2.

Column names, debit/credit conventions and date-format chaos are taken from
Razorpay's own sample reports (orders / payments / refunds / settlements-recon).

Simulates forward: orders -> payments -> fees -> refunds -> disputes ->
settlement batches -> bank credits. Ground truth is recorded during the
simulation, never inferred afterwards. No LLM involved anywhere.
"""

import csv
import json
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

SEED = 20260820
GST_RATE = Decimal("0.18")
EXCEL_EPOCH = date(1899, 12, 30)

# One plausible negotiated rate card, NOT the rate card. Razorpay prices per
# merchant (blended vs split), so the agent must INFER effective rates from
# settlement history rather than assume these. See provenance.md.
# Note UPI is not free: MDR is zero by mandate but a platform fee still applies.
RATE_CARD = {
    "upi": Decimal("0.0200"),
    "card_debit": Decimal("0.0120"),
    "card_credit": Decimal("0.0200"),
    "card_premium": Decimal("0.0250"),
    "card_intl": Decimal("0.0350"),
    "netbanking": Decimal("0.0175"),
    "wallet": Decimal("0.0200"),
}

REFUND_FEE = Decimal("4.00")   # flat per-refund charge, separate from MDR

CARD_TYPES = ["credit", "debit", ""]
ISSUERS = ["HDFC", "ICICI", "SBIN", "AXIS", "KKBK", ""]
DISPUTE_REASONS = [
    "product_not_received", "fraud", "duplicate_processing",
    "credit_not_processed",
]

HOLIDAYS = {date(2026, 8, 15), date(2026, 10, 2)}


def money(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def add_working_days(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if is_working_day(d):
            n -= 1
    return d


def working_day_path(d: date, n: int) -> str:
    """Human-readable canonical calendar proof for a synthetic T+n policy."""
    parts = [f"{d.isoformat()} T"]
    current, counted = d, 0
    while counted < n:
        current += timedelta(days=1)
        if is_working_day(current):
            counted += 1
            parts.append(f"{current.isoformat()} B{counted}")
        else:
            parts.append(f"{current.isoformat()} skipped")
    return " -> ".join(parts)


class DateWriter:
    """
    Razorpay's own sample recon report mixes ISO timestamps, dd/mm/yyyy strings
    and raw Excel serial floats inside a single column. We reproduce that.

    'iso'    -> 2026-08-04 10:43:32
    'dmy'    -> 04/08/2026 10:43:32
    'serial' -> 46238.44689814815
    'ambig'  -> ISO-shaped but day and month swapped, so 2026-07-04 could be
                4 July or 7 April. Parse it wrong and the settlement window
                shifts by months. This is the trap.
    """

    def __init__(self, rng, weights=(55, 25, 15, 5)):
        self.rng = rng
        self.weights = weights

    def __call__(self, d: date, hour_seed: int = 0) -> str:
        t = timedelta(
            hours=(hour_seed * 7) % 24,
            minutes=(hour_seed * 13) % 60,
            seconds=(hour_seed * 29) % 60,
        )
        dt = datetime.combine(d, datetime.min.time()) + t
        style = self.rng.choices(
            ["iso", "dmy", "serial", "ambig"], weights=self.weights
        )[0]
        if style == "iso":
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        if style == "dmy":
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        if style == "serial":
            frac = t.total_seconds() / 86400
            return repr((d - EXCEL_EPOCH).days + frac)
        return dt.strftime("%Y-%d-%m %H:%M:%S")


@dataclass
class Order:
    order_id: str
    created_at: date
    receipt: str
    customer_id: str
    gross_amount: Decimal
    channel: str
    status: str = "paid"
    attempts: int = 1


@dataclass
class Payment:
    payment_id: str
    order_id: str
    order_receipt: str
    captured_at: date
    amount: Decimal
    method: str
    card_type: str
    issuer: str
    rate_key: str
    international: bool
    fee: Decimal
    tax: Decimal
    settlement_id: str = ""
    status: str = "captured"

    @property
    def net(self) -> Decimal:
        return money(self.amount - self.fee - self.tax)


@dataclass
class Refund:
    refund_id: str
    payment_id: str
    order_id: str
    created_at: date
    amount: Decimal
    fee: Decimal
    tax: Decimal
    arn: str
    reason: str
    settled_in_batch: str = ""

    @property
    def debit(self) -> Decimal:
        return money(self.amount + self.fee + self.tax)


@dataclass
class Dispute:
    dispute_id: str
    payment_id: str
    order_id: str
    created_at: date
    amount: Decimal
    reason: str
    settled_in_batch: str = ""


@dataclass
class Adjustment:
    adjustment_id: str
    amount: Decimal
    reason: str
    settled_in_batch: str = ""


@dataclass
class Settlement:
    settlement_id: str
    utr: str
    settled_at: date
    capture_date: date | None = None
    scheduled_business_days: int = 2
    payments: list = field(default_factory=list)
    refunds: list = field(default_factory=list)
    disputes: list = field(default_factory=list)
    adjustments: list = field(default_factory=list)
    tier: int = 0
    batch_resolvable: bool = True
    components_resolvable: bool = True
    unresolvable_reason: str | None = None
    utr_presence: str = "full"      # full | truncated | bank_ref
    bank_ref: str = ""

    @property
    def credit(self) -> Decimal:
        """Bank credit = sum of credits minus sum of debits in the recon report."""
        total = sum((p.net for p in self.payments), Decimal("0"))
        total -= sum((r.debit for r in self.refunds), Decimal("0"))
        total -= sum((d.amount for d in self.disputes), Decimal("0"))
        total += sum((a.amount for a in self.adjustments), Decimal("0"))
        return money(total)


class Generator:
    def __init__(self, seed=SEED, days=75, busy=(22, 48), quiet_prob=0.18):
        self.seed = seed
        # Independent streams per concern. A single shared RNG means adding a
        # draw anywhere (e.g. a new card-type roll) shifts every downstream
        # value, silently changing records you did not touch. Separate streams
        # keep the dataset stable so day-to-day eval numbers stay comparable.
        self.rng_volume = random.Random(seed + 101)    # day schedule, amounts
        self.rng_pay = random.Random(seed + 202)       # method, card, issuer
        self.rng_refund = random.Random(seed + 303)
        self.rng_dispute = random.Random(seed + 404)
        self.rng_batch = random.Random(seed + 505)     # utr, tier, injections
        self.rng_render = random.Random(seed + 606)    # dates, narration
        self.rng_risk = random.Random(seed + 707)      # cashbook + bank-risk cases
        self.rng = self.rng_volume                     # back-compat alias
        self.dw = DateWriter(self.rng_render)
        self.days = days
        self.busy = busy
        self.quiet_prob = quiet_prob
        self.start = date(2026, 6, 1)
        self.orders, self.payments, self.refunds = [], [], []
        self.disputes, self.adjustments, self.settlements = [], [], []
        self.cashbook = []

    def _token(self, rng=None, n=14):
        rng = rng or self.rng_volume
        alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        return "".join(rng.choice(alpha) for _ in range(n))

    # ---- stage 1: orders and payments -------------------------------------

    def make_orders(self):
        for i in range(self.days):
            d = self.start + timedelta(days=i)
            # quiet days produce single-payment settlements, which is tier 0
            if self.rng_volume.random() < self.quiet_prob:
                n = self.rng_volume.randint(1, 2)
            else:
                n = self.rng_volume.randint(*self.busy)
            for _ in range(n):
                amt = money(self.rng_volume.choice([
                    self.rng_volume.randint(199, 999),
                    self.rng_volume.randint(1000, 4999),
                    self.rng_volume.randint(5000, 24999),
                ]) + self.rng_volume.choice([0, 0.5]))
                o = Order(
                    order_id=f"order_{self._token(self.rng_volume)}",
                    created_at=d,
                    receipt=f"rcpt-{self.rng_volume.randint(10000, 99999)}",
                    customer_id=f"cust_{self.rng_volume.randint(1, 600):04d}",
                    gross_amount=amt,
                    channel=self.rng_volume.choice(["web", "web", "web", "pos"]),
                )
                self.orders.append(o)
                self.capture(o)

    def capture(self, order: Order):
        method = self.rng_pay.choices(
            ["upi", "card", "netbanking", "wallet"], weights=[55, 30, 10, 5]
        )[0]
        card_type, intl = "", False

        if method == "card":
            intl = self.rng_pay.random() < 0.03
            if intl:
                card_type, rate_key = "credit", "card_intl"
            else:
                card_type = self.rng_pay.choices(
                    ["credit", "debit"], weights=[62, 38])[0]
                if card_type == "credit" and self.rng_pay.random() < 0.15:
                    rate_key = "card_premium"      # premium / corporate card
                else:
                    rate_key = f"card_{card_type}"
        else:
            rate_key = method

        fee = money(order.gross_amount * RATE_CARD[rate_key])
        self.payments.append(Payment(
            payment_id=f"pay_{self._token(self.rng_pay)}",
            order_id=order.order_id,
            order_receipt=order.receipt,
            captured_at=order.created_at,
            amount=order.gross_amount,
            method=method,
            card_type=card_type,
            issuer=self.rng_pay.choice(ISSUERS) if method in ("card", "netbanking") else "",
            rate_key=rate_key,
            international=intl,
            fee=fee,
            tax=money(fee * GST_RATE),
        ))

    # ---- stage 2: refunds and disputes ------------------------------------

    def make_refunds(self, rate=0.045):
        for p in self.payments:
            if self.rng_refund.random() < rate:
                lag = self.rng_refund.randint(1, 14)
                amt = p.amount if self.rng_refund.random() < 0.7 else money(
                    p.amount * Decimal(self.rng_refund.choice(["0.25", "0.50"])))
                self.refunds.append(Refund(
                    refund_id=f"rfnd_{self._token(self.rng_refund)}",
                    payment_id=p.payment_id,
                    order_id=p.order_id,
                    created_at=p.captured_at + timedelta(days=lag),
                    amount=amt,
                    fee=REFUND_FEE,
                    tax=money(REFUND_FEE * GST_RATE),
                    arn=str(self.rng_refund.randint(10**11, 10**12 - 1)),
                    reason=self.rng_refund.choice([
                        "customer_request", "item_out_of_stock",
                        "duplicate_order", "quality_issue"]),
                ))

    def make_disputes(self, rate=0.008):
        """Chargebacks land weeks later and reverse an already-closed batch."""
        for p in self.payments:
            if p.method == "card" and self.rng_dispute.random() < rate:
                lag = self.rng_dispute.randint(18, 55)
                self.disputes.append(Dispute(
                    dispute_id=f"disp_{self._token(self.rng_dispute)}",
                    payment_id=p.payment_id,
                    order_id=p.order_id,
                    created_at=p.captured_at + timedelta(days=lag),
                    amount=p.amount,
                    reason=self.rng_dispute.choice(DISPUTE_REASONS),
                ))

    # ---- stage 3: batching ------------------------------------------------

    def make_settlements(self):
        by_day = {}
        for p in self.payments:
            by_day.setdefault(p.captured_at, []).append(p)

        for capture_day in sorted(by_day):
            scheduled_business_days = (
                2 if capture_day.weekday() == 3
                else 1 if (capture_day.toordinal() + self.seed) % 2 == 0
                else 2
            )
            settled_at = add_working_days(capture_day, scheduled_business_days)
            s = Settlement(
                settlement_id=f"setl_{self._token(self.rng_batch)}",
                utr=f"CITIN{settled_at:%y%m%d}{self.rng_batch.randint(10**7, 10**8-1)}",
                settled_at=settled_at,
                capture_date=capture_day,
                scheduled_business_days=scheduled_business_days,
            )
            # A bank's own reference, distinct from the gateway UTR. The bank
            # statement's ref_no column carries this, and narrations in
            # 'bank_ref' mode show it instead of the UTR.
            s.bank_ref = str(self.rng_render.randint(10**9, 10**10 - 1))
            for p in by_day[capture_day]:
                p.settlement_id = s.settlement_id
                s.payments.append(p)

            for r in self.refunds:
                if not r.settled_in_batch and r.created_at <= settled_at:
                    r.settled_in_batch = s.settlement_id
                    s.refunds.append(r)

            for dp in self.disputes:
                if not dp.settled_in_batch and dp.created_at <= settled_at:
                    dp.settled_in_batch = s.settlement_id
                    s.disputes.append(dp)

            self.assign_tier(s)
            self.assign_utr_presence(s)
            self.settlements.append(s)

    def assign_tier(self, s: Settlement):
        own = {p.payment_id for p in s.payments}
        # a refund is cross-period if its original payment settled elsewhere
        cross = any(r.payment_id not in own for r in s.refunds)

        if len(s.payments) <= 2 and not s.refunds and not s.disputes:
            s.tier = 0
        elif s.disputes or cross:
            s.tier = 2
        else:
            s.tier = 1

        roll = self.rng_batch.random()
        if roll < 0.10:
            s.tier = 3
            self.inject_adversarial(s)
        elif roll < 0.15:
            s.tier = 4
            self.inject_unresolvable(s)

    def assign_utr_presence(self, s: Settlement):
        """
        Decide how much of the UTR reaches the bank narration.

        Real bank narrations rarely carry the gateway's full UTR verbatim; they
        often show a bank reference instead, or truncate it. We keep the full
        UTR only ~35% of the time so the rest must be matched by amount and
        composition. Tier 3 is adversarial and never leaks the full UTR.
        """
        r = self.rng_render.random()
        if s.tier == 3:
            s.utr_presence = "truncated" if r < 0.5 else "bank_ref"
        elif r < 0.35:
            s.utr_presence = "full"
        elif r < 0.68:
            s.utr_presence = "truncated"
        else:
            s.utr_presence = "bank_ref"

    def inject_adversarial(self, s: Settlement):
        if not s.payments:
            return
        src = self.rng_batch.choice(s.payments)
        dup = Payment(
            payment_id=f"pay_{self._token(self.rng_batch)}",
            order_id=src.order_id,
            order_receipt=src.order_receipt,
            captured_at=src.captured_at,
            amount=src.amount,
            method=src.method,
            card_type=src.card_type,
            issuer=src.issuer,
            rate_key=src.rate_key,
            international=src.international,
            fee=src.fee,
            tax=src.tax,
            settlement_id=s.settlement_id,
        )
        self.payments.append(dup)
        s.payments.append(dup)
        rev = Refund(
            refund_id=f"rfnd_{self._token(self.rng_batch)}",
            payment_id=dup.payment_id,
            order_id=dup.order_id,
            created_at=s.settled_at,
            amount=dup.amount,
            fee=REFUND_FEE,
            tax=money(REFUND_FEE * GST_RATE),
            arn=str(self.rng_batch.randint(10**11, 10**12 - 1)),
            reason="duplicate_order",
            settled_in_batch=s.settlement_id,
        )
        self.refunds.append(rev)
        s.refunds.append(rev)

    def inject_unresolvable(self, s: Settlement):
        adj = Adjustment(
            adjustment_id=f"adj_{self._token(self.rng_batch)}",
            amount=money(-self.rng_batch.randint(500, 6000)),
            reason="unattributed_adjustment",
            settled_in_batch=s.settlement_id,
        )
        self.adjustments.append(adj)
        s.adjustments.append(adj)
        # The bank credit still maps to this settlement (batch_resolvable stays
        # True), but the adjustment has no attributable source record, so the
        # line items cannot be fully reconciled (components_resolvable = False).
        s.components_resolvable = False
        s.unresolvable_reason = "adjustment with no attributable source record"

    # ---- stage 4: render --------------------------------------------------

    def narration(self, s: Settlement) -> str:
        ref = s.bank_ref if s.utr_presence == "bank_ref" else s.utr
        base = f"NEFT-{ref}-RAZORPAY SOFTWARE PRIVATE LIM"

        if s.utr_presence == "truncated":
            # Drop the unique 8-digit suffix, leaving only the shared date
            # prefix (plus 0-4 stray digits), so it cannot be matched verbatim.
            keep = 5 + 11 + self.rng_render.randint(0, 4)
            return base[:keep] + "-"

        r = self.rng_render.random()
        if r < 0.2:
            return base.replace("-", "  ") + " -"
        return base + "-"

    def run(self):
        self.make_orders()
        self.make_refunds()
        self.make_disputes()
        self.make_settlements()
        return self

    def make_cashbook(self):
        """Create independent ERP evidence for normal operating cash activity."""
        if self.cashbook:
            return
        specs = [
            (8, "credit", "48500.00", "Northstar Marketplace", "channel remittance"),
            (19, "credit", "32000.00", "Acme Retail Partner", "partner incentive"),
            (37, "credit", "71500.00", "Bluebird Distribution", "trade receivable"),
            (58, "credit", "26800.00", "Summit Commerce", "channel remittance"),
            (12, "debit", "44250.00", "Nimbus Logistics", "approved freight invoice"),
            (27, "debit", "18750.00", "Cobalt Cloud Services", "approved infrastructure invoice"),
            (46, "debit", "62500.00", "Orchid Media Works", "approved campaign invoice"),
            (64, "debit", "23900.00", "Vertex Office Supply", "approved procurement invoice"),
        ]
        for index, (offset, direction, amount, counterparty, purpose) in enumerate(specs, start=1):
            event_date = self.start + timedelta(days=offset)
            reference = f"CB{self.seed % 10000:04d}{index:04d}"
            varied_amount = money(Decimal(amount) + self.rng_risk.randint(-4500, 4500))
            self.cashbook.append({
                "event_id": f"CBK{index:06d}",
                "event_timestamp_utc": datetime(
                    event_date.year, event_date.month, event_date.day, 9, index, tzinfo=timezone.utc
                ).isoformat(),
                "value_date": event_date.strftime("%d/%m/%Y"),
                "direction": direction,
                "amount": str(varied_amount),
                "counterparty": counterparty,
                "reference": reference,
                "purpose": purpose,
                "approved_by": "synthetic-controller-policy",
            })

    # ---- writers ----------------------------------------------------------

    @staticmethod
    def _dump(path, rows, cols):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})

    def write(self, outdir="data"):
        os.makedirs(outdir, exist_ok=True)
        d = self.dw
        self.make_cashbook()
        extracted_at = datetime.now(timezone.utc).isoformat()

        self._dump(f"{outdir}/orders.csv", [dict(
            id=o.order_id, amount=o.gross_amount, amount_paid=o.gross_amount,
            amount_due="0.00", currency="INR", receipt=o.receipt, offer_id="",
            status=o.status, attempts=o.attempts, notes="[]",
            created_at=d(o.created_at, i),
        ) for i, o in enumerate(self.orders)], [
            "id", "amount", "amount_paid", "amount_due", "currency", "receipt",
            "offer_id", "status", "attempts", "notes", "created_at"])

        refunded = {r.payment_id: r.amount for r in self.refunds}

        self._dump(f"{outdir}/payments.csv", [dict(
            id=p.payment_id, amount=p.amount, currency="INR",
            status="refunded" if p.payment_id in refunded else "captured",
            order_id=p.order_id, invoice_id="",
            international="1" if p.international else "0",
            method=p.method, amount_refunded=refunded.get(p.payment_id, "0.00"),
            amount_transferred="0.00",
            refund_status="full" if p.payment_id in refunded else "",
            captured="1", description="", card_id="", card="",
            bank=p.issuer, wallet="", vpa="", email="", contact="", notes="[]",
            fee=p.fee, tax=p.tax, error_code="", error_description="",
            created_at=d(p.captured_at, i), card_type=p.card_type,
            card_network="",
        ) for i, p in enumerate(self.payments)], [
            "id", "amount", "currency", "status", "order_id", "invoice_id",
            "international", "method", "amount_refunded", "amount_transferred",
            "refund_status", "captured", "description", "card_id", "card",
            "bank", "wallet", "vpa", "email", "contact", "notes", "fee", "tax",
            "error_code", "error_description", "created_at", "card_type",
            "card_network"])

        self._dump(f"{outdir}/refunds.csv", [dict(
            id=r.refund_id, amount=r.amount, currency="INR",
            payment_id=r.payment_id,
            notes=json.dumps({"refund_reason": r.reason}), receipt="",
            created_at=d(r.created_at, i), contact="", email="", arn=r.arn,
        ) for i, r in enumerate(self.refunds)], [
            "id", "amount", "currency", "payment_id", "notes", "receipt",
            "created_at", "contact", "email", "arn"])

        recon, k = [], 0
        for s in self.settlements:
            for p in s.payments:
                k += 1
                recon.append({
                    "transaction_entity": "payment", "entity_id": p.payment_id,
                    "amount": p.amount, "currency": "INR",
                    "fee (exclusive tax)": p.fee, "tax": p.tax,
                    "debit": "0.00", "credit": p.net,
                    "payment_method": p.method, "card_type": p.card_type,
                    "issuer_name": p.issuer,
                    "entity_created_at": d(p.captured_at, k),
                    "payment_captured_at": d(p.captured_at, k),
                    "payment_notes": "[]", "refund_notes": "", "arn": "",
                    "entity_description": "", "order_id": p.order_id,
                    "order_receipt": p.order_receipt, "order_notes": "[]",
                    "dispute_id": "", "dispute_created_at": "",
                    "dispute_reason": "", "settlement_id": s.settlement_id,
                    "settled_at": d(s.settled_at, k),
                    "settlement_utr": s.utr, "settled_by": "Razorpay"})
            for r in s.refunds:
                k += 1
                recon.append({
                    "transaction_entity": "refund", "entity_id": r.refund_id,
                    "amount": r.amount, "currency": "INR",
                    "fee (exclusive tax)": r.fee, "tax": r.tax,
                    "debit": r.debit, "credit": "0.00",
                    "payment_method": "", "card_type": "", "issuer_name": "",
                    "entity_created_at": d(r.created_at, k),
                    "payment_captured_at": "", "payment_notes": "",
                    "refund_notes": json.dumps({"refund_reason": r.reason}),
                    "arn": r.arn, "entity_description": "", "order_id": "",
                    "order_receipt": "", "order_notes": "", "dispute_id": "",
                    "dispute_created_at": "", "dispute_reason": "",
                    "settlement_id": s.settlement_id,
                    "settled_at": d(s.settled_at, k),
                    "settlement_utr": s.utr, "settled_by": "Razorpay"})
            for dp in s.disputes:
                k += 1
                recon.append({
                    "transaction_entity": "dispute", "entity_id": dp.dispute_id,
                    "amount": dp.amount, "currency": "INR",
                    "fee (exclusive tax)": "0.00", "tax": "0.00",
                    "debit": dp.amount, "credit": "0.00",
                    "payment_method": "card", "card_type": "", "issuer_name": "",
                    "entity_created_at": d(dp.created_at, k),
                    "payment_captured_at": "", "payment_notes": "",
                    "refund_notes": "", "arn": "", "entity_description": "",
                    "order_id": "", "order_receipt": "", "order_notes": "",
                    "dispute_id": dp.dispute_id,
                    "dispute_created_at": d(dp.created_at, k),
                    "dispute_reason": dp.reason,
                    "settlement_id": s.settlement_id,
                    "settled_at": d(s.settled_at, k),
                    "settlement_utr": s.utr, "settled_by": "Razorpay"})
            for a in s.adjustments:
                k += 1
                recon.append({
                    "transaction_entity": "adjustment",
                    "entity_id": a.adjustment_id, "amount": a.amount,
                    "currency": "INR", "fee (exclusive tax)": "0.00",
                    "tax": "0.00", "debit": abs(a.amount), "credit": "0.00",
                    "payment_method": "", "card_type": "", "issuer_name": "",
                    "entity_created_at": d(s.settled_at, k),
                    "payment_captured_at": "", "payment_notes": "",
                    "refund_notes": "", "arn": "",
                    "entity_description": a.reason, "order_id": "",
                    "order_receipt": "", "order_notes": "", "dispute_id": "",
                    "dispute_created_at": "", "dispute_reason": "",
                    "settlement_id": s.settlement_id,
                    "settled_at": d(s.settled_at, k),
                    "settlement_utr": s.utr, "settled_by": "Razorpay"})

        self._dump(f"{outdir}/settlement_recon.csv", recon, [
            "transaction_entity", "entity_id", "amount", "currency",
            "fee (exclusive tax)", "tax", "debit", "credit", "payment_method",
            "card_type", "issuer_name", "entity_created_at",
            "payment_captured_at", "payment_notes", "refund_notes", "arn",
            "entity_description", "order_id", "order_receipt", "order_notes",
            "dispute_id", "dispute_created_at", "dispute_reason",
            "settlement_id", "settled_at", "settlement_utr", "settled_by"])

        settlement_schedule = [
            {
                "settlement_id": settlement.settlement_id,
                "capture_date": settlement.capture_date.isoformat(),
                "capture_weekday": settlement.capture_date.strftime("%A"),
                "settlement_cycle": f"T+{settlement.scheduled_business_days}",
                "scheduled_business_days": settlement.scheduled_business_days,
                "settled_at": settlement.settled_at.isoformat(),
                "settled_weekday": settlement.settled_at.strftime("%A"),
                "working_day_path": working_day_path(
                    settlement.capture_date, settlement.scheduled_business_days
                ),
                "chronology_valid": (
                    settlement.settled_at
                    == add_working_days(
                        settlement.capture_date, settlement.scheduled_business_days
                    )
                ),
            }
            for settlement in sorted(self.settlements, key=lambda item: item.capture_date)
        ]
        self._dump(f"{outdir}/settlement_schedule.csv", settlement_schedule, [
            "settlement_id", "capture_date", "capture_weekday", "settlement_cycle",
            "scheduled_business_days", "settled_at", "settled_weekday",
            "working_day_path", "chronology_valid",
        ])

        ordered = sorted(self.settlements, key=lambda x: x.settled_at)
        bank_candidates = []
        topology_pool = [
            settlement for settlement in ordered
            if settlement.credit > Decimal("100.00")
            and settlement.batch_resolvable
            and settlement.components_resolvable
        ]
        # Keep 75 bank nodes and 75 settlement nodes while making grouped
        # topologies a substantial part of the flagship batch:
        #   13 x 1:1, 12 x 1:N, 12 x N:1, 13 x N:M = 50 groups.
        # Component-level exceptions stay in 1:1 groups so one bad component
        # cannot manufacture several bank-level risk labels.
        required_groupable = 62
        if len(topology_pool) < required_groupable:
            raise RuntimeError(
                "not enough clean positive settlements to plant balanced topology coverage"
            )
        grouped_pool = topology_pool[:required_groupable]
        aggregate_groups = [grouped_pool[index:index + 2] for index in range(0, 24, 2)]
        split_groups = [[item] for item in grouped_pool[24:36]]
        many_to_many_groups = [
            grouped_pool[index:index + 2] for index in range(36, 62, 2)
        ]
        grouped_settlement_ids = {
            settlement.settlement_id
            for group in [*aggregate_groups, *split_groups, *many_to_many_groups]
            for settlement in group
        }

        def settlement_bank_row(
            settlements: list[Settlement],
            observed_amount: Decimal,
            topology: str,
            group_key: str,
            sequence: int,
            part: int = 1,
            parts: int = 1,
            posting_date: date | None = None,
        ):
            settled_at = max(
                max(item.settled_at for item in settlements),
                posting_date or max(item.settled_at for item in settlements),
            )
            timestamp = datetime(
                settled_at.year, settled_at.month, settled_at.day,
                10 + (sequence % 7), (sequence * 11 + part) % 60, tzinfo=timezone.utc,
            )
            grouped = len(settlements) > 1 or parts > 1
            if grouped:
                references = "-".join(item.utr for item in settlements)
                narration = f"RZP-{topology.replace(':', 'X')}-PART{part}OF{parts}-{references}"
            else:
                narration = self.narration(settlements[0])
            clean = all(item.components_resolvable for item in settlements)
            return {
                "_timestamp": timestamp,
                "_settlements": settlements,
                "_group_key": group_key,
                "_topology": topology,
                "_risk": {
                    "is_dubious": not clean,
                    "anomaly_type": (
                        "unattributed_settlement_component"
                        if not clean else "none"
                    ),
                    "truth_text": (
                        "Settlement contains an adjustment without independent source evidence."
                        if not clean
                        else f"Verified synthetic Razorpay reconciliation group with {topology} topology."
                    ),
                },
                "txn_date": settled_at.strftime("%d/%m/%Y"),
                "value_date": settled_at.strftime("%d/%m/%Y"),
                "txn_timestamp_utc": timestamp.isoformat(),
                "transaction_type": "PAYMENT_GATEWAY_SETTLEMENT",
                "narration": narration,
                "ref_no": group_key,
                "debit": abs(observed_amount) if observed_amount < 0 else "",
                "credit": observed_amount if observed_amount > 0 else "",
            }

        sequence = 0
        for settlement in ordered:
            if settlement.settlement_id in grouped_settlement_ids:
                continue
            bank_candidates.append(settlement_bank_row(
                [settlement], settlement.credit, "1:1",
                f"RZP-11-{settlement.settlement_id}", sequence,
            ))
            sequence += 1

        for group_index, aggregate_group in enumerate(aggregate_groups, start=1):
            aggregate_total = money(sum(
                (item.credit for item in aggregate_group), Decimal("0")
            ))
            bank_candidates.append(settlement_bank_row(
                aggregate_group, aggregate_total, "1:N",
                f"RZP-GROUP-1N-{group_index:02d}", sequence,
            ))
            sequence += 1

        split_amounts_by_index: dict[int, tuple[Decimal, Decimal]] = {}
        split_posting_date_by_index: dict[int, date] = {}
        for pair_start in range(0, len(split_groups), 2):
            first_total = split_groups[pair_start][0].credit
            second_total = split_groups[pair_start + 1][0].credit
            bridge_ratio = Decimal("0.27") + Decimal(pair_start % 3) / Decimal("100")
            bridge = money(min(first_total, second_total) * bridge_ratio)
            split_amounts_by_index[pair_start] = (
                money(first_total - bridge), bridge
            )
            split_amounts_by_index[pair_start + 1] = (
                bridge, money(second_total - bridge)
            )
            shared_posting_date = max(
                split_groups[pair_start][0].settled_at,
                split_groups[pair_start + 1][0].settled_at,
            )
            split_posting_date_by_index[pair_start] = shared_posting_date
            split_posting_date_by_index[pair_start + 1] = shared_posting_date

        for zero_index, split_group in enumerate(split_groups):
            group_index = zero_index + 1
            split_amounts = split_amounts_by_index[zero_index]
            for part, amount in enumerate(split_amounts, start=1):
                bank_candidates.append(settlement_bank_row(
                    split_group, amount, "N:1",
                    f"RZP-GROUP-N1-{group_index:02d}", sequence,
                    part=part, parts=2,
                    posting_date=split_posting_date_by_index[zero_index],
                ))
                sequence += 1

        def irreducible_split(
            total: Decimal, constituent_amounts: list[Decimal], ratio: Decimal
        ) -> tuple[Decimal, Decimal]:
            """Split a total without accidentally embedding a smaller 1:1 match."""
            first = money(total * ratio)
            second = money(total - first)
            forbidden = {money(item) for item in constituent_amounts}
            while first <= 0 or second <= 0 or first in forbidden or second in forbidden:
                first = money(first + Decimal("0.01"))
                second = money(total - first)
            return first, second

        many_amounts_by_index: dict[int, tuple[Decimal, Decimal]] = {}
        many_posting_date_by_index: dict[int, date] = {}
        for pair_start in range(0, len(many_to_many_groups) - 1, 2):
            first_group = many_to_many_groups[pair_start]
            second_group = many_to_many_groups[pair_start + 1]
            first_total = money(sum((item.credit for item in first_group), Decimal("0")))
            second_total = money(sum((item.credit for item in second_group), Decimal("0")))
            cross_total = money(first_group[0].credit + second_group[0].credit)
            lower = max(Decimal("0.01"), money(cross_total - second_total + Decimal("0.01")))
            upper = min(money(first_total - Decimal("0.01")), money(cross_total - Decimal("0.01")))
            first_part = money((lower + upper) / Decimal("2"))
            second_part = money(cross_total - first_part)
            forbidden = {
                money(item.credit) for item in [*first_group, *second_group]
            }
            while (
                first_part in forbidden
                or money(first_total - first_part) in forbidden
                or second_part in forbidden
                or money(second_total - second_part) in forbidden
            ):
                first_part = money(first_part + Decimal("0.01"))
                second_part = money(cross_total - first_part)
            many_amounts_by_index[pair_start] = (
                first_part, money(first_total - first_part)
            )
            many_amounts_by_index[pair_start + 1] = (
                second_part, money(second_total - second_part)
            )
            shared_posting_date = max(
                item.settled_at for item in [*first_group, *second_group]
            )
            many_posting_date_by_index[pair_start] = shared_posting_date
            many_posting_date_by_index[pair_start + 1] = shared_posting_date

        last_many_index = len(many_to_many_groups) - 1
        last_many_group = many_to_many_groups[last_many_index]
        last_many_total = money(sum((item.credit for item in last_many_group), Decimal("0")))
        many_amounts_by_index[last_many_index] = irreducible_split(
            last_many_total,
            [item.credit for item in last_many_group],
            Decimal("0.37"),
        )
        many_posting_date_by_index[last_many_index] = max(
            item.settled_at for item in last_many_group
        )

        for zero_index, many_group in enumerate(many_to_many_groups):
            group_index = zero_index + 1
            many_total = money(sum((item.credit for item in many_group), Decimal("0")))
            many_amounts = many_amounts_by_index[zero_index]
            for part, amount in enumerate(many_amounts, start=1):
                bank_candidates.append(settlement_bank_row(
                    many_group, amount, "N:M",
                    f"RZP-GROUP-NM-{group_index:02d}", sequence,
                    part=part, parts=2,
                    posting_date=many_posting_date_by_index[zero_index],
                ))
                sequence += 1

        def operating_row(event, timestamp, amount=None, anomaly_type="none", truth_text=""):
            direction = event["direction"]
            observed = money(amount if amount is not None else event["amount"])
            prefix = "IMPS" if direction == "credit" else "NEFT"
            return {
                "_timestamp": timestamp,
                "_risk": {
                    "is_dubious": anomaly_type != "none",
                    "anomaly_type": anomaly_type,
                    "truth_text": truth_text or "Supported by an approved ERP cashbook event.",
                },
                "txn_date": timestamp.strftime("%d/%m/%Y"),
                "value_date": timestamp.strftime("%d/%m/%Y"),
                "txn_timestamp_utc": timestamp.isoformat(),
                "transaction_type": "OPERATING_CREDIT" if direction == "credit" else "OPERATING_DEBIT",
                "narration": f"{prefix}-{event['reference']}-{event['counterparty'].upper()}",
                "ref_no": event["reference"],
                "debit": observed if direction == "debit" else "",
                "credit": observed if direction == "credit" else "",
            }

        # Six supported observations: three credits and three debits.
        for index in (0, 1, 2, 4, 5, 6):
            event = self.cashbook[index]
            event_dt = datetime.fromisoformat(event["event_timestamp_utc"])
            bank_candidates.append(operating_row(event, event_dt + timedelta(hours=5)))

        # Amount mismatches in both directions: the cashbook remains the independent expectation.
        for index in (3, 7):
            event = self.cashbook[index]
            event_dt = datetime.fromisoformat(event["event_timestamp_utc"])
            delta = money(self.rng_risk.randint(350, 1450))
            observed = money(event["amount"]) + delta
            bank_candidates.append(operating_row(
                event,
                event_dt + timedelta(hours=5),
                amount=observed,
                anomaly_type="amount_mismatch",
                truth_text=(
                    f"Bank {event['direction']} is INR {delta:.2f} above the approved cashbook amount."
                ),
            ))

        # Duplicate a supported credit and debit after their legitimate observation.
        for index in (0, 4):
            event = self.cashbook[index]
            event_dt = datetime.fromisoformat(event["event_timestamp_utc"])
            bank_candidates.append(operating_row(
                event,
                event_dt + timedelta(hours=5, minutes=17),
                anomaly_type="duplicate_reference",
                truth_text="The same approved cashbook reference appears twice in the bank statement.",
            ))

        # Unsupported credit and debit have no corresponding ERP evidence at all.
        for offset, direction, base_amount, reference, counterparty in (
            (33, "credit", "38900.00", "UNSUPCR2026", "UNKNOWN ORIGINATOR"),
            (52, "debit", "54750.00", "UNSUPDR2026", "UNKNOWN BENEFICIARY"),
        ):
            event_date = self.start + timedelta(days=offset)
            timestamp = datetime(
                event_date.year, event_date.month, event_date.day, 16, 40, tzinfo=timezone.utc
            )
            synthetic_event = {
                "direction": direction,
                "amount": str(money(Decimal(base_amount) + self.rng_risk.randint(-5000, 5000))),
                "reference": reference,
                "counterparty": counterparty,
            }
            bank_candidates.append(operating_row(
                synthetic_event,
                timestamp,
                anomaly_type="unsupported_transaction",
                truth_text=f"No approved cashbook evidence exists for this {direction}.",
            ))

        bank_candidates.sort(key=lambda row: (row["_timestamp"], row.get("ref_no", "")))
        bank, risk_truth, balance = [], [], Decimal("250000.00")
        settlement_bank_ids = defaultdict(list)
        bank_groups = defaultdict(list)
        for index, row in enumerate(bank_candidates):
            bank_id = f"BNK{index:06d}"
            debit = money(row.get("debit") or "0")
            credit = money(row.get("credit") or "0")
            balance = money(balance + credit - debit)
            row["bank_txn_id"] = bank_id
            row["balance"] = balance
            bank.append(row)
            if row.get("_settlements"):
                bank_groups[row["_group_key"]].append(row)
                for settlement in row["_settlements"]:
                    settlement_bank_ids[settlement.settlement_id].append(bank_id)
            risk_truth.append({
                "bank_txn_id": bank_id,
                "is_dubious": row["_risk"]["is_dubious"],
                "direction": "credit" if credit > 0 else "debit",
                "anomaly_type": row["_risk"]["anomaly_type"],
                "amount": str(credit if credit > 0 else debit),
                "transaction_timestamp_utc": row["txn_timestamp_utc"],
                "truth_text": row["_risk"]["truth_text"],
            })
        self._dump(f"{outdir}/bank_statement.csv", bank, [
            "bank_txn_id", "txn_date", "value_date", "txn_timestamp_utc",
            "transaction_type", "narration", "ref_no", "debit", "credit", "balance"])

        self._dump(f"{outdir}/cashbook.csv", self.cashbook, [
            "event_id", "event_timestamp_utc", "value_date", "direction", "amount",
            "counterparty", "reference", "purpose", "approved_by"])

        truth = []
        for row in bank:
            settlements = row.get("_settlements") or []
            if not settlements:
                continue
            group_rows = bank_groups[row["_group_key"]]
            bank_ids = [item["bank_txn_id"] for item in group_rows]
            settlement_ids = [item.settlement_id for item in settlements]
            group_total = money(sum(
                (money(item.get("credit") or "0") - money(item.get("debit") or "0") for item in group_rows),
                Decimal("0"),
            ))
            truth.append(dict(
                bank_txn_id=row["bank_txn_id"], bank_txn_ids=bank_ids,
                utr=settlements[0].utr, utrs=[item.utr for item in settlements],
                settlement_id=settlement_ids[0], settlement_ids=settlement_ids,
                topology=row["_topology"], credit=str(group_total),
                bank_entry_amount=str(money(row.get("credit") or "0") - money(row.get("debit") or "0")),
                tier=max(item.tier for item in settlements),
                component_payments=[p.payment_id for item in settlements for p in item.payments],
                component_refunds=[r.refund_id for item in settlements for r in item.refunds],
                component_disputes=[x.dispute_id for item in settlements for x in item.disputes],
                component_adjustments=[a.adjustment_id for item in settlements for a in item.adjustments],
                expected_fee_total=str(money(sum(
                    (p.fee + p.tax for item in settlements for p in item.payments), Decimal("0")))),
                expected_refund_fee_total=str(money(sum(
                    (r.fee + r.tax for item in settlements for r in item.refunds), Decimal("0")))),
                rate_keys_used=sorted({p.rate_key for item in settlements for p in item.payments}),
                batch_resolvable=all(item.batch_resolvable for item in settlements),
                components_resolvable=all(item.components_resolvable for item in settlements),
                unresolvable_reason="; ".join(
                    item.unresolvable_reason for item in settlements if item.unresolvable_reason
                ) or None,
                utr_presence=(settlements[0].utr_presence if len(settlements) == 1 else "grouped"),
            ))

        with open(f"{outdir}/ground_truth.json", "w") as f:
            json.dump(truth, f, indent=2, default=str)
        with open(f"{outdir}/risk_truth.json", "w") as f:
            json.dump(risk_truth, f, indent=2, default=str)
        with open(f"{outdir}/seed.txt", "w") as f:
            f.write(str(self.seed))

        coverage_end = max(
            [s.settled_at for s in self.settlements]
            + [datetime.fromisoformat(item["event_timestamp_utc"]).date() for item in self.cashbook]
        )
        source_rows = {
            "orders.csv": len(self.orders),
            "payments.csv": len(self.payments),
            "refunds.csv": len(self.refunds),
            "settlement_recon.csv": len(recon),
            "settlement_schedule.csv": len(settlement_schedule),
            "bank_statement.csv": len(bank),
            "cashbook.csv": len(self.cashbook),
            "ground_truth.json": len(truth),
            "risk_truth.json": len(risk_truth),
        }
        provenance = {
            "dataset_id": f"synthetic-finance-controller-{self.seed}",
            "synthetic": True,
            "seed": self.seed,
            "extracted_at_utc": extracted_at,
            "coverage_start": self.start.isoformat(),
            "coverage_end": coverage_end.isoformat(),
            "timezone": "UTC",
            "ground_truth_usage": "evaluation_only; never read by matching or risk-detection rules",
            "augmentation_note": (
                "Synthetic bank and ERP cashbook activity includes labeled credit and debit "
                "duplicates, amount mismatches, unsupported transactions, and planted 1:1, "
                "1:N, N:1, and N:M settlement reconciliation topologies. Settlement dates "
                "follow an explicit synthetic T+1/T+2 Monday-Friday working-day policy; "
                "this is test policy evidence, not a universal merchant contract."
            ),
            "sources": [
                {
                    "name": name,
                    "rows": rows,
                    "extracted_at_utc": extracted_at,
                    "coverage_start": self.start.isoformat(),
                    "coverage_end": coverage_end.isoformat(),
                    "source_system": (
                        "Synthetic bank export" if name == "bank_statement.csv"
                        else "Synthetic ERP cashbook" if name == "cashbook.csv"
                        else "Synthetic T+1/T+2 working-day policy ledger"
                        if name == "settlement_schedule.csv"
                        else "Evaluation truth (controller-blind)" if "truth" in name
                        else "Official-schema-shaped Razorpay export"
                    ),
                }
                for name, rows in source_rows.items()
            ],
        }
        with open(f"{outdir}/provenance.json", "w") as f:
            json.dump(provenance, f, indent=2)
        return truth


def self_check(gen: Generator, outdir="data"):
    """
    Two independent checks:
      1. every batch nets to zero against its own components
      2. the rendered recon CSV's (credit - debit) per settlement equals the
         bank credit, which catches the gross-versus-net convention bug
    """
    import collections
    errs = []

    for s in gen.settlements:
        rhs = money(
            sum((p.amount - p.fee - p.tax for p in s.payments), Decimal("0"))
            - sum((r.amount + r.fee + r.tax for r in s.refunds), Decimal("0"))
            - sum((x.amount for x in s.disputes), Decimal("0"))
            + sum((a.amount for a in s.adjustments), Decimal("0")))
        if s.credit != rhs:
            errs.append(f"batch {s.settlement_id} does not net: {s.credit} vs {rhs}")
        if any(payment.captured_at > s.settled_at for payment in s.payments):
            errs.append(f"payment chronology is invalid for {s.settlement_id}")
        if any(refund.created_at > s.settled_at for refund in s.refunds):
            errs.append(f"refund chronology is invalid for {s.settlement_id}")
        if any(dispute.created_at > s.settled_at for dispute in s.disputes):
            errs.append(f"dispute chronology is invalid for {s.settlement_id}")

    with open(f"{outdir}/settlement_schedule.csv") as handle:
        schedule_rows = list(csv.DictReader(handle))
    schedule_by_id = {row["settlement_id"]: row for row in schedule_rows}
    cycles = {row["settlement_cycle"] for row in schedule_rows}
    if cycles != {"T+1", "T+2"}:
        errs.append(f"settlement schedule must contain both T+1 and T+2; found {sorted(cycles)}")
    thursday_t2 = []
    for row in schedule_rows:
        captured = date.fromisoformat(row["capture_date"])
        settled = date.fromisoformat(row["settled_at"])
        business_days = int(row["scheduled_business_days"])
        expected = add_working_days(captured, business_days)
        if settled != expected or not is_working_day(settled) or settled < captured:
            errs.append(
                f"settlement schedule chronology invalid for {row['settlement_id']}: "
                f"{captured} T+{business_days} -> {settled}, expected {expected}"
            )
        if captured.weekday() == 3 and business_days == 2:
            thursday_t2.append(row)
            if settled.weekday() != 0:
                errs.append(
                    f"Thursday T+2 must settle Monday for {row['settlement_id']}, got {settled}"
                )
    if not thursday_t2:
        errs.append("settlement schedule lacks a Thursday T+2 to Monday proof case")

    totals = collections.defaultdict(Decimal)
    with open(f"{outdir}/settlement_recon.csv") as f:
        for row in csv.DictReader(f):
            totals[row["settlement_id"]] += (
                Decimal(row["credit"] or "0") - Decimal(row["debit"] or "0"))

    for s in gen.settlements:
        got = money(totals[s.settlement_id])
        if got != s.credit:
            errs.append(
                f"recon csv for {s.settlement_id} sums to {got}, "
                f"bank credit is {s.credit}")

    with open(f"{outdir}/bank_statement.csv") as handle:
        bank_rows = list(csv.DictReader(handle))
    previous = None
    for row in bank_rows:
        debit = money(row.get("debit") or "0")
        credit = money(row.get("credit") or "0")
        balance = money(row.get("balance") or "0")
        if (debit > 0) == (credit > 0):
            errs.append(f"bank row {row['bank_txn_id']} does not have exactly one positive side")
        if previous is not None and money(previous + credit - debit) != balance:
            errs.append(f"bank row {row['bank_txn_id']} breaks the balance roll-forward")
        previous = balance

    with open(f"{outdir}/risk_truth.json") as handle:
        risk_truth = json.load(handle)
    planted = [row for row in risk_truth if row["is_dubious"]]
    if not planted or {row["direction"] for row in planted} != {"credit", "debit"}:
        errs.append("risk truth must include dubious credits and debits")
    expected_classes = {
        "duplicate_reference", "amount_mismatch", "unsupported_transaction",
        "unattributed_settlement_component",
    }
    if {row["anomaly_type"] for row in planted} != expected_classes:
        errs.append("risk truth anomaly-class coverage is incomplete")

    with open(f"{outdir}/ground_truth.json") as handle:
        reconciliation_truth = json.load(handle)
    observed_topologies = {row.get("topology") for row in reconciliation_truth}
    required_topologies = {"1:1", "1:N", "N:1", "N:M"}
    if not required_topologies.issubset(observed_topologies):
        errs.append(
            "reconciliation topology coverage is incomplete: "
            + ", ".join(sorted(required_topologies - observed_topologies))
        )

    unique_topology_groups = {
        (tuple(item.get("bank_txn_ids", [])), tuple(item.get("settlement_ids", [])), item.get("topology"))
        for item in reconciliation_truth
    }
    topology_group_counts = collections.Counter(item[2] for item in unique_topology_groups)
    expected_topology_group_counts = {"1:1": 13, "1:N": 12, "N:1": 12, "N:M": 13}
    if dict(topology_group_counts) != expected_topology_group_counts:
        errs.append(
            "flagship topology mix is unbalanced: "
            f"{dict(topology_group_counts)} vs {expected_topology_group_counts}"
        )

    bank_by_id = {row["bank_txn_id"]: row for row in bank_rows}
    settlement_by_id = {item.settlement_id: item for item in gen.settlements}
    checked_groups = set()
    for item in reconciliation_truth:
        signature = (tuple(item.get("bank_txn_ids", [])), tuple(item.get("settlement_ids", [])))
        if signature in checked_groups:
            continue
        checked_groups.add(signature)
        bank_total = money(sum(
            (
                money(bank_by_id[identifier].get("credit") or "0")
                - money(bank_by_id[identifier].get("debit") or "0")
                for identifier in signature[0]
            ),
            Decimal("0"),
        ))
        settlement_total = money(sum(
            (settlement_by_id[identifier].credit for identifier in signature[1]),
            Decimal("0"),
        ))
        if bank_total != settlement_total:
            errs.append(
                f"topology group {signature} does not conserve money: "
                f"{bank_total} vs {settlement_total}"
            )
        latest_settlement = max(
            date.fromisoformat(schedule_by_id[identifier]["settled_at"])
            for identifier in signature[1]
        )
        for identifier in signature[0]:
            bank_value_date = datetime.strptime(
                bank_by_id[identifier]["value_date"], "%d/%m/%Y"
            ).date()
            if bank_value_date < latest_settlement:
                errs.append(
                    f"bank row {identifier} predates its latest settlement: "
                    f"{bank_value_date} < {latest_settlement}"
                )
    return errs


if __name__ == "__main__":
    g = Generator().run()
    truth = g.write()
    errs = self_check(g)

    tiers = {}
    for t in truth:
        tiers[t["tier"]] = tiers.get(t["tier"], 0) + 1

    presence = {}
    for t in truth:
        presence[t["utr_presence"]] = presence.get(t["utr_presence"], 0) + 1

    recon_rows = sum(1 for _ in open("data/settlement_recon.csv")) - 1
    print(f"orders            {len(g.orders)}")
    print(f"payments          {len(g.payments)}")
    print(f"refunds           {len(g.refunds)}")
    print(f"disputes          {len(g.disputes)}")
    print(f"adjustments       {len(g.adjustments)}")
    print(f"recon line items  {recon_rows}")
    print(f"bank credits      {len(truth)}")
    print(f"batch unresolvable {sum(1 for t in truth if not t['batch_resolvable'])}")
    print(f"component unresolvable {sum(1 for t in truth if not t['components_resolvable'])}")
    print(f"utr presence      {dict(sorted(presence.items()))}")
    print(f"tier spread       {dict(sorted(tiers.items()))}")
    print(f"self-check errors {len(errs)}")
    for e in errs[:5]:
        print("  ", e)
