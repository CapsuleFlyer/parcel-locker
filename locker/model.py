"""Independent executable state-machine model of the Smart Parcel Locker.

Derived ONLY from ``data/requirements.md`` / the assignment text. It never
imports or inspects the SUT.

Design: the behaviour is a *declarative rule table* keyed by ``(state, operation)``.
Each key maps to an ordered list of guarded rules (first matching guard wins);
any ``(state, operation)`` pair without a matching rule falls back to a default
rejection that leaves the state untouched (requirement 12). This is deliberately
structured differently from the SUT's imperative if-chain so that the oracle is
not a copy of the implementation.

The table is *built from* ``rules_config.Policy`` (``build_rules``): the tweakable facts
(which states allow which operation, credential formats, expiry policy, ...) live in
``rules_config.py`` so a rule change in the viva is a one-value edit there. The baseline
policy reproduces data/requirements.md exactly (35 transitions, 305 pairs).

The same table is used to derive the *transition catalogue* (the denominator for
transition coverage) and the *transition-pair catalogue*.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Optional

from .rules_config import Policy, get_policy
from .types import Command, Operation, Result, Snapshot, State

A, R, O, M = State.AVAILABLE, State.RESERVED, State.OCCUPIED, State.MAINTENANCE
Op = Operation


# --------------------------------------------------------------------------- #
# Credential policy (requirements 2 and 5): the formats live in rules_config.Policy
# --------------------------------------------------------------------------- #
def reservation_code_for(customer_id: str, policy: Optional[Policy] = None) -> str:
    return (policy or get_policy()).reservation_code(customer_id)


def retrieval_code_for(customer_id: str, policy: Optional[Policy] = None) -> str:
    return (policy or get_policy()).retrieval_code(customer_id)


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
# Transition rules (requirements 1, 3, 4, 6, 8, 9, 10), built from the policy
# --------------------------------------------------------------------------- #
def _in_state_order(states) -> list[State]:
    return [s for s in State if s in states]


@lru_cache(maxsize=None)
def build_rules(policy: Policy) -> dict[tuple[State, Operation], list[Rule]]:
    """The declarative rule table for ``policy`` (cached; do not mutate the result)."""
    rules: dict[tuple[State, Operation], list[Rule]] = {}

    for s in _in_state_order(policy.reserve_from):
        rules[(s, Op.RESERVE)] = [Rule("reserved", R, True)]

    for s in _in_state_order(policy.cancel_from):
        if policy.cancel_requires_code:
            rules[(s, Op.CANCEL)] = [Rule("cancelled", A, True, _code_matches_reservation),
                                     Rule("invalid_reservation_code", s, False)]
        else:
            rules[(s, Op.CANCEL)] = [Rule("cancelled", A, True)]

    rules[(R, Op.DEPOSIT)] = [Rule("deposited", O, True, _code_matches_reservation),
                              Rule("invalid_reservation_code", R, False)]

    if policy.retrieve_also_accepts_reservation_code:
        retrieve_guard: Guard = lambda d, c: (c.code == d.retrieval_code or c.code == d.reservation_code)
    else:
        retrieve_guard = _code_matches_retrieval
    rules[(O, Op.RETRIEVE)] = [Rule("retrieved", A, True, retrieve_guard),
                               Rule("invalid_retrieval_code", O, False)]

    for s in _in_state_order(policy.expire_from):
        if policy.expire_requires_flag:
            rules[(s, Op.EXPIRE)] = [Rule("expired", policy.expire_target, True, _is_expired),
                                     Rule("not_expired", s, False)]
        else:
            rules[(s, Op.EXPIRE)] = [Rule("expired", policy.expire_target, True)]

    for s in _in_state_order(policy.disable_from):
        rules[(s, Op.DISABLE)] = [Rule("disabled", M, True)]

    for s in _in_state_order(policy.enable_from):
        rules[(s, Op.ENABLE)] = [Rule("enabled", A, True)]
    return rules


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
def _on_clear(d: _Data, c: Command) -> None:
    d.clear()


@lru_cache(maxsize=None)
def effects_for(policy: Policy) -> dict[str, Callable[[_Data, Command], None]]:
    def on_reserved(d: _Data, c: Command) -> None:
        d.customer_id = c.customer_id
        d.reservation_code = policy.reservation_code(c.customer_id)
        d.retrieval_code = None

    def on_deposited(d: _Data, c: Command) -> None:
        # Assumption A3: the reservation code stays stored while OCCUPIED; only
        # retrieval/cancel/expire/disable clear "all" data (requirement 7).
        d.retrieval_code = policy.retrieval_code(d.customer_id)

    return {
        "reserved": on_reserved,
        "deposited": on_deposited,
        "cancelled": _on_clear,
        "retrieved": _on_clear,
        "expired": _on_clear,
        "disabled": _on_clear,   # no-op from AVAILABLE; discards booking/parcel from RESERVED/OCCUPIED
        # "enabled": no data change (data is already empty in MAINTENANCE)
    }


# --------------------------------------------------------------------------- #
# Catalogues (coverage denominators)
# --------------------------------------------------------------------------- #
def transition_catalogue(policy: Optional[Policy] = None) -> tuple[TransitionKey, ...]:
    """Every distinct (src, op, outcome, dst) the model can produce."""
    table = build_rules(policy or get_policy())
    out: list[TransitionKey] = []
    for s in State:
        for op in Operation:
            rules = table.get((s, op), [])
            for r in rules:
                out.append(TransitionKey(s, op, r.outcome, r.dst, r.accepted))
            if not any(r.guard is None for r in rules):
                out.append(TransitionKey(s, op, DEFAULT_REJECTION[op], s, False))
    return tuple(out)


def transition_pairs(policy: Optional[Policy] = None) -> tuple[tuple[TransitionKey, TransitionKey], ...]:
    """Defined adjacent pairs (t1, t2): t1 ends in the state where t2 starts.

    Rejected operations are self-loops, so they take part in pairs too. Every
    such pair is realisable because a transition depends only on the abstract
    state and the input class, not on history.
    """
    cat = transition_catalogue(policy)
    return tuple((a, b) for a in cat for b in cat if a.dst == b.src)


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #
class LockerModel:
    """Executable oracle: ``step(command)`` returns the *expected* Result."""

    def __init__(self, policy: Optional[Policy] = None):
        self.policy: Policy = policy or get_policy()
        self._rules = build_rules(self.policy)
        self._effects = effects_for(self.policy)
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
        # The (cached, immutable) policy/rule table is shared; only the mutable parts are copied.
        twin = LockerModel.__new__(LockerModel)
        twin.policy, twin._rules, twin._effects = self.policy, self._rules, self._effects
        twin._state = self._state
        twin._data = copy.copy(self._data)
        twin.last_transition = self.last_transition
        return twin

    def _match(self, command: Command) -> Rule:
        for rule in self._rules.get((self._state, command.operation), ()):
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
            effect = self._effects.get(rule.outcome)
            if effect:
                effect(self._data, command)
            self._state = rule.dst
        # rejected: nothing mutates (requirement 12)
        self.last_transition = key
        return Result(rule.accepted, rule.outcome)
