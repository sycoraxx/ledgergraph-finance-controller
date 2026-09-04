"""Deterministic global reconciliation over a canonical money-event graph.

Fuzzy evidence is permitted only while generating candidates. Selection is a
global, exact set-packing problem with hard signed-money conservation and
one-use constraints. Tied optimal solutions abstain on the ambiguous edges.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any, Iterable

from ortools.sat.python import cp_model

from .l1_search import parse_date_candidates
from .membership_solver import MembershipItem, solve_unique_membership
from .subset_sum import SubsetSumIndex, build_subset_sum_index, reachable_totals_by_size


DEFAULT_SELECTION_THRESHOLD = 65
MAX_GROUP_HYPOTHESES_PER_TOTAL = 64
MAX_DP_STATES = 250_000
DEFAULT_CP_SAT_TIME_LIMIT_SECONDS = 5.0
MAX_DECLARED_GROUP_MEMBERS_PER_SIDE = 1000
MAX_INFERRED_GROUP_MEMBERS = 100
MAX_MEMBERSHIP_POOL_SIZE = 1000
DEFAULT_MEMBERSHIP_TIME_LIMIT_SECONDS = 2.0
DECLARED_GROUP_FIELDS = ("reconciliation_group_id", "payout_id", "batch_id")


def normalize_reference(value: str | None) -> str:
    return "".join(character for character in (value or "").upper() if character.isalnum())


def bounded_edit_distance(left: str, right: str, limit: int = 2) -> int | None:
    """Return Levenshtein distance only when it is at most ``limit``."""
    if abs(len(left) - len(right)) > limit:
        return None
    previous = list(range(len(right) + 1))
    for row_index, left_character in enumerate(left, start=1):
        current = [row_index]
        row_minimum = row_index
        for column_index, right_character in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column_index] + 1,
                previous[column_index - 1] + (left_character != right_character),
            ))
            row_minimum = min(row_minimum, current[-1])
        if row_minimum > limit:
            return None
        previous = current
    return previous[-1] if previous[-1] <= limit else None


def signed_bank_amount(row: dict[str, str]) -> Decimal:
    return Decimal(row.get("credit") or "0") - Decimal(row.get("debit") or "0")


def minimum_date_distance(left: set[str], right: set[str]) -> int | None:
    if not left or not right:
        return None
    return min(
        abs((date.fromisoformat(left_value) - date.fromisoformat(right_value)).days)
        for left_value in left
        for right_value in right
    )


def bank_dates(row: dict[str, str]) -> set[str]:
    return parse_date_candidates(row.get("value_date")) or parse_date_candidates(row.get("txn_date"))


def reference_evidence(narration: str, utr: str) -> list[dict[str, Any]]:
    raw_narration = (narration or "").upper()
    raw_utr = (utr or "").upper()
    if not raw_utr:
        return []
    if raw_utr in raw_narration:
        return [{"feature": "full_utr_exact", "points": 100, "detail": "full UTR appears in narration"}]
    normalized_narration = normalize_reference(raw_narration)
    normalized_utr = normalize_reference(raw_utr)
    if normalized_utr and normalized_utr in normalized_narration:
        return [{"feature": "normalized_utr_exact", "points": 90, "detail": "UTR agrees after punctuation normalization"}]
    tokens = [normalize_reference(token) for token in raw_narration.replace("/", " ").replace("-", " ").split()]
    distances = [
        distance
        for token in tokens
        if abs(len(token) - len(normalized_utr)) <= 2
        for distance in [bounded_edit_distance(token, normalized_utr, 2)]
        if distance is not None
    ]
    if distances:
        distance = min(distances)
        return [{
            "feature": "utr_edit_distance",
            "points": 35 if distance == 1 else 20,
            "detail": f"closest narration token is edit distance {distance} from UTR",
        }]
    if len(normalized_utr) >= 11 and normalized_utr[:11] in normalized_narration:
        return [{"feature": "utr_prefix_exact", "points": 15, "detail": "exact 11-character UTR prefix appears"}]
    return []


def pair_support_features(
    bank: dict[str, str], settlement: dict[str, Any]
) -> list[dict[str, Any]]:
    features = list(reference_evidence(bank.get("narration", ""), settlement.get("utr", "")))
    distance = minimum_date_distance(bank_dates(bank), set(settlement.get("settled_dates", set())))
    if distance == 0:
        features.append({"feature": "settlement_date_exact", "points": 20, "detail": "bank and settlement dates agree"})
    elif distance is not None and distance <= 2:
        features.append({"feature": "posting_window", "points": 14, "detail": f"bank posted {distance} day(s) from settlement"})
    elif distance is not None and distance <= 5:
        features.append({"feature": "extended_posting_window", "points": 5, "detail": f"bank posted {distance} days from settlement"})
    return features


def feature_score(features: Iterable[dict[str, Any]]) -> int:
    return sum(int(feature["points"]) for feature in features)


def candidate_id(kind: str, bank_ids: tuple[str, ...], settlement_ids: tuple[str, ...]) -> str:
    # Group membership is unordered. Canonical IDs prevent the same hyperedge
    # being emitted twice as A+B and B+A, which would create a false tied optimum.
    if len(bank_ids) + len(settlement_ids) > 100:
        canonical = "\0".join((kind, *sorted(bank_ids), "=>", *sorted(settlement_ids)))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"{kind}:large:{len(bank_ids)}x{len(settlement_ids)}:{digest}"
    return f"{kind}:{'+'.join(sorted(bank_ids))}=>{'+'.join(sorted(settlement_ids))}"


def declared_group_key(item: dict[str, Any]) -> str | None:
    """Return a dedicated cross-source membership key, never a fuzzy reference."""
    for field in DECLARED_GROUP_FIELDS:
        if item.get(f"{field}_conflict"):
            return None
        value = str(item.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return None


def topology_for(bank_count: int, settlement_count: int) -> str:
    if bank_count == 1 and settlement_count == 1:
        return "1:1"
    if bank_count == 1:
        return "1:N"
    if settlement_count == 1:
        return "N:1"
    return "N:M"


def single_candidate(
    bank: dict[str, str],
    settlement_id: str,
    settlement: dict[str, Any],
    *,
    exact_amount_frequency: int,
    support_features: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    bank_amount = signed_bank_amount(bank)
    settlement_amount = Decimal(settlement["net"])
    same_direction = bank_amount == 0 or settlement_amount == 0 or (bank_amount > 0) == (settlement_amount > 0)
    amount_exact = bank_amount == settlement_amount
    features: list[dict[str, Any]] = []
    if amount_exact:
        features.append({"feature": "signed_amount_exact", "points": 50, "detail": "signed bank amount equals settlement net"})
        if exact_amount_frequency == 1:
            features.append({"feature": "globally_unique_amount", "points": 5, "detail": "only one settlement has this signed net"})
    features.extend(support_features if support_features is not None else pair_support_features(bank, settlement))
    reference_points = sum(item["points"] for item in features if "utr" in item["feature"])
    if not amount_exact and not reference_points:
        return None
    residual = bank_amount - settlement_amount
    eligible = same_direction and amount_exact
    blockers = []
    if not same_direction:
        blockers.append("direction_conflict")
    if not amount_exact:
        blockers.append("money_conservation_failed")
    bank_ids, settlement_ids = (bank["bank_txn_id"],), (settlement_id,)
    return {
        "candidate_id": candidate_id("one_to_one", bank_ids, settlement_ids),
        "kind": "one_to_one",
        "topology": "1:1",
        "bank_ids": list(bank_ids),
        "settlement_ids": list(settlement_ids),
        "bank_total": str(bank_amount),
        "settlement_total": str(settlement_amount),
        "residual": str(residual),
        "features": features,
        "evidence_score": feature_score(features),
        "eligible": eligible,
        "blockers": blockers,
    }


def group_candidate(
    kind: str,
    banks: list[dict[str, str]],
    settlement_items: list[tuple[str, dict[str, Any]]],
    *,
    unique_combination: bool,
    declared_membership_key: str | None = None,
) -> dict[str, Any]:
    bank_total = sum((signed_bank_amount(row) for row in banks), Decimal("0"))
    settlement_total = sum((Decimal(item["net"]) for _, item in settlement_items), Decimal("0"))
    amount_exact = bank_total == settlement_total
    features: list[dict[str, Any]] = [{
        "feature": "declared_group_structure" if declared_membership_key else "bounded_group_structure",
        "points": 35 if declared_membership_key else 10,
        "detail": (
            f"the dedicated group key {declared_membership_key!r} agrees across both sources"
            if declared_membership_key
            else f"bounded {kind.replace('_', ' ')} hypothesis"
        ),
    }]
    if amount_exact:
        features.insert(0, {"feature": "signed_group_amount_exact", "points": 50, "detail": "grouped signed amounts conserve money exactly"})
    if unique_combination and amount_exact and not declared_membership_key:
        features.append({"feature": "unique_group_sum", "points": 2, "detail": "only one bounded group produces this exact total; uniqueness is weak corroboration"})
    combined_bank_dates = set().union(*(bank_dates(bank) for bank in banks))
    combined_settlement_dates = set().union(*(
        set(settlement.get("settled_dates", set())) for _, settlement in settlement_items
    ))
    group_distance = minimum_date_distance(combined_bank_dates, combined_settlement_dates)
    if group_distance == 0:
        features.append({"feature": "group_date_exact", "points": 15, "detail": "at least one bank/settlement date agrees exactly"})
    elif group_distance is not None and group_distance <= 2:
        features.append({"feature": "group_posting_window", "points": 10, "detail": "group falls inside the two-day posting window"})
    canonical_settlement_dates = [
        date.fromisoformat(str(settlement.get("canonical_settled_at")))
        for _, settlement in settlement_items
        if settlement.get("canonical_settled_at")
    ]
    chronology_valid = True
    if canonical_settlement_dates:
        latest_settlement_date = max(canonical_settlement_dates)
        chronology_valid = all(
            not bank_dates(bank)
            or max(date.fromisoformat(value) for value in bank_dates(bank)) >= latest_settlement_date
            for bank in banks
        )
    reference_links = [] if declared_membership_key else [
        evidence
        for bank in banks
        for _, settlement in settlement_items
        for evidence in [reference_evidence(bank.get("narration", ""), settlement.get("utr", ""))]
        if evidence
    ]
    if reference_links:
        strong_links = sum(max(item["points"] for item in evidence) >= 35 for evidence in reference_links)
        weak_links = len(reference_links) - strong_links
        reference_points = min(40, 10 * strong_links + weak_links)
        features.append({
            "feature": "group_reference_support",
            "points": reference_points,
            "detail": f"{strong_links} strong and {weak_links} weak grouped reference link(s) found",
        })
    bank_ids = tuple(row["bank_txn_id"] for row in banks)
    settlement_ids = tuple(identifier for identifier, _ in settlement_items)
    blockers = []
    if not amount_exact:
        blockers.append("money_conservation_failed")
    if not chronology_valid:
        blockers.append("chronology_conflict")
    candidate = {
        "candidate_id": candidate_id(kind, bank_ids, settlement_ids),
        "kind": kind,
        "topology": topology_for(len(bank_ids), len(settlement_ids)),
        "bank_ids": list(bank_ids),
        "settlement_ids": list(settlement_ids),
        "bank_total": str(bank_total),
        "settlement_total": str(settlement_total),
        "residual": str(bank_total - settlement_total),
        "features": features,
        "evidence_score": feature_score(features),
        "eligible": amount_exact and chronology_valid,
        "blockers": blockers,
    }
    if declared_membership_key:
        candidate["generation_strategy"] = "declared_cross_source_membership"
        candidate["declared_membership_key"] = declared_membership_key
        candidate["candidate_generation_complete"] = True
    return candidate


def has_money_conserving_proper_subgroup(
    bank_ids: tuple[str, ...],
    settlement_ids: tuple[str, ...],
    bank_by_id: dict[str, dict[str, str]],
    settlements: dict[str, dict[str, Any]],
) -> bool:
    """Reject an N:M wrapper that merely bundles a smaller exact match.

    Reachable totals are computed once per cardinality with boolean dynamic
    programming.  The previous implementation repeatedly enumerated the same
    subsets for every pair of cardinalities.
    """
    bank_totals = reachable_totals_by_size([
        signed_bank_amount(bank_by_id[identifier]) for identifier in bank_ids
    ])
    settlement_totals = reachable_totals_by_size([
        Decimal(settlements[identifier]["net"]) for identifier in settlement_ids
    ])
    for bank_size in range(1, len(bank_ids) + 1):
        for settlement_size in range(1, len(settlement_ids) + 1):
            if bank_size == len(bank_ids) and settlement_size == len(settlement_ids):
                continue
            if bank_totals[bank_size] & settlement_totals[settlement_size]:
                return True
    return False


def _group_kind(bank_count: int, settlement_count: int) -> str:
    if bank_count == 1 and settlement_count == 1:
        return "declared_one_to_one"
    if bank_count == 1:
        return "many_settlements_to_one_bank"
    if settlement_count == 1:
        return "one_settlement_to_many_banks"
    return "many_banks_to_many_settlements"


def build_declared_group_candidates(
    bank_rows: list[dict[str, str]],
    settlements: dict[str, dict[str, Any]],
    *,
    max_members_per_side: int = MAX_DECLARED_GROUP_MEMBERS_PER_SIDE,
) -> tuple[list[dict[str, Any]], set[str], set[str], list[dict[str, Any]], dict[str, Any]]:
    """Build O(N+M) candidates from dedicated membership keys.

    A key must appear on both sources.  Nodes carrying such a key are reserved
    for that declared group: if its totals, chronology, counterpart, or size
    fail a control, those nodes are held rather than rematched opportunistically.
    """
    banks_by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    settlements_by_key: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    conflicted_nodes: set[str] = set()
    for row in bank_rows:
        if any(row.get(f"{field}_conflict") for field in DECLARED_GROUP_FIELDS):
            conflicted_nodes.add(f"B:{row['bank_txn_id']}")
            continue
        key = declared_group_key(row)
        if key:
            banks_by_key[key].append(row)
    for identifier, settlement in settlements.items():
        if any(settlement.get(f"{field}_conflict") for field in DECLARED_GROUP_FIELDS):
            conflicted_nodes.add(f"S:{identifier}")
            continue
        key = declared_group_key(settlement)
        if key:
            settlements_by_key[key].append((identifier, settlement))

    candidates: list[dict[str, Any]] = []
    reserved_nodes: set[str] = set(conflicted_nodes)
    unsafe_nodes: set[str] = set(conflicted_nodes)
    issues: list[dict[str, Any]] = []
    if conflicted_nodes:
        issues.append({
            "code": "declared_group_key_conflict",
            "node_ids": sorted(conflicted_nodes),
            "reason": "one source entity carries conflicting dedicated group keys",
        })
    accepted_member_count = 0
    for key in sorted(set(banks_by_key) | set(settlements_by_key)):
        banks = banks_by_key.get(key, [])
        settlement_items = settlements_by_key.get(key, [])
        nodes = {
            *(f"B:{row['bank_txn_id']}" for row in banks),
            *(f"S:{identifier}" for identifier, _ in settlement_items),
        }
        reserved_nodes.update(nodes)
        if not banks or not settlement_items:
            unsafe_nodes.update(nodes)
            issues.append({
                "code": "declared_group_missing_counterpart",
                "membership_key": key,
                "bank_member_count": len(banks),
                "settlement_member_count": len(settlement_items),
                "reason": "dedicated group key is present on only one source",
            })
            continue
        if len(banks) > max_members_per_side or len(settlement_items) > max_members_per_side:
            unsafe_nodes.update(nodes)
            issues.append({
                "code": "declared_group_size_limit",
                "membership_key": key,
                "bank_member_count": len(banks),
                "settlement_member_count": len(settlement_items),
                "limit_per_side": max_members_per_side,
                "reason": "declared membership exceeds the configured verification limit",
            })
            continue
        candidate = group_candidate(
            _group_kind(len(banks), len(settlement_items)),
            banks,
            settlement_items,
            unique_combination=True,
            declared_membership_key=key,
        )
        if not candidate["eligible"]:
            unsafe_nodes.update(nodes)
            issues.append({
                "code": "declared_group_control_failure",
                "membership_key": key,
                "bank_member_count": len(banks),
                "settlement_member_count": len(settlement_items),
                "blockers": candidate["blockers"],
                "residual": candidate["residual"],
                "reason": "declared membership failed money or chronology controls",
            })
        candidates.append(candidate)
        accepted_member_count += len(banks) + len(settlement_items)

    audit = {
        "algorithm": "declared_cross_source_membership",
        "supported_fields": list(DECLARED_GROUP_FIELDS),
        "max_members_per_side": max_members_per_side,
        "declared_group_count": len(set(banks_by_key) | set(settlements_by_key)),
        "candidate_count": len(candidates),
        "accepted_member_count": accepted_member_count,
        "reserved_node_count": len(reserved_nodes),
    }
    return candidates, reserved_nodes, unsafe_nodes, issues, audit


def _membership_evidence(features: list[dict[str, Any]]) -> tuple[int, bool, bool]:
    reference_points = max(
        (int(item["points"]) for item in features if "utr" in item["feature"]),
        default=0,
    )
    feature_names = {item["feature"] for item in features}
    date_close = bool({"settlement_date_exact", "posting_window"} & feature_names)
    date_points = 15 if "settlement_date_exact" in feature_names else 10 if "posting_window" in feature_names else 0
    # The membership cost prevents a large weakly dated subset from beating a
    # smaller, strongly referenced explanation merely because it has more rows.
    return reference_points + date_points - 15, reference_points >= 35, date_close


def build_candidate_graph(
    bank_rows: list[dict[str, str]],
    settlements: dict[str, dict[str, Any]],
    *,
    max_group_size: int = 3,
    max_declared_group_members: int = MAX_DECLARED_GROUP_MEMBERS_PER_SIDE,
    max_inferred_group_members: int = MAX_INFERRED_GROUP_MEMBERS,
    max_membership_pool_size: int = MAX_MEMBERSHIP_POOL_SIZE,
    membership_time_limit_seconds: float = DEFAULT_MEMBERSHIP_TIME_LIMIT_SECONDS,
) -> dict[str, Any]:
    all_bank_rows = bank_rows
    all_settlements = settlements
    (
        declared_candidates,
        reserved_nodes,
        declared_unsafe_nodes,
        declared_issues,
        declared_audit,
    ) = build_declared_group_candidates(
        all_bank_rows,
        all_settlements,
        max_members_per_side=max_declared_group_members,
    )
    # Dedicated cross-source group keys define an atomic verification scope.
    # Do not feed those nodes into fuzzy or subset candidate generation.
    bank_rows = [
        row for row in all_bank_rows
        if f"B:{row['bank_txn_id']}" not in reserved_nodes
    ]
    settlements = {
        identifier: item for identifier, item in all_settlements.items()
        if f"S:{identifier}" not in reserved_nodes
    }
    settlement_amount_frequency: dict[Decimal, int] = defaultdict(int)
    for settlement in settlements.values():
        settlement_amount_frequency[Decimal(settlement["net"])] += 1
    candidates = list(declared_candidates)
    unsafe_nodes: set[str] = set(declared_unsafe_nodes)
    generation_issues: list[dict[str, Any]] = list(declared_issues)
    membership_audit: dict[str, Any] = {
        "algorithm": "cp_sat_unique_anchor_membership",
        "max_inferred_group_members": max_inferred_group_members,
        "max_pool_size": max_membership_pool_size,
        "time_limit_seconds_per_anchor": membership_time_limit_seconds,
        "attempts": [],
        "proven_unique_count": 0,
    }
    subset_sum_audit: dict[str, Any] = {
        "algorithm": "bounded_dynamic_programming_subset_sum",
        "status": "not_required",
    }
    pair_support: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for bank in bank_rows:
        for settlement_id, settlement in settlements.items():
            support = pair_support_features(bank, settlement)
            pair_support[(bank["bank_txn_id"], settlement_id)] = support
            candidate = single_candidate(
                bank, settlement_id, settlement,
                exact_amount_frequency=settlement_amount_frequency[signed_bank_amount(bank)],
                support_features=support,
            )
            if candidate:
                candidates.append(candidate)

    if max_group_size >= 2:
        settlement_amounts = [(identifier, Decimal(item["net"])) for identifier, item in settlements.items()]
        bank_amounts = [(row["bank_txn_id"], signed_bank_amount(row)) for row in bank_rows]
        bank_by_id = {row["bank_txn_id"]: row for row in bank_rows}
        settlement_index = build_subset_sum_index(
            settlement_amounts,
            max_group_size,
            max_solutions_per_state=MAX_GROUP_HYPOTHESES_PER_TOTAL,
            max_solutions_per_total=MAX_GROUP_HYPOTHESES_PER_TOTAL,
            max_states=MAX_DP_STATES,
        )
        bank_index = build_subset_sum_index(
            bank_amounts,
            max_group_size,
            max_solutions_per_state=MAX_GROUP_HYPOTHESES_PER_TOTAL,
            max_solutions_per_total=MAX_GROUP_HYPOTHESES_PER_TOTAL,
            max_states=MAX_DP_STATES,
        )
        subset_sum_audit = {
            "algorithm": "bounded_dynamic_programming_subset_sum",
            "status": "complete",
            "bank_index": bank_index.audit_summary(),
            "settlement_index": settlement_index.audit_summary(),
        }

        def mark_incomplete_target(
            *,
            side: str,
            total: Decimal,
            anchor_node: str | None,
            index: SubsetSumIndex,
            opposite_prefix: str,
        ) -> None:
            nonlocal subset_sum_audit
            if anchor_node:
                unsafe_nodes.add(anchor_node)
            unsafe_nodes.update(
                f"{opposite_prefix}:{identifier}"
                for identifier in index.participants_by_total.get(total, set())
            )
            issue = {
                "code": "candidate_generation_truncated",
                "side": side,
                "signed_total": str(total),
                "anchor_node": anchor_node,
                "reason": (
                    "dynamic-programming state budget exhausted"
                    if index.globally_truncated
                    else "more exact subsets exist than the configured witness cap"
                ),
            }
            if issue not in generation_issues:
                generation_issues.append(issue)
            subset_sum_audit["status"] = "truncated_fail_closed"

        if bank_index.globally_truncated or settlement_index.globally_truncated:
            unsafe_nodes.update(f"B:{row['bank_txn_id']}" for row in bank_rows)
            unsafe_nodes.update(f"S:{identifier}" for identifier in settlements)
            generation_issues.append({
                "code": "candidate_generation_state_budget_exhausted",
                "side": "both" if bank_index.globally_truncated and settlement_index.globally_truncated else (
                    "bank" if bank_index.globally_truncated else "settlement"
                ),
                "reason": "the DP state cap was reached; the complete graph cannot be proven",
            })
            subset_sum_audit["status"] = "truncated_fail_closed"

        for bank in bank_rows:
            target = signed_bank_amount(bank)
            matches = settlement_index.matches(target)
            complete = settlement_index.complete_for(target)
            if not complete:
                mark_incomplete_target(
                    side="settlement_subsets_for_bank",
                    total=target,
                    anchor_node=f"B:{bank['bank_txn_id']}",
                    index=settlement_index,
                    opposite_prefix="S",
                )
            for settlement_ids in matches:
                candidate = group_candidate(
                    "many_settlements_to_one_bank",
                    [bank],
                    [(identifier, settlements[identifier]) for identifier in settlement_ids],
                    unique_combination=complete and len(matches) == 1,
                )
                candidate["candidate_generation_complete"] = complete
                if not complete:
                    candidate["eligible"] = False
                    candidate["blockers"].append("candidate_generation_truncated")
                candidates.append(candidate)
        for settlement_id, settlement in settlements.items():
            target = Decimal(settlement["net"])
            matches = bank_index.matches(target)
            complete = bank_index.complete_for(target)
            if not complete:
                mark_incomplete_target(
                    side="bank_subsets_for_settlement",
                    total=target,
                    anchor_node=f"S:{settlement_id}",
                    index=bank_index,
                    opposite_prefix="B",
                )
            for bank_ids in matches:
                candidate = group_candidate(
                    "one_settlement_to_many_banks",
                    [bank_by_id[identifier] for identifier in bank_ids],
                    [(settlement_id, settlement)],
                    unique_combination=complete and len(matches) == 1,
                )
                candidate["candidate_generation_complete"] = complete
                if not complete:
                    candidate["eligible"] = False
                    candidate["blockers"].append("candidate_generation_truncated")
                candidates.append(candidate)

        # For groups larger than the enumerable DP bound, solve membership
        # directly around a strongly referenced bank or settlement anchor.
        # This avoids enumerating every subset in a pool that may contain up to
        # 1,000 records.  Only a proven-unique optimum becomes a candidate.
        if max_inferred_group_members > max_group_size:
            for bank in bank_rows:
                target = signed_bank_amount(bank)
                if settlement_index.matches(target) or not settlement_index.complete_for(target):
                    continue
                pool: list[MembershipItem] = []
                strong_count = 0
                strong_total = Decimal("0")
                for identifier, settlement in settlements.items():
                    amount = Decimal(settlement["net"])
                    if target == 0 or amount == 0 or (target > 0) != (amount > 0):
                        continue
                    score, strong, date_close = _membership_evidence(
                        pair_support[(bank["bank_txn_id"], identifier)]
                    )
                    if not strong and not date_close:
                        continue
                    pool.append(MembershipItem(identifier, amount, score))
                    strong_count += int(strong)
                    if strong:
                        strong_total += amount
                if (
                    len(pool) <= max_group_size
                    or strong_count < 2
                    or abs(strong_total) > abs(target)
                ):
                    continue
                proof = solve_unique_membership(
                    target,
                    pool,
                    max_members=max_inferred_group_members,
                    max_pool_size=max_membership_pool_size,
                    time_limit_seconds=membership_time_limit_seconds,
                )
                proof_audit = {
                    "side": "settlements_for_bank",
                    "anchor_node": f"B:{bank['bank_txn_id']}",
                    **proof.audit_summary(),
                }
                membership_audit["attempts"].append(proof_audit)
                if proof.proven_unique:
                    candidate = group_candidate(
                        "many_settlements_to_one_bank",
                        [bank],
                        [(identifier, settlements[identifier]) for identifier in proof.member_ids],
                        unique_combination=True,
                    )
                    candidate["features"].append({
                        "feature": "cp_sat_membership_unique",
                        "points": 25,
                        "detail": "large-group membership is the unique evidence-optimal exact sum",
                    })
                    candidate["evidence_score"] = feature_score(candidate["features"])
                    candidate["generation_strategy"] = "cp_sat_unique_anchor_membership"
                    candidate["membership_proof"] = proof_audit
                    candidate["candidate_generation_complete"] = True
                    candidates.append(candidate)
                    membership_audit["proven_unique_count"] += 1
                elif proof.status != "NO_SOLUTION":
                    affected = {f"B:{bank['bank_txn_id']}", *(f"S:{item.identifier}" for item in pool)}
                    unsafe_nodes.update(affected)
                    generation_issues.append({
                        "code": "large_membership_not_proven",
                        "side": "settlements_for_bank",
                        "anchor_node": f"B:{bank['bank_txn_id']}",
                        "status": proof.status,
                        "pool_size": len(pool),
                        "reason": "large inferred membership was ambiguous, over budget, or timed out",
                    })

            for settlement_id, settlement in settlements.items():
                target = Decimal(settlement["net"])
                if bank_index.matches(target) or not bank_index.complete_for(target):
                    continue
                pool = []
                strong_count = 0
                strong_total = Decimal("0")
                for bank in bank_rows:
                    amount = signed_bank_amount(bank)
                    if target == 0 or amount == 0 or (target > 0) != (amount > 0):
                        continue
                    score, strong, date_close = _membership_evidence(
                        pair_support[(bank["bank_txn_id"], settlement_id)]
                    )
                    if not strong and not date_close:
                        continue
                    pool.append(MembershipItem(bank["bank_txn_id"], amount, score))
                    strong_count += int(strong)
                    if strong:
                        strong_total += amount
                if (
                    len(pool) <= max_group_size
                    or strong_count < 2
                    or abs(strong_total) > abs(target)
                ):
                    continue
                proof = solve_unique_membership(
                    target,
                    pool,
                    max_members=max_inferred_group_members,
                    max_pool_size=max_membership_pool_size,
                    time_limit_seconds=membership_time_limit_seconds,
                )
                proof_audit = {
                    "side": "banks_for_settlement",
                    "anchor_node": f"S:{settlement_id}",
                    **proof.audit_summary(),
                }
                membership_audit["attempts"].append(proof_audit)
                if proof.proven_unique:
                    candidate = group_candidate(
                        "one_settlement_to_many_banks",
                        [bank_by_id[identifier] for identifier in proof.member_ids],
                        [(settlement_id, settlement)],
                        unique_combination=True,
                    )
                    candidate["features"].append({
                        "feature": "cp_sat_membership_unique",
                        "points": 25,
                        "detail": "large-group membership is the unique evidence-optimal exact sum",
                    })
                    candidate["evidence_score"] = feature_score(candidate["features"])
                    candidate["generation_strategy"] = "cp_sat_unique_anchor_membership"
                    candidate["membership_proof"] = proof_audit
                    candidate["candidate_generation_complete"] = True
                    candidates.append(candidate)
                    membership_audit["proven_unique_count"] += 1
                elif proof.status != "NO_SOLUTION":
                    affected = {f"S:{settlement_id}", *(f"B:{item.identifier}" for item in pool)}
                    unsafe_nodes.update(affected)
                    generation_issues.append({
                        "code": "large_membership_not_proven",
                        "side": "banks_for_settlement",
                        "anchor_node": f"S:{settlement_id}",
                        "status": proof.status,
                        "pool_size": len(pool),
                        "reason": "large inferred membership was ambiguous, over budget, or timed out",
                    })

        bank_groups = bank_index.groups_by_total
        settlement_groups = settlement_index.groups_by_total
        for total in sorted(set(bank_groups) & set(settlement_groups)):
            bank_matches = bank_groups[total]
            settlement_matches = settlement_groups[total]
            pair_count = len(bank_matches) * len(settlement_matches)
            complete = (
                bank_index.complete_for(total)
                and settlement_index.complete_for(total)
                and pair_count <= MAX_GROUP_HYPOTHESES_PER_TOTAL
            )
            if not complete:
                unsafe_nodes.update(
                    f"B:{identifier}"
                    for identifier in bank_index.participants_by_total.get(total, set())
                )
                unsafe_nodes.update(
                    f"S:{identifier}"
                    for identifier in settlement_index.participants_by_total.get(total, set())
                )
                generation_issues.append({
                    "code": "nm_candidate_pairing_truncated",
                    "side": "many_to_many",
                    "signed_total": str(total),
                    "retained_pair_count": min(pair_count, MAX_GROUP_HYPOTHESES_PER_TOTAL),
                    "known_pair_count": pair_count,
                    "reason": "N:M candidate pairing is incomplete and therefore fail-closed",
                })
                subset_sum_audit["status"] = "truncated_fail_closed"
            emitted = 0
            for bank_ids in bank_matches:
                for settlement_ids in settlement_matches:
                    if has_money_conserving_proper_subgroup(
                        bank_ids, settlement_ids, bank_by_id, settlements
                    ):
                        continue
                    if emitted >= MAX_GROUP_HYPOTHESES_PER_TOTAL:
                        break
                    candidate = group_candidate(
                        "many_banks_to_many_settlements",
                        [bank_by_id[identifier] for identifier in bank_ids],
                        [(identifier, settlements[identifier]) for identifier in settlement_ids],
                        unique_combination=complete and pair_count == 1,
                    )
                    candidate["candidate_generation_complete"] = complete
                    if not complete:
                        candidate["eligible"] = False
                        candidate["blockers"].append("candidate_generation_truncated")
                    candidates.append(candidate)
                    emitted += 1
                if emitted >= MAX_GROUP_HYPOTHESES_PER_TOTAL:
                    break

        # Candidate generation must expose plausible grouped near-misses to the
        # hard gates and global optimizer. Exact-sum enumeration alone makes
        # every grouped hypothesis look pre-solved. These bounded, evidence-led
        # alternatives use partial reference support plus nearby posting dates;
        # no benchmark truth is consulted.
        existing_ids = {item["candidate_id"] for item in candidates}

        def append_distinct(candidate: dict[str, Any]) -> None:
            if candidate["candidate_id"] in existing_ids:
                return
            existing_ids.add(candidate["candidate_id"])
            candidates.append(candidate)

        linked_settlements_by_bank = {
            row["bank_txn_id"]: [
                identifier for identifier, settlement in settlements.items()
                if any(
                    item["points"] >= 35
                    for item in pair_support[(row["bank_txn_id"], identifier)]
                    if "utr" in item["feature"]
                )
            ]
            for row in bank_rows
        }
        linked_banks_by_settlement = {
            identifier: [
                row["bank_txn_id"] for row in bank_rows
                if any(
                    item["points"] >= 35
                    for item in pair_support[(row["bank_txn_id"], identifier)]
                    if "utr" in item["feature"]
                )
            ]
            for identifier, settlement in settlements.items()
        }

        def bank_settlement_distance(bank_id: str, settlement_id: str) -> int:
            distance = minimum_date_distance(
                bank_dates(bank_by_id[bank_id]),
                set(settlements[settlement_id].get("settled_dates", set())),
            )
            return distance if distance is not None else 10_000

        # 1:N: retain one partial-reference settlement pair per bank.
        for bank in bank_rows:
            bank_id = bank["bank_txn_id"]
            linked = linked_settlements_by_bank[bank_id]
            if not linked:
                continue
            decoys = sorted(
                (identifier for identifier in settlements if identifier not in linked),
                key=lambda identifier: (
                    bank_settlement_distance(bank_id, identifier), identifier
                ),
            )
            if not decoys:
                continue
            settlement_ids = (linked[0], decoys[0])
            candidate = group_candidate(
                "many_settlements_to_one_bank",
                [bank],
                [(identifier, settlements[identifier]) for identifier in settlement_ids],
                unique_combination=False,
            )
            candidate["generation_reason"] = "partial reference plus nearest settlement date"
            append_distinct(candidate)

        # N:1: retain one partial-reference bank pair per settlement.
        for settlement_id, settlement in settlements.items():
            linked = linked_banks_by_settlement[settlement_id]
            if not linked:
                continue
            decoys = sorted(
                (row["bank_txn_id"] for row in bank_rows if row["bank_txn_id"] not in linked),
                key=lambda bank_id: (
                    bank_settlement_distance(bank_id, settlement_id), bank_id
                ),
            )
            if not decoys:
                continue
            bank_ids = (linked[0], decoys[0])
            candidate = group_candidate(
                "one_settlement_to_many_banks",
                [bank_by_id[identifier] for identifier in bank_ids],
                [(settlement_id, settlement)],
                unique_combination=False,
            )
            candidate["generation_reason"] = "partial reference plus nearest bank posting date"
            append_distinct(candidate)

        # N:M: perturb one side of each observed reference neighbourhood. This
        # creates an inspectable mesh of wrong groupings without an unbounded
        # bank-pair × settlement-pair cross-product.
        for bank in bank_rows:
            bank_id = bank["bank_txn_id"]
            linked = linked_settlements_by_bank[bank_id]
            if not linked:
                continue
            settlement_decoys = sorted(
                (identifier for identifier in settlements if identifier not in linked),
                key=lambda identifier: (
                    bank_settlement_distance(bank_id, identifier), identifier
                ),
            )
            settlement_ids = tuple((linked + settlement_decoys)[:2])
            if len(settlement_ids) < 2:
                continue
            bank_decoys = sorted(
                (row["bank_txn_id"] for row in bank_rows if row["bank_txn_id"] != bank_id),
                key=lambda other_id: (
                    min(bank_settlement_distance(other_id, sid) for sid in settlement_ids),
                    other_id,
                ),
            )
            if not bank_decoys:
                continue
            bank_ids = (bank_id, bank_decoys[0])
            candidate = group_candidate(
                "many_banks_to_many_settlements",
                [bank_by_id[identifier] for identifier in bank_ids],
                [(identifier, settlements[identifier]) for identifier in settlement_ids],
                unique_combination=False,
            )
            if candidate["eligible"] and has_money_conserving_proper_subgroup(
                bank_ids, settlement_ids, bank_by_id, settlements
            ):
                candidate["eligible"] = False
                candidate["blockers"].append("reducible_group_wrapper")
            candidate["generation_reason"] = "perturbed reference neighbourhood"
            append_distinct(candidate)

    return {
        "bank_nodes": [
            {
                "id": row["bank_txn_id"],
                "amount": str(signed_bank_amount(row)),
                "date_candidates": sorted(bank_dates(row)),
                "narration": row.get("narration", ""),
                "declared_membership_key": declared_group_key(row),
            }
            for row in all_bank_rows
        ],
        "settlement_nodes": [
            {
                "id": identifier,
                "amount": str(item["net"]),
                "date_candidates": sorted(item.get("settled_dates", set())),
                "utr": item.get("utr", ""),
                "component_count": len(item.get("rows", [])),
                "capture_date": item.get("capture_date", ""),
                "settlement_cycle": item.get("settlement_cycle", ""),
                "scheduled_business_days": item.get("scheduled_business_days", ""),
                "settled_at": item.get("canonical_settled_at", ""),
                "working_day_path": item.get("working_day_path", ""),
                "chronology_valid": item.get("chronology_valid"),
                "declared_membership_key": declared_group_key(item),
            }
            for identifier, item in all_settlements.items()
        ],
        "candidates": sorted(candidates, key=lambda item: (-item["evidence_score"], item["candidate_id"])),
        "max_group_size": max_group_size,
        "max_declared_group_members_per_side": max_declared_group_members,
        "max_inferred_group_members": max_inferred_group_members,
        "group_hypothesis_cap_per_total": MAX_GROUP_HYPOTHESES_PER_TOTAL,
        "candidate_generation": {
            **subset_sum_audit,
            "declared_groups": declared_audit,
            "large_inferred_groups": membership_audit,
            "complete": not generation_issues,
            "unsafe_nodes": sorted(unsafe_nodes),
            "issues": generation_issues,
        },
    }


@dataclass
class ComponentSolution:
    selected_ids: set[str]
    objective: int
    tied: bool
    branches: int
    exhausted: bool
    status: str
    best_bound: int
    wall_time_seconds: float
    ambiguity_checks: int


def candidate_nodes(candidate: dict[str, Any]) -> set[str]:
    return {*(f"B:{identifier}" for identifier in candidate["bank_ids"]), *(f"S:{identifier}" for identifier in candidate["settlement_ids"])}


def connected_candidate_components(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    by_node: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        for node in candidate_nodes(candidate):
            by_node[node].append(index)
    remaining = set(range(len(candidates)))
    components = []
    while remaining:
        seed = remaining.pop()
        stack, indices = [seed], {seed}
        while stack:
            index = stack.pop()
            for node in candidate_nodes(candidates[index]):
                for neighbour in by_node[node]:
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        indices.add(neighbour)
                        stack.append(neighbour)
        components.append([candidates[index] for index in sorted(indices)])
    return components


def _cp_sat_model(
    ordered: list[dict[str, Any]],
    weights: list[int],
    *,
    fixed_objective: int | None = None,
    excluded_index: int | None = None,
) -> tuple[cp_model.CpModel, list[cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"candidate_{index}") for index in range(len(ordered))]
    by_node: dict[str, list[int]] = defaultdict(list)
    for index, candidate in enumerate(ordered):
        for node in candidate_nodes(candidate):
            by_node[node].append(index)
    for indices in by_node.values():
        model.add(sum(variables[index] for index in indices) <= 1)
    objective = sum(weights[index] * variables[index] for index in range(len(ordered)))
    if fixed_objective is None:
        model.maximize(objective)
    else:
        model.add(objective == fixed_objective)
    if excluded_index is not None:
        model.add(variables[excluded_index] == 0)
    return model, variables


def _configured_solver(time_limit_seconds: float) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, time_limit_seconds)
    # A single worker and fixed seed make proof artifacts reproducible across
    # repeated runs.  Money and objective coefficients remain integers.
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    return solver


def solve_component(
    candidates: list[dict[str, Any]],
    *,
    time_limit_seconds: float = DEFAULT_CP_SAT_TIME_LIMIT_SECONDS,
) -> ComponentSolution:
    """Solve one candidate component and retain only mandatory optimal edges.

    The first CP-SAT run proves the optimal objective.  Each selected edge is
    then excluded in a fixed-objective feasibility probe.  If another optimum
    exists without that edge, it is ambiguous and excluded from the safe
    intersection.  Any unproven main solve or ambiguity probe abstains for the
    entire component.
    """
    if time_limit_seconds <= 0:
        return ComponentSolution(
            set(), 0, False, 0, True, "TIME_LIMIT_ZERO", 0, 0.0, 0
        )
    ordered = sorted(
        candidates,
        key=lambda item: (-(item["evidence_score"] + 20 * (len(item["bank_ids"]) + len(item["settlement_ids"]) - 2)), item["candidate_id"]),
    )
    weights = [item["evidence_score"] + 20 * (len(item["bank_ids"]) + len(item["settlement_ids"]) - 2) for item in ordered]
    started = perf_counter()
    deadline = started + time_limit_seconds
    model, variables = _cp_sat_model(ordered, weights)
    solver = _configured_solver(time_limit_seconds)
    status = solver.solve(model)
    status_name = solver.status_name(status)
    branches = int(solver.num_branches)
    if status != cp_model.OPTIMAL:
        return ComponentSolution(
            set(), 0, False, branches, True, status_name,
            int(round(solver.best_objective_bound)) if status in (cp_model.FEASIBLE, cp_model.OPTIMAL) else 0,
            perf_counter() - started, 0,
        )

    optimum = int(round(solver.objective_value))
    best_bound = int(round(solver.best_objective_bound))
    initially_selected = [index for index, variable in enumerate(variables) if solver.value(variable)]
    mandatory_ids: set[str] = set()
    tied = False
    ambiguity_checks = 0
    for index in initially_selected:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            return ComponentSolution(
                set(), optimum, tied, branches, True, "AMBIGUITY_CHECK_TIMEOUT",
                best_bound, perf_counter() - started, ambiguity_checks,
            )
        probe_model, _ = _cp_sat_model(
            ordered,
            weights,
            fixed_objective=optimum,
            excluded_index=index,
        )
        probe_solver = _configured_solver(remaining)
        probe_status = probe_solver.solve(probe_model)
        branches += int(probe_solver.num_branches)
        ambiguity_checks += 1
        if probe_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            tied = True
            continue
        if probe_status == cp_model.INFEASIBLE:
            mandatory_ids.add(ordered[index]["candidate_id"])
            continue
        return ComponentSolution(
            set(), optimum, tied, branches, True,
            f"AMBIGUITY_CHECK_{probe_solver.status_name(probe_status)}",
            best_bound, perf_counter() - started, ambiguity_checks,
        )

    return ComponentSolution(
        mandatory_ids,
        optimum,
        tied,
        branches,
        False,
        "OPTIMAL_AMBIGUOUS" if tied else "OPTIMAL_UNIQUE",
        best_bound,
        perf_counter() - started,
        ambiguity_checks,
    )


def confidence_for(candidate: dict[str, Any]) -> float:
    features = {item["feature"] for item in candidate["features"]}
    if "full_utr_exact" in features and "signed_amount_exact" in features:
        return 1.0
    if candidate["kind"] != "one_to_one":
        return 0.95
    if candidate["evidence_score"] >= 70:
        return 0.97
    return 0.90


def solve_candidate_graph(
    graph: dict[str, Any],
    *,
    selection_threshold: int = DEFAULT_SELECTION_THRESHOLD,
    component_time_limit_seconds: float = DEFAULT_CP_SAT_TIME_LIMIT_SECONDS,
) -> dict[str, Any]:
    unsafe_nodes = set(graph.get("candidate_generation", {}).get("unsafe_nodes", []))
    selectable = [
        candidate for candidate in graph["candidates"]
        if candidate["eligible"] and candidate["evidence_score"] >= selection_threshold
        and not (candidate_nodes(candidate) & unsafe_nodes)
    ]
    components = connected_candidate_components(selectable)
    selected_ids: set[str] = set()
    component_reports = []
    for candidates in components:
        component_node_ids = sorted(set().union(*(candidate_nodes(item) for item in candidates)))
        solution = solve_component(
            candidates,
            time_limit_seconds=component_time_limit_seconds,
        )
        selected_ids |= solution.selected_ids
        component_reports.append({
            "candidate_count": len(candidates),
            "node_ids": component_node_ids,
            "objective": solution.objective,
            "best_bound": solution.best_bound,
            "status": solution.status,
            "tied_optimum": solution.tied,
            "branches": solution.branches,
            "exhausted": solution.exhausted,
            "wall_time_seconds": round(solution.wall_time_seconds, 6),
            "ambiguity_checks": solution.ambiguity_checks,
        })
    selected = [candidate for candidate in graph["candidates"] if candidate["candidate_id"] in selected_ids]
    selected_nodes = set().union(*(candidate_nodes(item) for item in selected)) if selected else set()
    certificates = []
    for index, candidate in enumerate(selected, start=1):
        nodes = candidate_nodes(candidate)
        alternatives = [
            {
                "candidate_id": other["candidate_id"],
                "evidence_score": other["evidence_score"],
                "residual": other["residual"],
                "reason": "lower global objective or conflicting one-use constraint",
            }
            for other in graph["candidates"]
            if other["candidate_id"] != candidate["candidate_id"] and candidate_nodes(other) & nodes
        ][:5]
        certificates.append({
            "certificate_id": f"LGC-{index:05d}",
            "decision": "globally_selected",
            "candidate_id": candidate["candidate_id"],
            "kind": candidate["kind"],
            "topology": candidate["topology"],
            "bank_entries": candidate["bank_ids"],
            "settlements": candidate["settlement_ids"],
            "evidence_score": candidate["evidence_score"],
            "confidence": confidence_for(candidate),
            "confidence_interpretation": "deterministic policy band, not an empirical probability",
            "score_breakdown": candidate["features"],
            "money_conservation": {
                "bank_total": candidate["bank_total"],
                "settlement_net": candidate["settlement_total"],
                "residual": candidate["residual"],
            },
            "constraints_satisfied": [
                "signed_money_conservation",
                "global_one_use",
                (
                    "declared_cross_source_membership_limit"
                    if candidate.get("generation_strategy") == "declared_cross_source_membership"
                    else "bounded_group_size_or_unique_membership_proof"
                ),
                "selection_threshold",
                "complete_candidate_generation_for_selected_nodes",
                "cp_sat_optimum_proven",
                "selected_edge_mandatory_across_all_optima",
            ],
            "rejected_alternatives": alternatives,
        })
    all_bank_ids = {node["id"] for node in graph["bank_nodes"]}
    all_settlement_ids = {node["id"] for node in graph["settlement_nodes"]}
    candidate_topology_counts = {
        topology: sum(item["topology"] == topology for item in graph["candidates"])
        for topology in ("1:1", "1:N", "N:1", "N:M")
    }
    selected_topology_counts = {
        topology: sum(item["topology"] == topology for item in selected)
        for topology in ("1:1", "1:N", "N:1", "N:M")
    }
    hard_gate_rejected_topology_counts = {
        topology: sum(
            item["topology"] == topology
            and (not item["eligible"] or item["evidence_score"] < selection_threshold)
            for item in graph["candidates"]
        )
        for topology in ("1:1", "1:N", "N:1", "N:M")
    }
    global_rejected_topology_counts = {
        topology: sum(
            item["topology"] == topology
            and item["eligible"]
            and item["evidence_score"] >= selection_threshold
            and not (candidate_nodes(item) & unsafe_nodes)
            and item["candidate_id"] not in selected_ids
            for item in graph["candidates"]
        )
        for topology in ("1:1", "1:N", "N:1", "N:M")
    }
    generation_rejected_topology_counts = {
        topology: sum(
            item["topology"] == topology
            and bool(candidate_nodes(item) & unsafe_nodes)
            for item in graph["candidates"]
        )
        for topology in ("1:1", "1:N", "N:1", "N:M")
    }
    return {
        "solver": "ortools_cp_sat_component_set_packing",
        "solver_policy": (
            "only proven-optimal edges mandatory across every optimum may proceed; "
            "feasible-only, unknown, timed-out, truncated, or ambiguous edges abstain"
        ),
        "selection_threshold": selection_threshold,
        "component_time_limit_seconds": component_time_limit_seconds,
        "threshold_policy": "synthetic-suite selective threshold; exact money remains a hard constraint",
        "candidate_count": len(graph["candidates"]),
        "selectable_candidate_count": len(selectable),
        "selected_candidate_count": len(selected),
        "candidate_generation": graph.get("candidate_generation", {}),
        "candidate_generation_unsafe_node_count": len(unsafe_nodes),
        "all_components_proven": (
            bool(graph.get("candidate_generation", {}).get("complete", True))
            and all(not item["exhausted"] for item in component_reports)
        ),
        "selected": selected,
        "certificates": certificates,
        "candidate_topology_counts": candidate_topology_counts,
        "selected_topology_counts": selected_topology_counts,
        "hard_gate_rejected_topology_counts": hard_gate_rejected_topology_counts,
        "global_rejected_topology_counts": global_rejected_topology_counts,
        "generation_rejected_topology_counts": generation_rejected_topology_counts,
        "abstained_bank_ids": sorted(identifier for identifier in all_bank_ids if f"B:{identifier}" not in selected_nodes),
        "unused_settlement_ids": sorted(identifier for identifier in all_settlement_ids if f"S:{identifier}" not in selected_nodes),
        "components": component_reports,
        "global_constraints": [
            "each bank entry used at most once",
            "each settlement used at most once",
            "signed grouped amounts conserve money exactly",
            "declared cross-source groups may contain up to the configured per-side limit",
            "large inferred anchor groups require a unique CP-SAT membership optimum",
            "tied optimal edges are excluded",
            "candidate-generation truncation fails closed",
            "non-optimal or timed-out CP-SAT components fail closed",
        ],
    }
