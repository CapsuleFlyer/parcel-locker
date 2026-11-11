"""THE ONE FILE TO EDIT FOR A "CHANGE REQUEST".

Every rule an instructor is likely to tweak live is a plain field of ``POLICY`` below.
The model (``model.py``), the oracle's state invariants (``oracle.py``), the generators'
input alphabet (``generators.py``) and the policy-driven SUT (``policy_sut.py``) all read
from it, so you edit ONE value, then run:

    python -m locker change                  # model(POLICY) vs. original SUT and vs. PolicySUT(POLICY)
    python -m locker change --preset cancel_when_occupied
    python -m locker change --set cancel_from=RESERVED,OCCUPIED --set expire_requires_flag=false

What you will see (and what it means):
  * vs the ORIGINAL (provided) SUT: tests FAIL. That is correct: the SUT does not implement the
    new rule, so the framework detects the changed behaviour (a nice live "fault detection" demo).
  * vs ``PolicySUT(POLICY)``: tests PASS. That SUT is a hand-written if-chain that implements the
    same knobs, i.e. "the system after the change request was implemented".

What this file CANNOT express (needs real code changes, see docs/CHANGE_REQUESTS.md):
a brand-new state, a brand-new operation, counters (e.g. lock-out after 3 wrong codes), a
disabled-but-still-holding-a-parcel state. Those are code edits in model.py / types.py /
generators.py (+ a SUT change), and the recipes are written down in the doc.

Independence note: this file only holds *requirement-level facts* (which states allow which
operation, what a credential looks like). The decision logic that turns them into expected results
stays in ``model.py`` (declarative table) and is independent of the SUT's if-chain.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, fields, replace
from typing import Iterator

from .types import State

A, R, O, M = State.AVAILABLE, State.RESERVED, State.OCCUPIED, State.MAINTENANCE


def _states(*s: State) -> frozenset:
    return frozenset(s)


@dataclass(frozen=True)
class Policy:
    """All tweakable behaviour. Defaults == the rules in data/requirements.md (the baseline)."""

    # ---- credentials (requirements 2 and 5) --------------------------------------------------
    # Templates; {cid} is the customer id. "Retrieval auth mechanism changes" -> edit these.
    reservation_code_template: str = "R-{cid}"
    retrieval_code_template: str = "P-{cid}"
    # Auth change: RETRIEVE also accepts the reservation code (either credential opens the locker).
    retrieve_also_accepts_reservation_code: bool = False

    # ---- which states each operation is accepted from ----------------------------------------
    reserve_from: frozenset = field(default_factory=lambda: _states(A))          # subset of {A, M}
    cancel_from: frozenset = field(default_factory=lambda: _states(R))           # subset of {R, O}
    expire_from: frozenset = field(default_factory=lambda: _states(R))           # subset of {R, O}
    disable_from: frozenset = field(default_factory=lambda: _states(A))          # subset of {A, R, O}
    enable_from: frozenset = field(default_factory=lambda: _states(M))           # subset of {M}

    # ---- extra conditions --------------------------------------------------------------------
    # "Cancellation allowed under an additional condition": CANCEL must carry the reservation code.
    cancel_requires_code: bool = False
    # Expiry policy: with False, EXPIRE is accepted whenever the state allows it (flag ignored).
    expire_requires_flag: bool = True
    # Expiry policy: where an expired reservation goes (data is always cleared). {A, M}.
    expire_target: State = A

    # NOTE on data: every accepted CANCEL / EXPIRE / RETRIEVE / DISABLE clears all customer and
    # credential data (requirement 7, A3). DISABLE from RESERVED/OCCUPIED therefore discards the
    # booking/parcel. A maintenance state that *keeps* the parcel needs a new state; see the doc.

    # -------------------------------------------------------------------------------------- #
    def reservation_code(self, customer_id: str) -> str:
        return self.reservation_code_template.format(cid=customer_id)

    def retrieval_code(self, customer_id: str) -> str:
        return self.retrieval_code_template.format(cid=customer_id)

    def validate(self) -> "Policy":
        def sub(name: str, allowed: set) -> None:
            value = getattr(self, name)
            if not isinstance(value, frozenset):
                raise ValueError(f"{name} must be a frozenset of State, got {type(value).__name__}")
            bad = value - allowed
            if bad:
                raise ValueError(f"{name} may only contain {sorted(s.value for s in allowed)}; "
                                 f"got {sorted(s.value for s in bad)}")

        sub("reserve_from", {A, M})
        sub("cancel_from", {R, O})
        sub("expire_from", {R, O})
        sub("disable_from", {A, R, O})
        sub("enable_from", {M})
        if not self.reserve_from:
            raise ValueError("reserve_from must not be empty (the locker could never be booked)")
        if self.expire_target not in (A, M):
            raise ValueError("expire_target must be AVAILABLE or MAINTENANCE")
        for name in ("reservation_code_template", "retrieval_code_template"):
            tpl = getattr(self, name)
            if "{cid}" not in tpl:
                raise ValueError(f"{name} must contain '{{cid}}' so codes stay customer-specific")
            tpl.format(cid="X")  # raises on stray braces
        if self.reservation_code("C1") == self.retrieval_code("C1") and \
                not self.retrieve_also_accepts_reservation_code:
            raise ValueError("reservation and retrieval templates produce the SAME code; the "
                             "'wrong credential type' input class would be meaningless. Change "
                             "one template or set retrieve_also_accepts_reservation_code=True.")
        return self

    def diff(self, other: "Policy") -> dict:
        """Fields where ``self`` differs from ``other``: {name: (self_value, other_value)}."""
        return {f.name: (getattr(self, f.name), getattr(other, f.name))
                for f in fields(self) if getattr(self, f.name) != getattr(other, f.name)}


def fmt_value(v) -> str:
    if isinstance(v, frozenset):
        return "{" + ", ".join(sorted(s.value for s in v)) + "}"
    if isinstance(v, State):
        return v.value
    return repr(v)


# =========================================================================================== #
#  EDIT HERE.  Change a value, save, run `python -m locker change`.
#  (BASELINE below is the untouched requirement set; tests and presets compare against it.)
# =========================================================================================== #
BASELINE = Policy().validate()

POLICY = Policy(
    reservation_code_template="R-{cid}",
    retrieval_code_template="P-{cid}",
    retrieve_also_accepts_reservation_code=False,
    reserve_from=_states(A),                 # e.g. _states(A, M)
    cancel_from=_states(R),                  # e.g. _states(R, O)
    expire_from=_states(R),                  # e.g. _states(R, O)
    disable_from=_states(A),                 # e.g. _states(A, O)  or  _states(A, R, O)
    enable_from=_states(M),
    cancel_requires_code=False,              # True: CANCEL needs the reservation code
    expire_requires_flag=True,               # False: EXPIRE ignores the expired flag
    expire_target=A,                         # e.g. M (expired locker goes to inspection)
).validate()


# =========================================================================================== #
#  Ready-made "instructor change requests" (each is BASELINE + a few edits)
# =========================================================================================== #
PRESETS: dict[str, tuple[str, Policy]] = {
    "disable_when_occupied": (
        "Maintenance may now be initiated while a compartment is OCCUPIED (parcel is removed/discarded).",
        replace(BASELINE, disable_from=_states(A, O))),
    "disable_when_busy": (
        "Maintenance may start from RESERVED or OCCUPIED too (booking/parcel discarded).",
        replace(BASELINE, disable_from=_states(A, R, O))),
    "cancel_when_occupied": (
        "A reservation may also be cancelled once the parcel is deposited (parcel returned).",
        replace(BASELINE, cancel_from=_states(R, O))),
    "cancel_needs_code": (
        "Cancelling needs an additional condition: the reservation code must be supplied.",
        replace(BASELINE, cancel_requires_code=True)),
    "retrieve_either_code": (
        "Retrieval authentication changes: the reservation code now also opens an occupied locker.",
        replace(BASELINE, retrieve_also_accepts_reservation_code=True)),
    "new_code_format": (
        "Credential format changes: reservation code RSV-<id>-A, retrieval code PIN-<id>.",
        replace(BASELINE, reservation_code_template="RSV-{cid}-A", retrieval_code_template="PIN-{cid}")),
    "expire_ignores_flag": (
        "Expiry policy: any EXPIRE on a RESERVED locker is accepted (no expired condition).",
        replace(BASELINE, expire_requires_flag=False)),
    "expire_to_maintenance": (
        "Expiry policy: an expired reservation sends the locker to MAINTENANCE for inspection.",
        replace(BASELINE, expire_target=M)),
    "expire_when_occupied": (
        "Expiry policy: an uncollected OCCUPIED parcel can expire too (parcel discarded, locker free).",
        replace(BASELINE, expire_from=_states(R, O))),
    "reserve_in_maintenance": (
        "A locker in MAINTENANCE may be pre-reserved (moves straight to RESERVED).",
        replace(BASELINE, reserve_from=_states(A, M))),
}


# =========================================================================================== #
#  Active policy (what model / oracle / generators use right now)
# =========================================================================================== #
_active: Policy = POLICY


def get_policy() -> Policy:
    return _active


def set_policy(policy: Policy) -> None:
    global _active
    _active = policy.validate()


@contextmanager
def use_policy(policy: Policy) -> Iterator[Policy]:
    """Temporarily switch the whole pipeline (model, oracle, generators, metrics) to ``policy``."""
    global _active
    previous, _active = _active, policy.validate()
    try:
        yield _active
    finally:
        _active = previous


def parse_overrides(base: Policy, assignments: list[str]) -> Policy:
    """Apply ``name=value`` strings (CLI ``--set``) to ``base``.

    Sets: ``cancel_from=RESERVED,OCCUPIED`` (use ``none`` for empty); bools: true/false;
    state: ``expire_target=MAINTENANCE``; templates: ``retrieval_code_template=PIN-{cid}``.
    """
    names = {f.name: f for f in fields(Policy)}
    values = {}
    for item in assignments:
        if "=" not in item:
            raise ValueError(f"--set expects name=value, got {item!r}")
        key, raw = item.split("=", 1)
        key = key.strip()
        if key not in names:
            raise ValueError(f"unknown policy field {key!r}; choose from: {', '.join(names)}")
        current = getattr(base, key)
        try:
            if isinstance(current, frozenset):
                parts = [] if raw.strip().lower() in ("", "none") else [p.strip().upper() for p in raw.split(",")]
                values[key] = frozenset(State[p] for p in parts)
            elif isinstance(current, bool):
                if raw.strip().lower() not in ("true", "false"):
                    raise ValueError("expected true or false")
                values[key] = raw.strip().lower() == "true"
            elif isinstance(current, State):
                values[key] = State[raw.strip().upper()]
            else:
                values[key] = raw
        except KeyError as exc:
            raise ValueError(f"{key}: unknown state {exc.args[0]!r}; use "
                             f"{', '.join(s.name for s in State)}") from None
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from None
    return replace(base, **values).validate()
