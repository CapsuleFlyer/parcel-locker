"""Independent executable state-machine model of the Smart Parcel Locker.

Derived ONLY from ``data/requirements.md`` / the assignment text. It never
imports or inspects the SUT.

Design: the behaviour is a *declarative rule table* keyed by ``(state, operation)``.
Each key maps to an ordered list of guarded rules (first matching guard wins);
any ``(state, operation)`` pair without a matching rule falls back to a default
rejection that leaves the state untouched (requirement 12). This is deliberately
structured differently from the SUT's imperative if-chain so that the oracle is
not a copy of the implementation, and so that a rule change (e.g. "allow DISABLE
while OCCUPIED") is a one-line table edit.

The same table is used to derive the *transition catalogue* (the denominator for
transition coverage) and the *transition-pair catalogue*.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Optional

from .types import Command, Operation, Result, Snapshot, State

A, R, O, M = State.AVAILABLE, State.RESERVED, State.OCCUPIED, State.MAINTENANCE
Op = Operation


# --------------------------------------------------------------------------- #
# Credential policy (requirements 2 and 5)
# --------------------------------------------------------------------------- #
def reservation_code_for(customer_id: str) -> str:
    return "R-" + customer_id


def retrieval_code_for(customer_id: str) -> str:
    return "P-" + customer_id


# --------------------------------------------------------------------------- #
# Model data (the extended state variables)
# --------------------------------------------------------------------------- #
@dataclass
class _Data:
    customer_id: Optional[str] = None
    reservation_code: Optional[str] = None
    retrieval_code: Optional[str] = None

    def clear(self) -> None:
        self.customer_id = self.reservation_code = self.retrieval_code = None


Guard = Callable[[_Data, Command], bool]


@dataclass(frozen=True)
class Rule:
    """One guarded alternative for a (state, operation) pair."""
    outcome: str          # expected Result.message (also names the transition outcome)
    dst: State            # state after the rule fires
    accepted: bool        # expected Result.accepted
    guard: Optional[Guard] = None  # None == unconditional


@dataclass(frozen=True)
class TransitionKey:
    """Identity of one model transition: source, operation, outcome, destination."""
    src: State
    op: Operation
    outcome: str
    dst: State
    accepted: bool

    def label(self) -> str:
        return f"{self.src.value}--{self.op.value}[{self.outcome}]-->{self.dst.value}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.label()


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
def _code_matches_reservation(d: _Data, c: Command) -> bool:
    return c.code == d.reservation_code


def _code_matches_retrieval(d: _Data, c: Command) -> bool:
    return c.code == d.retrieval_code


def _is_expired(d: _Data, c: Command) -> bool:
    return c.expired is True


# --------------------------------------------------------------------------- #
# Transition rules (requirements 1, 3, 4, 6, 8, 9, 10)
# --------------------------------------------------------------------------- #
RULES: dict[tuple[State, Operation], list[Rule]] = {
    (A, Op.RESERVE):  [Rule("reserved", R, True)],
    (R, Op.CANCEL):   [Rule("cancelled", A, True)],
    (R, Op.DEPOSIT):  [Rule("deposited", O, True, _code_matches_reservation),
                       Rule("invalid_reservation_code", R, False)],
    (O, Op.RETRIEVE): [Rule("retrieved", A, True, _code_matches_retrieval),
                       Rule("invalid_retrieval_code", O, False)],
    (R, Op.EXPIRE):   [Rule("expired", A, True, _is_expired),
                       Rule("not_expired", R, False)],
    (A, Op.DISABLE):  [Rule("disabled", M, True)],
    (M, Op.ENABLE):   [Rule("enabled", A, True)],
}

# Rejection used for any (state, op) with no matching rule (requirement 12).
DEFAULT_REJECTION: dict[Operation, str] = {
    Op.RESERVE: "locker_not_available",
    Op.CANCEL: "not_reserved",
    Op.DEPOSIT: "not_reserved",
    Op.RETRIEVE: "no_parcel",
    Op.EXPIRE: "not_reserved",
    Op.DISABLE: "cannot_disable",
    Op.ENABLE: "not_in_maintenance",
    Op.INVALID_ACCESS: "invalid_access",   # rejected in EVERY state (requirement 11)
}


# --------------------------------------------------------------------------- #
# Effects on the credential data, keyed by accepted outcome
# --------------------------------------------------------------------------- #
def _on_reserved(d: _Data, c: Command) -> None:
    d.customer_id = c.customer_id
    d.reservation_code = reservation_code_for(c.customer_id)
    d.retrieval_code = None


def _on_deposited(d: _Data, c: Command) -> None:
    # Assumption A3: the reservation code stays stored while OCCUPIED; only
    # retrieval/cancel/expire clear "all" data (requirement 7).
    d.retrieval_code = retrieval_code_for(d.customer_id)


def _on_clear(d: _Data, c: Command) -> None:
    d.clear()


EFFECTS: dict[str, Callable[[_Data, Command], None]] = {
    "reserved": _on_reserved,
    "deposited": _on_deposited,
    "cancelled": _on_clear,
    "retrieved": _on_clear,
    "expired": _on_clear,
    # "disabled" / "enabled": no data change (data is already empty in A / M)
}


# --------------------------------------------------------------------------- #
# Catalogues (coverage denominators)
# --------------------------------------------------------------------------- #
def transition_catalogue() -> tuple[TransitionKey, ...]:
    """Every distinct (src, op, outcome, dst) the model can produce."""
    out: list[TransitionKey] = []
    for s in State:
        for op in Operation:
            rules = RULES.get((s, op), [])
            for r in rules:
                out.append(TransitionKey(s, op, r.outcome, r.dst, r.accepted))
            if not any(r.guard is None for r in rules):
                out.append(TransitionKey(s, op, DEFAULT_REJECTION[op], s, False))
    return tuple(out)


def transition_pairs() -> tuple[tuple[TransitionKey, TransitionKey], ...]:
    """Defined adjacent pairs (t1, t2): t1 ends in the state where t2 starts.

    Rejected operations are self-loops, so they take part in pairs too. Every
    such pair is realisable because a transition depends only on the abstract
    state and the input class, not on history.
    """
    cat = transition_catalogue()
    return tuple((a, b) for a in cat for b in cat if a.dst == b.src)


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
class LockerModel:
    """Executable oracle: ``step(command)`` returns the *expected* Result."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._state: State = A
        self._data = _Data()
        self.last_transition: Optional[TransitionKey] = None

    # -- queries ---------------------------------------------------------- #
    @property
    def state(self) -> State:
        return self._state

    def snapshot(self) -> Snapshot:
        d = self._data
        return Snapshot(self._state, d.customer_id, d.reservation_code, d.retrieval_code)

    def clone(self) -> "LockerModel":
        return copy.deepcopy(self)

    def _match(self, command: Command) -> Rule:
        for rule in RULES.get((self._state, command.operation), ()):
            if rule.guard is None or rule.guard(self._data, command):
                return rule
        outcome = DEFAULT_REJECTION.get(command.operation, "unknown_operation")
        return Rule(outcome, self._state, False)

    def peek(self, command: Command) -> TransitionKey:
        """Which transition *would* fire, without changing the model."""
        r = self._match(command)
        return TransitionKey(self._state, command.operation, r.outcome, r.dst, r.accepted)

    def is_valid(self, command: Command) -> bool:
        """Is the operation accepted in the current state (guards included)?"""
        return self.peek(command).accepted

    # -- execution -------------------------------------------------------- #
    def step(self, command: Command) -> Result:
        rule = self._match(command)
        key = TransitionKey(self._state, command.operation, rule.outcome, rule.dst, rule.accepted)
        if rule.accepted:
            effect = EFFECTS.get(rule.outcome)
            if effect:
                effect(self._data, command)
            self._state = rule.dst
        # rejected: nothing mutates (requirement 12)
        self.last_transition = key
        return Result(rule.accepted, rule.outcome)
