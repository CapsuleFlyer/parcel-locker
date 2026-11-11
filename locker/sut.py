from .types import State, Operation, Command, Result, Snapshot

class ParcelLocker:
    """Reference System Under Test. Students should test it, not rewrite it."""
    def __init__(self):
        self.state = State.AVAILABLE
        self.customer_id = None
        self.reservation_code = None
        self.retrieval_code = None

    def snapshot(self):
        return Snapshot(self.state, self.customer_id, self.reservation_code, self.retrieval_code)

    def execute(self, command: Command) -> Result:
        op = command.operation
        if op == Operation.RESERVE:
            if self.state != State.AVAILABLE:
                return Result(False, "locker_not_available")
            self.state = State.RESERVED
            self.customer_id = command.customer_id
            self.reservation_code = f"R-{command.customer_id}"
            return Result(True, "reserved")
        if op == Operation.CANCEL:
            if self.state != State.RESERVED:
                return Result(False, "not_reserved")
            self._clear()
            return Result(True, "cancelled")
        if op == Operation.DEPOSIT:
            if self.state != State.RESERVED:
                return Result(False, "not_reserved")
            if command.code != self.reservation_code:
                return Result(False, "invalid_reservation_code")
            self.state = State.OCCUPIED
            self.retrieval_code = f"P-{self.customer_id}"
            return Result(True, "deposited")
        if op == Operation.RETRIEVE:
            if self.state != State.OCCUPIED:
                return Result(False, "no_parcel")
            if command.code != self.retrieval_code:
                return Result(False, "invalid_retrieval_code")
            self._clear()
            return Result(True, "retrieved")
        if op == Operation.EXPIRE:
            if self.state != State.RESERVED:
                return Result(False, "not_reserved")
            if not command.expired:
                return Result(False, "not_expired")
            self._clear()
            return Result(True, "expired")
        if op == Operation.DISABLE:
            if self.state != State.AVAILABLE:
                return Result(False, "cannot_disable")
            self.state = State.MAINTENANCE
            return Result(True, "disabled")
        if op == Operation.ENABLE:
            if self.state != State.MAINTENANCE:
                return Result(False, "not_in_maintenance")
            self.state = State.AVAILABLE
            return Result(True, "enabled")
        if op == Operation.INVALID_ACCESS:
            return Result(False, "invalid_access")
        return Result(False, "unknown_operation")

    def _clear(self):
        self.state = State.AVAILABLE
        self.customer_id = None
        self.reservation_code = None
        self.retrieval_code = None
