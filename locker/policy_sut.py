"""``PolicySUT``: "the system after the change request was implemented".

The provided reference SUT (``sut.py``) is never modified. For change-request drills we need
an implementation that follows the *changed* rules, so this subclass re-implements
``execute`` as an imperative if-chain (same style as the original SUT, deliberately NOT the
model's declarative table) whose behaviour is steered by the same ``rules_config.Policy``.

With the baseline policy it behaves exactly like ``ParcelLocker`` (checked in
``tests/test_policy.py`` by exhaustive bounded comparison).

Use:  ``SequenceRunner(sut_factory=lambda: PolicySUT(policy))``
"""
from __future__ import annotations

from typing import Optional

from .rules_config import Policy, get_policy
from .sut import ParcelLocker
from .types import Command, Operation, Result, State


class PolicySUT(ParcelLocker):
    def __init__(self, policy: Optional[Policy] = None):
        super().__init__()
        self.policy = policy or get_policy()

    def execute(self, command: Command) -> Result:
        p, op = self.policy, command.operation

        if op == Operation.RESERVE:
            if self.state not in p.reserve_from:
                return Result(False, "locker_not_available")
            self.state = State.RESERVED
            self.customer_id = command.customer_id
            self.reservation_code = p.reservation_code(command.customer_id)
            return Result(True, "reserved")

        if op == Operation.CANCEL:
            if self.state not in p.cancel_from:
                return Result(False, "not_reserved")
            if p.cancel_requires_code and command.code != self.reservation_code:
                return Result(False, "invalid_reservation_code")
            self._clear()
            return Result(True, "cancelled")

        if op == Operation.DEPOSIT:
            if self.state != State.RESERVED:
                return Result(False, "not_reserved")
            if command.code != self.reservation_code:
                return Result(False, "invalid_reservation_code")
            self.state = State.OCCUPIED
            self.retrieval_code = p.retrieval_code(self.customer_id)
            return Result(True, "deposited")

        if op == Operation.RETRIEVE:
            if self.state != State.OCCUPIED:
                return Result(False, "no_parcel")
            accepted_codes = [self.retrieval_code]
            if p.retrieve_also_accepts_reservation_code:
                accepted_codes.append(self.reservation_code)
            if command.code not in accepted_codes:
                return Result(False, "invalid_retrieval_code")
            self._clear()
            return Result(True, "retrieved")

        if op == Operation.EXPIRE:
            if self.state not in p.expire_from:
                return Result(False, "not_reserved")
            if p.expire_requires_flag and not command.expired:
                return Result(False, "not_expired")
            self._clear()
            self.state = p.expire_target
            return Result(True, "expired")

        if op == Operation.DISABLE:
            if self.state not in p.disable_from:
                return Result(False, "cannot_disable")
            self._clear()                      # booking/parcel (if any) is discarded
            self.state = State.MAINTENANCE
            return Result(True, "disabled")

        if op == Operation.ENABLE:
            if self.state not in p.enable_from:
                return Result(False, "not_in_maintenance")
            self.state = State.AVAILABLE
            return Result(True, "enabled")

        if op == Operation.INVALID_ACCESS:
            return Result(False, "invalid_access")
        return Result(False, "unknown_operation")
