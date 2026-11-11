"""Automated test execution engine.

``SequenceRunner.run`` executes one command sequence against a fresh SUT and a
fresh model in lock-step, applying the oracle (``oracle.py``) after every command
and recording the first divergence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from . import oracle
from .model import LockerModel, TransitionKey
from .sut import ParcelLocker
from .types import Command, Operation, Result, Snapshot


def format_command(c: Command) -> str:
    op = c.operation
    if op == Operation.RESERVE:
        return f"RESERVE({c.customer_id})"
    if op in (Operation.DEPOSIT, Operation.RETRIEVE, Operation.INVALID_ACCESS):
        return f"{op.value}(code={c.code!r})"
    if op == Operation.EXPIRE:
        return f"EXPIRE(expired={c.expired})"
    return op.value


def format_sequence(seq: Sequence[Command]) -> str:
    return " ; ".join(format_command(c) for c in seq)


@dataclass
class ExecutionRecord:
    """One executed test (fields mirror the table in assignment Task 3)."""
    test_id: str
    strategy: str
    seed: Optional[int]
    sequence: list
    initial_state: str
    outcome: str = "PASS"                      # PASS | FAIL
    steps_executed: int = 0
    failure_index: Optional[int] = None
    failure_command: Optional[str] = None
    failure_kind: Optional[str] = None
    failure_details: str = ""
    expected_result: Optional[Result] = None   # at the failing step (or last step)
    actual_result: Optional[Result] = None
    expected_final_state: Optional[Snapshot] = None
    actual_final_state: Optional[Snapshot] = None
    trace: list = field(default_factory=list)  # model TransitionKeys actually exercised
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return self.outcome == "PASS"

    def to_row(self) -> dict:
        def res(r):
            return "" if r is None else f"{'ACCEPT' if r.accepted else 'REJECT'}:{r.message}"

        def snap(s):
            return "" if s is None else "|".join(str(v) for v in oracle.snapshot_dict(s).values())

        return {
            "test_id": self.test_id,
            "strategy": self.strategy,
            "seed": self.seed,
            "length": len(self.sequence),
            "sequence": format_sequence(self.sequence),
            "initial_state": self.initial_state,
            "expected_result": res(self.expected_result),
            "actual_result": res(self.actual_result),
            "expected_final_state": snap(self.expected_final_state),
            "actual_final_state": snap(self.actual_final_state),
            "outcome": self.outcome,
            "failure_index": "" if self.failure_index is None else self.failure_index,
            "failure_kind": self.failure_kind or "",
            "failure_details": self.failure_details,
            "duration_us": round(self.duration_s * 1e6, 1),
        }


class SequenceRunner:
    """Run sequences against ``sut_factory()`` with ``model_factory()`` as oracle."""

    def __init__(self, sut_factory: Callable[[], object] = ParcelLocker,
                 model_factory: Callable[[], LockerModel] = LockerModel,
                 compare_messages: bool = True, compare_result: bool = True,
                 compare_state: bool = True, check_invariants: bool = True,
                 check_reject_purity: bool = True):
        """Oracle layers can be switched off individually (used by the oracle ablation)."""
        self.sut_factory = sut_factory
        self.model_factory = model_factory
        self.compare_messages = compare_messages
        self.compare_result = compare_result
        self.compare_state = compare_state
        self.check_invariants = check_invariants
        self.check_reject_purity = check_reject_purity

    def run(self, sequence: Sequence[Command], test_id: str = "", strategy: str = "",
            seed: Optional[int] = None) -> ExecutionRecord:
        t0 = time.perf_counter()
        model = self.model_factory()
        rec = ExecutionRecord(test_id, strategy, seed, list(sequence),
                              initial_state=model.snapshot().state.value)
        try:
            sut = self.sut_factory()
        except Exception as exc:  # noqa: BLE001 - SUT constructor failure is a test failure
            return self._fail(rec, 0, None, oracle.SUT_EXCEPTION, f"SUT init raised {exc!r}", t0)

        rec.expected_final_state = model.snapshot()
        for i, cmd in enumerate(sequence):
            try:
                before = sut.snapshot()
                actual = sut.execute(cmd)
                after = sut.snapshot()
            except Exception as exc:  # noqa: BLE001
                return self._fail(rec, i, cmd, oracle.SUT_EXCEPTION, f"SUT raised {exc!r}", t0)

            expected = model.step(cmd)
            rec.trace.append(model.last_transition)
            exp_snap = model.snapshot()
            rec.steps_executed = i + 1
            rec.expected_result, rec.actual_result = expected, actual
            rec.expected_final_state, rec.actual_final_state = exp_snap, after

            problems = oracle.compare_step(expected, actual, exp_snap, after, self.compare_messages,
                                           self.compare_result, self.compare_state)
            if self.check_invariants:
                problems += oracle.check_snapshot_invariants(after)
            if self.check_reject_purity:
                problems += oracle.check_no_mutation_on_reject(before, after, actual)
            if problems:
                kind = problems[0][0]
                details = " | ".join(f"[{k}] {d}" for k, d in problems)
                return self._fail(rec, i, cmd, kind, details, t0)

        rec.duration_s = time.perf_counter() - t0
        return rec

    @staticmethod
    def _fail(rec: ExecutionRecord, index: int, cmd: Optional[Command], kind: str,
              details: str, t0: float) -> ExecutionRecord:
        rec.outcome = "FAIL"
        rec.failure_index = index
        rec.failure_command = format_command(cmd) if cmd is not None else None
        rec.failure_kind = kind
        rec.failure_details = details
        rec.duration_s = time.perf_counter() - t0
        return rec

    def run_many(self, sequences: Sequence[Sequence[Command]], strategy: str = "",
                 seed: Optional[int] = None) -> list[ExecutionRecord]:
        prefix = f"{strategy or 'T'}-s{seed}" if seed is not None else (strategy or "T")
        return [self.run(s, f"{prefix}-{i:04d}", strategy, seed) for i, s in enumerate(sequences)]
