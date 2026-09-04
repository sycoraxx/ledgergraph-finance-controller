"""Time-bounded, proof-oriented membership search for large anchored groups.

The regular LedgerGraph candidate generator enumerates small subsets so it can
show every candidate.  That is the right method for small groups but the wrong
method for an aggregate containing tens or hundreds of records.  This module
solves one anchored membership question directly with CP-SAT and accepts a
result only when the optimum and its uniqueness are both proven.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class MembershipItem:
    identifier: str
    amount: Decimal
    evidence_score: int


@dataclass
class MembershipProof:
    status: str
    member_ids: tuple[str, ...]
    objective: int
    best_bound: int
    pool_size: int
    branches: int
    wall_time_seconds: float
    uniqueness_checks: int

    @property
    def proven_unique(self) -> bool:
        return self.status == "OPTIMAL_UNIQUE"

    def audit_summary(self) -> dict[str, object]:
        return asdict(self)


def _minor_units(value: Decimal) -> int:
    scaled = value * 100
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ValueError(f"amount has more than two decimal places: {value}")
    return int(integral)


def _solver(seconds: float) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    return solver


def _model(
    amounts: list[int],
    scores: list[int],
    target: int,
    min_members: int,
    max_members: int,
    *,
    fixed_objective: int | None = None,
    excluded_assignment: set[int] | None = None,
) -> tuple[cp_model.CpModel, list[cp_model.IntVar]]:
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"member_{index}") for index in range(len(amounts))]
    model.add(sum(amount * variable for amount, variable in zip(amounts, variables)) == target)
    model.add(sum(variables) >= min_members)
    model.add(sum(variables) <= max_members)
    objective = sum(score * variable for score, variable in zip(scores, variables))
    if fixed_objective is None:
        model.maximize(objective)
    else:
        model.add(objective == fixed_objective)
    if excluded_assignment is not None:
        changed = [
            (1 - variable) if index in excluded_assignment else variable
            for index, variable in enumerate(variables)
        ]
        model.add(sum(changed) >= 1)
    return model, variables


def solve_unique_membership(
    target: Decimal,
    items: list[MembershipItem],
    *,
    min_members: int = 2,
    max_members: int = 100,
    max_pool_size: int = 1000,
    time_limit_seconds: float = 2.0,
) -> MembershipProof:
    """Find a unique optimal exact-sum subset or return a fail-closed status.

    Evidence scores are policy weights, not probabilities.  No identifier-based
    tie-break is added: two equally supported memberships remain ambiguous.
    """
    started = perf_counter()
    ordered = sorted(items, key=lambda item: item.identifier)
    if len(ordered) > max_pool_size:
        return MembershipProof(
            "POOL_LIMIT", tuple(), 0, 0, len(ordered), 0,
            perf_counter() - started, 0,
        )
    if len({item.identifier for item in ordered}) != len(ordered):
        return MembershipProof(
            "DUPLICATE_IDENTIFIER", tuple(), 0, 0, len(ordered), 0,
            perf_counter() - started, 0,
        )
    if time_limit_seconds <= 0 or max_members < min_members:
        return MembershipProof(
            "INVALID_BUDGET", tuple(), 0, 0, len(ordered), 0,
            perf_counter() - started, 0,
        )
    if len(ordered) < min_members:
        return MembershipProof(
            "NO_SOLUTION", tuple(), 0, 0, len(ordered), 0,
            perf_counter() - started, 0,
        )

    try:
        target_units = _minor_units(target)
        amount_units = [_minor_units(item.amount) for item in ordered]
    except ValueError:
        return MembershipProof(
            "INVALID_MONEY_SCALE", tuple(), 0, 0, len(ordered), 0,
            perf_counter() - started, 0,
        )
    scores = [int(item.evidence_score) for item in ordered]
    deadline = started + time_limit_seconds
    model, variables = _model(
        amount_units, scores, target_units, min_members, min(max_members, len(ordered))
    )
    solver = _solver(time_limit_seconds)
    status = solver.solve(model)
    branches = int(solver.num_branches)
    if status == cp_model.INFEASIBLE:
        return MembershipProof(
            "NO_SOLUTION", tuple(), 0, int(round(solver.best_objective_bound)),
            len(ordered), branches, perf_counter() - started, 0,
        )
    if status != cp_model.OPTIMAL:
        return MembershipProof(
            f"MAIN_{solver.status_name(status)}", tuple(), 0,
            int(round(solver.best_objective_bound)) if status == cp_model.FEASIBLE else 0,
            len(ordered), branches, perf_counter() - started, 0,
        )

    objective = int(round(solver.objective_value))
    best_bound = int(round(solver.best_objective_bound))
    selected = {index for index, variable in enumerate(variables) if solver.value(variable)}
    remaining = deadline - perf_counter()
    if remaining <= 0:
        return MembershipProof(
            "UNIQUENESS_TIMEOUT", tuple(), objective, best_bound, len(ordered),
            branches, perf_counter() - started, 0,
        )
    probe_model, _ = _model(
        amount_units,
        scores,
        target_units,
        min_members,
        min(max_members, len(ordered)),
        fixed_objective=objective,
        excluded_assignment=selected,
    )
    probe = _solver(remaining)
    probe_status = probe.solve(probe_model)
    branches += int(probe.num_branches)
    if probe_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return MembershipProof(
            "OPTIMAL_AMBIGUOUS", tuple(), objective, best_bound, len(ordered),
            branches, perf_counter() - started, 1,
        )
    if probe_status != cp_model.INFEASIBLE:
        return MembershipProof(
            f"UNIQUENESS_{probe.status_name(probe_status)}", tuple(), objective,
            best_bound, len(ordered), branches, perf_counter() - started, 1,
        )
    return MembershipProof(
        "OPTIMAL_UNIQUE",
        tuple(ordered[index].identifier for index in sorted(selected)),
        objective,
        best_bound,
        len(ordered),
        branches,
        perf_counter() - started,
        1,
    )
