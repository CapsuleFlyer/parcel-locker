"""Held-out fault-injection mutants H01..H12 (independently authored)."""
from .sut import ParcelLocker
from .types import Command, Operation as Op, Result, State
from .mutants import MutantSpec


def C(op, cid="C1", code="", expired=False):
    return Command(op, cid, code, expired)


class H01(ParcelLocker):
    """Reservation code normalises customer id to upper case."""
    def execute(self, command):
        r = super().execute(command)
        if command.operation == Op.RESERVE and r.accepted:
            self.reservation_code = f"R-{command.customer_id.upper()}"
        return r


class H02(ParcelLocker):
    """Customer C2 reservations expire without the expired flag."""
    def execute(self, command):
        if (command.operation == Op.EXPIRE and self.state == State.RESERVED
                and self.customer_id == "C2"):
            self._clear()
            return Result(True, "expired")
        return super().execute(command)


class H03(ParcelLocker):
    """Message-only: successful deposit reports a different message."""
    def execute(self, command):
        r = super().execute(command)
        if command.operation == Op.DEPOSIT and r.accepted:
            return Result(True, "deposit_ok")
        return r


class H04(ParcelLocker):
    """Message-only: wrong retrieval code reports the reservation-code message."""
    def execute(self, command):
        r = super().execute(command)
        if r.message == "invalid_retrieval_code":
            return Result(False, "invalid_reservation_code")
        return r


class H05(ParcelLocker):
    """Third successful retrieval forgets to clear the customer id."""
    def __init__(self):
        super().__init__()
        self._retrievals = 0

    def execute(self, command):
        cid = self.customer_id
        r = super().execute(command)
        if command.operation == Op.RETRIEVE and r.accepted:
            self._retrievals += 1
            if self._retrievals == 3:
                self.customer_id = cid
        return r


class H06(ParcelLocker):
    """Rejected deposit (wrong code) leaks a retrieval code into state."""
    def execute(self, command):
        r = super().execute(command)
        if r.message == "invalid_reservation_code":
            self.retrieval_code = f"P-{self.customer_id}"
        return r


class H07(ParcelLocker):
    """INVALID_ACCESS while occupied wipes the stored retrieval code."""
    def execute(self, command):
        if command.operation == Op.INVALID_ACCESS and self.state == State.OCCUPIED:
            self.retrieval_code = None
        return super().execute(command)


class H08(ParcelLocker):
    """RESERVE immediately after a successful EXPIRE is wrongly rejected."""
    def __init__(self):
        super().__init__()
        self._prev_expired = False

    def execute(self, command):
        if command.operation == Op.RESERVE and self._prev_expired:
            self._prev_expired = False
            return Result(False, "locker_not_available")
        r = super().execute(command)
        self._prev_expired = command.operation == Op.EXPIRE and r.accepted
        return r


class H09(ParcelLocker):
    """DISABLE also accepted while RESERVED (keeps customer data)."""
    def execute(self, command):
        if command.operation == Op.DISABLE and self.state == State.RESERVED:
            self.state = State.MAINTENANCE
            return Result(True, "disabled")
        return super().execute(command)


class H10(ParcelLocker):
    """Retrieval code comparison only checks the first three characters."""
    def execute(self, command):
        if (command.operation == Op.RETRIEVE and self.state == State.OCCUPIED
                and command.code[:3] == self.retrieval_code[:3]):
            self._clear()
            return Result(True, "retrieved")
        return super().execute(command)


class H11(ParcelLocker):
    """EQUIVALENT: retrieval code derived from stored reservation code."""
    def execute(self, command):
        if (command.operation == Op.DEPOSIT and self.state == State.RESERVED
                and command.code == self.reservation_code):
            self.state = State.OCCUPIED
            self.retrieval_code = "P-" + self.reservation_code[2:]
            return Result(True, "deposited")
        return super().execute(command)


class H12(ParcelLocker):
    """EQUIVALENT: cancel does not reset retrieval_code."""
    def execute(self, command):
        if command.operation == Op.CANCEL and self.state == State.RESERVED:
            self.state = State.AVAILABLE
            self.customer_id = None
            self.reservation_code = None
            return Result(True, "cancelled")
        return super().execute(command)


R, D, T = Op.RESERVE, Op.DEPOSIT, Op.RETRIEVE
_cycle = (C(R), C(D, code="R-C1"), C(T, code="P-C1"))

HELDOUT_MUTANTS: tuple[MutantSpec, ...] = (
    MutantSpec("H01", "case_folded_reservation_code", "input-specific",
               "Reservation code upper-cases the customer id; lowercase ids break deposit.",
               H01, witness=(C(R, "c1"), C(D, "c1", "R-c1"))),
    MutantSpec("H02", "c2_expires_without_flag", "input-specific",
               "EXPIRE for customer C2 ignores the expired flag.",
               H02, witness=(C(R, "C2"), C(Op.EXPIRE, "C2", expired=False))),
    MutantSpec("H03", "deposit_message_changed", "message-only",
               "Successful deposit returns 'deposit_ok' instead of 'deposited'.",
               H03, witness=(C(R), C(D, code="R-C1"))),
    MutantSpec("H04", "wrong_retrieval_message", "message-only",
               "Wrong retrieval code reports invalid_reservation_code.",
               H04, witness=(C(R), C(D, code="R-C1"), C(T, code="WRONG"))),
    MutantSpec("H05", "third_retrieve_keeps_customer", "history-dependent",
               "Third successful retrieval leaves customer_id set.",
               H05, witness=_cycle * 3),
    MutantSpec("H06", "rejected_deposit_leaks_code", "rejected-mutation",
               "Rejected deposit with wrong code sets retrieval_code.",
               H06, witness=(C(R), C(D, code="WRONG"))),
    MutantSpec("H07", "invalid_access_wipes_code", "rejected-mutation",
               "INVALID_ACCESS in OCCUPIED clears retrieval_code.",
               H07, witness=(C(R), C(D, code="R-C1"), C(Op.INVALID_ACCESS))),
    MutantSpec("H08", "reserve_after_expire_rejected", "history-dependent",
               "RESERVE directly following a successful EXPIRE is rejected.",
               H08, witness=(C(R), C(Op.EXPIRE, expired=True), C(R))),
    MutantSpec("H09", "disable_from_reserved", "guard",
               "DISABLE accepted in RESERVED.",
               H09, witness=(C(R), C(Op.DISABLE))),
    MutantSpec("H10", "retrieve_prefix_check", "input-specific",
               "Retrieval code only compared on first 3 chars (P-C1 vs P-C2 match).",
               H10, witness=(C(R), C(D, code="R-C1"), C(T, code="P-C2"))),
    MutantSpec("H11", "retrieval_code_from_reservation_code", "equivalent",
               "Retrieval code built from reservation_code[2:] instead of customer_id.",
               H11, expected_equivalent=True,
               note="In RESERVED, reservation_code is always 'R-'+customer_id, so "
                    "'P-'+reservation_code[2:] == 'P-'+customer_id for every reachable state."),
    MutantSpec("H12", "cancel_keeps_retrieval_code", "equivalent",
               "CANCEL does not reset retrieval_code.",
               H12, expected_equivalent=True,
               note="retrieval_code is None in every RESERVED state (set only on deposit, "
                    "cleared on every return to AVAILABLE), so skipping the reset is unobservable."),
)
