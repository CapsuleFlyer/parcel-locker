"""Test oracle: checks that go beyond comparing return values.

Three layers, strongest evidence first:
1. Model comparison  - Result and the *complete* snapshot must equal the model's.
2. State invariants  - properties every reachable SUT snapshot must satisfy,
                       checked on the SUT's own snapshot (model-independent).
3. Rejection purity  - a rejected operation must leave the SUT snapshot unchanged,
                       checked from the SUT's before/after snapshots.

Layers 2 and 3 do not consult the model, which reduces the risk that a bug
copied into both model and SUT goes unnoticed, and they give more precise
failure diagnostics than a bare "snapshot mismatch".
"""
from __future__ import annotations

from typing import Optional

from .rules_config import Policy, get_policy
from .types import Result, Snapshot, State

Problem = tuple[str, str]  # (kind, human-readable detail)

RESULT_MISMATCH = "result_mismatch"
STATE_MISMATCH = "state_mismatch"
INVARIANT_VIOLATION = "invariant_violation"
REJECT_MUTATED_STATE = "reject_mutated_state"
SUT_EXCEPTION = "sut_exception"


def snapshot_dict(s: Snapshot) -> dict:
    return {
        "state": s.state.value if isinstance(s.state, State) else str(s.state),
        "customer_id": s.customer_id,
        "reservation_code": s.reservation_code,
        "retrieval_code": s.retrieval_code,
    }


def compare_step(expected: Result, actual: Result, expected_snap: Snapshot,
                 actual_snap: Snapshot, compare_messages: bool = True,
                 compare_result: bool = True, compare_state: bool = True) -> list[Problem]:
    problems: list[Problem] = []
    if compare_result:
        if expected.accepted != actual.accepted:
            problems.append((RESULT_MISMATCH,
                             f"accepted: expected {expected.accepted}, actual {actual.accepted}"))
        elif compare_messages and expected.message != actual.message:
            problems.append((RESULT_MISMATCH,
                             f"message: expected {expected.message!r}, actual {actual.message!r}"))
    if compare_state and expected_snap != actual_snap:
        e, a = snapshot_dict(expected_snap), snapshot_dict(actual_snap)
        diff = [f"{k}: expected {e[k]!r}, actual {a[k]!r}" for k in e if e[k] != a[k]]
        problems.append((STATE_MISMATCH, "; ".join(diff)))
    return problems


def check_snapshot_invariants(s: Snapshot, policy: Optional[Policy] = None) -> list[Problem]:
    """Structural invariants of a single snapshot (see docs/MODEL.md, I1-I4).

    The credential *formats* come from ``rules_config`` (a requirement-level fact shared with the
    model); the checks themselves look only at the SUT snapshot, never at the model's state.
    """
    policy = policy or get_policy()
    res_code, ret_code = policy.reservation_code, policy.retrieval_code
    res_fmt = policy.reservation_code_template.replace("{cid}", "<customer>")
    ret_fmt = policy.retrieval_code_template.replace("{cid}", "<customer>")
    out: list[Problem] = []

    def bad(msg: str) -> None:
        out.append((INVARIANT_VIOLATION, msg))

    if s.state in (State.AVAILABLE, State.MAINTENANCE):
        # I1: no customer or credential data outside an active booking
        if (s.customer_id, s.reservation_code, s.retrieval_code) != (None, None, None):
            bad(f"I1 {s.state.value} must hold no customer/credential data, got "
                f"{s.customer_id!r}/{s.reservation_code!r}/{s.retrieval_code!r}")
    elif s.state == State.RESERVED:
        # I2: reserved => customer + matching reservation code, no retrieval code yet
        if s.customer_id is None or s.reservation_code != res_code(s.customer_id):
            bad(f"I2 RESERVED needs reservation_code == {res_fmt}, "
                f"got {s.reservation_code!r}")
        if s.retrieval_code is not None:
            bad(f"I2 RESERVED must not hold a retrieval code, got {s.retrieval_code!r}")
    elif s.state == State.OCCUPIED:
        # I3: occupied => retrieval code P-<customer> present for the same customer
        if s.customer_id is None or s.retrieval_code != ret_code(s.customer_id):
            bad(f"I3 OCCUPIED needs retrieval_code == {ret_fmt}, "
                f"got {s.retrieval_code!r}")
        if s.reservation_code != (res_code(s.customer_id) if s.customer_id else None):
            bad(f"I3 OCCUPIED reservation_code inconsistent with customer: {s.reservation_code!r}")
    else:
        bad(f"I4 unknown state {s.state!r}")
    return out


def check_no_mutation_on_reject(before: Snapshot, after: Snapshot, result: Result) -> list[Problem]:
    """Requirement 12 / 11: rejected operations must not mutate state."""
    if not result.accepted and before != after:
        e, a = snapshot_dict(before), snapshot_dict(after)
        diff = [f"{k}: {e[k]!r} -> {a[k]!r}" for k in e if e[k] != a[k]]
        return [(REJECT_MUTATED_STATE, "rejected op changed SUT state: " + "; ".join(diff))]
    return []
