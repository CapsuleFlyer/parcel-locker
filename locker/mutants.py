"""Faulty versions (mutants) of the reference SUT, for fault injection.

Each mutant subclasses ``ParcelLocker`` and overrides ``execute`` to introduce ONE
distinct, plausible implementation defect. The reference ``sut.py`` is never
modified. ``expected_equivalent=True`` marks mutants that are *believed* to be
behaviourally equivalent to the original (no observable difference); this belief
is cross-checked by a bounded exhaustive search in ``mutation.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from .sut import ParcelLocker
from .types import Command, Operation as Op, Result, State


@dataclass(frozen=True)
class MutantSpec:
    id: str
    name: str
    category: str
    description: str
    factory: Callable[[], ParcelLocker]
    expected_equivalent: bool = False
    note: str = ""
    witness: tuple = ()   # hand-written sequence proving the mutant is NOT equivalent


def _reserve(cid: str = "C1") -> Command:
    return Command(Op.RESERVE, customer_id=cid)


def _deposit(code: str = "R-C1") -> Command:
    return Command(Op.DEPOSIT, code=code)


def _retrieve(code: str = "P-C1") -> Command:
    return Command(Op.RETRIEVE, code=code)


_CYCLE = (_reserve(), _deposit(), _retrieve())   # one full delivery cycle


# --- illegal acceptance -------------------------------------------------------
class ReserveWhenOccupied(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.RESERVE and self.state == State.OCCUPIED:
            self.state = State.RESERVED
            self.customer_id = c.customer_id
            self.reservation_code = f"R-{c.customer_id}"
            self.retrieval_code = None
            return Result(True, "reserved")
        return super().execute(c)


class DepositInMaintenance(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.DEPOSIT and self.state == State.MAINTENANCE:
            self.state = State.OCCUPIED
            self.customer_id = c.customer_id
            self.reservation_code = f"R-{c.customer_id}"
            self.retrieval_code = f"P-{c.customer_id}"
            return Result(True, "deposited")
        return super().execute(c)


class RetrieveWithoutAuth(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.RETRIEVE and self.state == State.OCCUPIED:
            self._clear()
            return Result(True, "retrieved")
        return super().execute(c)


class EarlyExpire(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.EXPIRE and self.state == State.RESERVED:
            self._clear()
            return Result(True, "expired")
        return super().execute(c)


class CancelWhenOccupied(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.CANCEL and self.state == State.OCCUPIED:
            self._clear()
            return Result(True, "cancelled")
        return super().execute(c)


class DisableWhenReserved(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.DISABLE and self.state == State.RESERVED:
            self.state = State.MAINTENANCE
            return Result(True, "disabled")
        return super().execute(c)


class DepositIgnoresCode(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.DEPOSIT and self.state == State.RESERVED:
            c = replace(c, code=self.reservation_code)
        return super().execute(c)


class ExpireWhenOccupied(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.EXPIRE and self.state == State.OCCUPIED and c.expired:
            self._clear()
            return Result(True, "expired")
        return super().execute(c)


# --- incomplete clean-up / stale data ------------------------------------------
class StaleRetrievalCode(ParcelLocker):
    def execute(self, c: Command) -> Result:
        keep = self.retrieval_code
        r = super().execute(c)
        if c.operation == Op.RETRIEVE and r.accepted:
            self.retrieval_code = keep
        return r


class StaleCustomerAfterRetrieve(ParcelLocker):
    def execute(self, c: Command) -> Result:
        keep = self.customer_id
        r = super().execute(c)
        if c.operation == Op.RETRIEVE and r.accepted:
            self.customer_id = keep
        return r


class ExpireKeepsCustomer(ParcelLocker):
    def execute(self, c: Command) -> Result:
        keep = self.customer_id
        r = super().execute(c)
        if c.operation == Op.EXPIRE and r.accepted:
            self.customer_id = keep
        return r


# --- state corruption on rejected / unrelated operations -------------------------
class BadDepositWipesCode(ParcelLocker):
    def execute(self, c: Command) -> Result:
        r = super().execute(c)
        if c.operation == Op.DEPOSIT and r.message == "invalid_reservation_code":
            self.reservation_code = None
        return r


class InvalidAccessClearsParcel(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.INVALID_ACCESS and self.state == State.OCCUPIED:
            self.retrieval_code = None
        return super().execute(c)


class RejectedReserveOverwritesCustomer(ParcelLocker):
    def execute(self, c: Command) -> Result:
        if c.operation == Op.RESERVE and self.state == State.RESERVED:
            self.customer_id = c.customer_id  # side effect of a rejected op
        return super().execute(c)


# --- wrong credential policy -------------------------------------------------------
class WrongRetrievalPrefix(ParcelLocker):
    def execute(self, c: Command) -> Result:
        r = super().execute(c)
        if c.operation == Op.DEPOSIT and r.accepted:
            self.retrieval_code = f"R-{self.customer_id}"
        return r


class PrefixCodeMatchOnDeposit(ParcelLocker):
    """Accepts any deposit code that merely *starts with* the right one."""
    def execute(self, c: Command) -> Result:
        if (c.operation == Op.DEPOSIT and self.state == State.RESERVED
                and c.code.startswith(self.reservation_code)):
            c = replace(c, code=self.reservation_code)
        return super().execute(c)


# --- history-dependent faults (probe sequence-based strategies) -------------------
class DoubleCancelWhileOccupiedWipesCode(ParcelLocker):
    """Two consecutive CANCEL attempts on an OCCUPIED locker wipe the retrieval code."""
    def __init__(self):
        super().__init__()
        self._prev_cancel_while_occupied = False

    def execute(self, c: Command) -> Result:
        if c.operation == Op.CANCEL and self.state == State.OCCUPIED:
            if self._prev_cancel_while_occupied:
                self.retrieval_code = None
            self._prev_cancel_while_occupied = True
        else:
            self._prev_cancel_while_occupied = False
        return super().execute(c)


class DisableAfterRetrieveKeepsCustomer(ParcelLocker):
    """DISABLE right after a successful RETRIEVE leaves a stale customer ID."""
    def __init__(self):
        super().__init__()
        self._after_retrieve = False

    def execute(self, c: Command) -> Result:
        r = super().execute(c)
        if c.operation == Op.DISABLE and r.accepted and self._after_retrieve:
            self.customer_id = "STALE"
        self._after_retrieve = c.operation == Op.RETRIEVE and r.accepted
        return r


class ThirdCycleStaleCode(ParcelLocker):
    """The retrieval code is only retained after the 3rd successful retrieval."""
    def __init__(self):
        super().__init__()
        self._retrievals = 0

    def execute(self, c: Command) -> Result:
        keep = self.retrieval_code
        r = super().execute(c)
        if c.operation == Op.RETRIEVE and r.accepted:
            self._retrievals += 1
            if self._retrievals == 3:
                self.retrieval_code = keep
        return r


# --- equivalent mutants (no observable difference) -----------------------------------
class EnableRedundantClear(ParcelLocker):
    """ENABLE also clears all data; data is already empty in MAINTENANCE."""
    def execute(self, c: Command) -> Result:
        r = super().execute(c)
        if c.operation == Op.ENABLE and r.accepted:
            self._clear()
        return r


class DepositRedundantReassign(ParcelLocker):
    """DEPOSIT re-assigns the reservation code to the value it already has."""
    def execute(self, c: Command) -> Result:
        r = super().execute(c)
        if c.operation == Op.DEPOSIT and r.accepted:
            self.reservation_code = f"R-{self.customer_id}"
        return r


class RetrieveUnreachableGuard(ParcelLocker):
    """RETRIEVE gets an extra rejection when customer_id is None in OCCUPIED.

    Equivalent: invariant I3 guarantees customer_id is never None when OCCUPIED, so the
    extra branch is unreachable (equivalence needs reasoning about reachable states).
    """
    def execute(self, c: Command) -> Result:
        if c.operation == Op.RETRIEVE and self.state == State.OCCUPIED and self.customer_id is None:
            return Result(False, "invalid_retrieval_code")
        return super().execute(c)


class ExpireUnreachableGuard(ParcelLocker):
    """EXPIRE additionally requires reservation_code to be None-free; always true in RESERVED (I2)."""
    def execute(self, c: Command) -> Result:
        if (c.operation == Op.EXPIRE and self.state == State.RESERVED and c.expired
                and self.reservation_code is None):
            return Result(False, "not_expired")
        return super().execute(c)


MUTANTS: tuple[MutantSpec, ...] = (
    MutantSpec("M01", "ReserveWhenOccupied", "illegal acceptance",
               "RESERVE is accepted in OCCUPIED and overwrites the parcel owner.",
               ReserveWhenOccupied,
               witness=(_reserve(), _deposit(), _reserve("C2"))),
    MutantSpec("M02", "DepositInMaintenance", "illegal acceptance",
               "DEPOSIT is accepted in MAINTENANCE.", DepositInMaintenance,
               witness=(Command(Op.DISABLE), _deposit())),
    MutantSpec("M03", "RetrieveWithoutAuth", "missing authentication",
               "RETRIEVE ignores the retrieval code.", RetrieveWithoutAuth,
               witness=(_reserve(), _deposit(), _retrieve("WRONG"))),
    MutantSpec("M04", "EarlyExpire", "expiry policy",
               "EXPIRE succeeds although expired=False.", EarlyExpire,
               witness=(_reserve(), Command(Op.EXPIRE, expired=False))),
    MutantSpec("M05", "CancelWhenOccupied", "illegal acceptance",
               "CANCEL is accepted in OCCUPIED (parcel is silently dropped).", CancelWhenOccupied,
               witness=(_reserve(), _deposit(), Command(Op.CANCEL))),
    MutantSpec("M06", "DisableWhenReserved", "illegal acceptance",
               "DISABLE is accepted in RESERVED (booking data kept in MAINTENANCE).",
               DisableWhenReserved, witness=(_reserve(), Command(Op.DISABLE))),
    MutantSpec("M07", "DepositIgnoresCode", "missing authentication",
               "DEPOSIT accepts any reservation code.", DepositIgnoresCode,
               witness=(_reserve(), _deposit("WRONG"))),
    MutantSpec("M08", "ExpireWhenOccupied", "illegal acceptance",
               "EXPIRE with expired=True is accepted in OCCUPIED.", ExpireWhenOccupied,
               witness=(_reserve(), _deposit(), Command(Op.EXPIRE, expired=True))),
    MutantSpec("M09", "StaleRetrievalCode", "stale data",
               "Retrieval code is retained after a successful retrieval.", StaleRetrievalCode,
               witness=_CYCLE),
    MutantSpec("M10", "StaleCustomerAfterRetrieve", "stale data",
               "Customer ID is retained after a successful retrieval.", StaleCustomerAfterRetrieve,
               witness=_CYCLE),
    MutantSpec("M11", "ExpireKeepsCustomer", "stale data",
               "Customer ID is retained after a successful expiry.", ExpireKeepsCustomer,
               witness=(_reserve(), Command(Op.EXPIRE, expired=True))),
    MutantSpec("M12", "BadDepositWipesCode", "state change on rejection",
               "A deposit with a wrong code erases the stored reservation code.",
               BadDepositWipesCode, witness=(_reserve(), _deposit("WRONG"))),
    MutantSpec("M13", "InvalidAccessClearsParcel", "state change on rejection",
               "INVALID_ACCESS in OCCUPIED erases the retrieval code.", InvalidAccessClearsParcel,
               witness=(_reserve(), _deposit(), Command(Op.INVALID_ACCESS, code="INVALID"))),
    MutantSpec("M14", "RejectedReserveOverwritesCustomer", "state change on rejection",
               "A rejected RESERVE in RESERVED still overwrites the customer ID "
               "(only observable when the new ID differs).", RejectedReserveOverwritesCustomer,
               witness=(_reserve("C1"), _reserve("C2"))),
    MutantSpec("M15", "WrongRetrievalPrefix", "wrong credential policy",
               "Retrieval code is issued as R-<id> instead of P-<id>.", WrongRetrievalPrefix,
               witness=(_reserve(), _deposit())),
    MutantSpec("M16", "PrefixCodeMatchOnDeposit", "weak authentication",
               "DEPOSIT accepts any code that starts with the correct reservation code.",
               PrefixCodeMatchOnDeposit,
               note="Only observable with a near-miss credential such as 'R-C1x'; "
                    "run with --near-miss to add that input class.",
               witness=(_reserve(), _deposit("R-C1x"))),
    MutantSpec("M17", "DoubleCancelWhileOccupiedWipesCode", "history-dependent (pair)",
               "Two consecutive rejected CANCELs on an OCCUPIED locker wipe the retrieval code.",
               DoubleCancelWhileOccupiedWipesCode,
               note="Triggered by the transition pair CANCEL[not_reserved] -> CANCEL[not_reserved] "
                    "in OCCUPIED. Added to probe pair-based testing (see threats to validity).",
               witness=(_reserve(), _deposit(), Command(Op.CANCEL), Command(Op.CANCEL))),
    MutantSpec("M18", "DisableAfterRetrieveKeepsCustomer", "history-dependent (pair)",
               "DISABLE immediately after a successful RETRIEVE leaves a stale customer ID.",
               DisableAfterRetrieveKeepsCustomer,
               note="Triggered by the pair RETRIEVE[retrieved] -> DISABLE[disabled].",
               witness=_CYCLE + (Command(Op.DISABLE),)),
    MutantSpec("M19", "ThirdCycleStaleCode", "history-dependent (long)",
               "The retrieval code is retained after the 3rd successful retrieval in a run.",
               ThirdCycleStaleCode,
               note="Needs 3 complete delivery cycles (>= 9 valid steps): beyond length-2 "
                    "history, so transition-pair coverage does not guarantee exposing it.",
               witness=_CYCLE * 3),
    MutantSpec("E01", "EnableRedundantClear", "equivalent",
               "ENABLE additionally clears data that is already empty.",
               EnableRedundantClear, expected_equivalent=True),
    MutantSpec("E02", "DepositRedundantReassign", "equivalent",
               "DEPOSIT re-assigns the reservation code to its existing value.",
               DepositRedundantReassign, expected_equivalent=True),
    MutantSpec("E03", "RetrieveUnreachableGuard", "equivalent",
               "RETRIEVE gains a guard on customer_id being None while OCCUPIED.",
               RetrieveUnreachableGuard, expected_equivalent=True,
               note="Equivalent by invariant I3: customer_id is never None in OCCUPIED."),
    MutantSpec("E04", "ExpireUnreachableGuard", "equivalent",
               "EXPIRE gains a guard on reservation_code being None while RESERVED.",
               ExpireUnreachableGuard, expected_equivalent=True,
               note="Equivalent by invariant I2: reservation_code is never None in RESERVED."),
)
