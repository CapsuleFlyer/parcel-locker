"""Deliberately WRONG variants of the model, used to validate the framework from the other side.

If the model (oracle) were mis-specified, running the *reference SUT* against it must produce
failures. ``extended.model_mutation`` checks that every wrong model is exposed by generated tests,
i.e. the framework can reveal a model that disagrees with the real behaviour.
"""
from __future__ import annotations

from .model import LockerModel, Rule, State, Op, TransitionKey
from .types import Command

A, R, O, M = State.AVAILABLE, State.RESERVED, State.OCCUPIED, State.MAINTENANCE


class _Wrong(LockerModel):
    def _alt(self, command: Command):  # return a Rule to override, or None
        return None

    def _match(self, command: Command) -> Rule:
        return self._alt(command) or super()._match(command)


class DisableAllowedWhenOccupied(_Wrong):
    def _alt(self, c):
        if self._state == O and c.operation == Op.DISABLE:
            return Rule("disabled", M, True)


class ExpireIgnoresFlag(_Wrong):
    def _alt(self, c):
        if self._state == R and c.operation == Op.EXPIRE:
            return Rule("expired", A, True)


class DepositAcceptsAnyCode(_Wrong):
    def _alt(self, c):
        if self._state == R and c.operation == Op.DEPOSIT:
            return Rule("deposited", O, True)


class CancelAllowedWhenOccupied(_Wrong):
    def _alt(self, c):
        if self._state == O and c.operation == Op.CANCEL:
            return Rule("cancelled", A, True)


class RetrieveKeepsData(_Wrong):
    """Model forgets requirement 7: retrieval leaves data in place (only state changes)."""
    def step(self, command: Command):
        before = self.snapshot()
        r = super().step(command)
        if r.accepted and command.operation == Op.RETRIEVE:
            self._data.customer_id = before.customer_id
        return r


class InvalidAccessAcceptedWhenAvailable(_Wrong):
    def _alt(self, c):
        if self._state == A and c.operation == Op.INVALID_ACCESS:
            return Rule("invalid_access", A, True)


MODEL_MUTANTS = {
    "DisableAllowedWhenOccupied": DisableAllowedWhenOccupied,
    "ExpireIgnoresFlag": ExpireIgnoresFlag,
    "DepositAcceptsAnyCode": DepositAcceptsAnyCode,
    "CancelAllowedWhenOccupied": CancelAllowedWhenOccupied,
    "RetrieveKeepsData": RetrieveKeepsData,
    "InvalidAccessAcceptedWhenAvailable": InvalidAccessAcceptedWhenAvailable,
}
