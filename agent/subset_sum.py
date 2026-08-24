"""Bounded, auditable dynamic-programming subset-sum discovery.

The reconciliation engine needs the actual member sets, not merely a boolean
answer to "does this total exist?".  This module therefore keeps a bounded set
of witnesses for each ``(cardinality, signed total)`` state and separately
tracks whether any witnesses were discarded.  Callers must fail closed when a
target total is incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class SubsetSumIndex:
    groups_by_total: dict[Decimal, list[tuple[str, ...]]]
    incomplete_totals: set[Decimal]
    participants_by_total: dict[Decimal, set[str]]
    state_count: int
    transition_count: int
    max_group_size: int
    max_solutions_per_total: int
    globally_truncated: bool

    def matches(self, target: Decimal) -> list[tuple[str, ...]]:
        return self.groups_by_total.get(target, [])

    def complete_for(self, target: Decimal) -> bool:
        return not self.globally_truncated and target not in self.incomplete_totals

    def audit_summary(self) -> dict[str, object]:
        return {
            "algorithm": "bounded_dynamic_programming_subset_sum",
            "max_group_size": self.max_group_size,
            "max_solutions_per_total": self.max_solutions_per_total,
            "state_count": self.state_count,
            "transition_count": self.transition_count,
            "indexed_total_count": len(self.groups_by_total),
            "incomplete_total_count": len(self.incomplete_totals),
            "globally_truncated": self.globally_truncated,
        }


def build_subset_sum_index(
    items: list[tuple[str, Decimal]],
    max_group_size: int,
    *,
    min_group_size: int = 2,
    max_solutions_per_state: int = 64,
    max_solutions_per_total: int = 64,
    max_states: int = 250_000,
) -> SubsetSumIndex:
    """Index bounded signed subset sums while making incompleteness explicit.

    Dynamic programming reuses every reachable ``(size, total)`` state instead
    of rescanning all combinations separately for every bank or settlement
    target.  Witness caps are safety budgets, never silent approximations: an
    overflow marks the affected total incomplete.
    """
    if max_group_size < 0:
        raise ValueError("max_group_size must be non-negative")
    if min_group_size < 1:
        raise ValueError("min_group_size must be positive")
    if max_solutions_per_state < 1 or max_solutions_per_total < 1:
        raise ValueError("subset-sum witness caps must be positive")
    if max_states < 1:
        raise ValueError("max_states must be positive")

    bounded_size = min(max_group_size, len(items))
    # Each state bucket contains deterministic witness tuples in canonical
    # source-ingestion order. Candidate IDs separately sort their membership,
    # so equivalent hyperedges still receive stable identities.
    ordered_items = list(items)
    states: list[dict[Decimal, list[tuple[str, ...]]]] = [
        {} for _ in range(bounded_size + 1)
    ]
    incomplete_states: list[set[Decimal]] = [set() for _ in range(bounded_size + 1)]
    participants: list[dict[Decimal, set[str]]] = [
        {} for _ in range(bounded_size + 1)
    ]
    states[0][Decimal("0")] = [tuple()]
    participants[0][Decimal("0")] = set()
    state_count = 1
    transition_count = 0
    globally_truncated = False

    stop_for_global_cap = False
    for item_index, (identifier, amount) in enumerate(ordered_items, start=1):
        for size in range(min(bounded_size, item_index), 0, -1):
            previous_states = list(states[size - 1].items())
            for previous_total, previous_groups in previous_states:
                total = previous_total + amount
                transition_count += len(previous_groups)
                if total not in states[size]:
                    if state_count >= max_states:
                        globally_truncated = True
                        stop_for_global_cap = True
                        break
                    states[size][total] = []
                    participants[size][total] = set()
                    state_count += 1

                destination = states[size][total]
                destination_participants = participants[size][total]
                if previous_total in incomplete_states[size - 1]:
                    incomplete_states[size].add(total)
                    destination_participants.update(participants[size - 1][previous_total])
                    destination_participants.add(identifier)

                for group in previous_groups:
                    extended = (*group, identifier)
                    destination_participants.update(extended)
                    if len(destination) < max_solutions_per_state:
                        destination.append(extended)
                    else:
                        incomplete_states[size].add(total)
            if stop_for_global_cap:
                break
        if stop_for_global_cap:
            break

    groups_by_total: dict[Decimal, list[tuple[str, ...]]] = {}
    incomplete_totals: set[Decimal] = set()
    participants_by_total: dict[Decimal, set[str]] = {}
    for size in range(min_group_size, bounded_size + 1):
        for total, groups in states[size].items():
            bucket = groups_by_total.setdefault(total, [])
            participants_by_total.setdefault(total, set()).update(participants[size][total])
            if total in incomplete_states[size]:
                incomplete_totals.add(total)
            room = max_solutions_per_total - len(bucket)
            if room > 0:
                bucket.extend(groups[:room])
            if len(groups) > room:
                incomplete_totals.add(total)

    return SubsetSumIndex(
        groups_by_total=groups_by_total,
        incomplete_totals=incomplete_totals,
        participants_by_total=participants_by_total,
        state_count=state_count,
        transition_count=transition_count,
        max_group_size=max_group_size,
        max_solutions_per_total=max_solutions_per_total,
        globally_truncated=globally_truncated,
    )


def reachable_totals_by_size(amounts: list[Decimal]) -> list[set[Decimal]]:
    """Return exact reachable totals for each cardinality using boolean DP."""
    totals = [set() for _ in range(len(amounts) + 1)]
    totals[0].add(Decimal("0"))
    for item_index, amount in enumerate(amounts, start=1):
        for size in range(item_index, 0, -1):
            totals[size].update(previous + amount for previous in totals[size - 1])
    return totals
