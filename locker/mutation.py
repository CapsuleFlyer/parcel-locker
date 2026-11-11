"""Mutation testing support: run test sets against mutants, classify survivors."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence

from .generators import DEFAULT_CUSTOMERS, candidate_commands
from .model import LockerModel
from .mutants import MUTANTS, MutantSpec
from .runner import SequenceRunner, format_sequence
from .types import Command


@dataclass
class MutantRun:
    """Outcome of one mutant against one generated test set."""
    mutant_id: str
    strategy: str
    seed: Optional[int]
    detected: bool
    kill_count: int            # number of tests in the set that exposed the mutant
    tests_to_first_kill: Optional[int]   # 1-based; None if undetected
    first_kill_test_id: str = ""
    first_kill_sequence: str = ""
    failure_kind: str = ""
    failure_details: str = ""
    exec_time_s: float = 0.0
    kill_indices: list = field(default_factory=list)   # 0-based indices of killing tests


def run_mutant_on_set(spec: MutantSpec, sequences: Sequence[Sequence[Command]],
                      strategy: str = "", seed: Optional[int] = None,
                      runner_kwargs: Optional[dict] = None, stop_at_first: bool = False) -> MutantRun:
    runner = SequenceRunner(sut_factory=spec.factory, **(runner_kwargs or {}))
    t0 = time.perf_counter()
    kills, first, kill_idx = 0, None, []
    for i, seq in enumerate(sequences):
        rec = runner.run(seq, f"{strategy}-s{seed}-{i:04d}", strategy, seed)
        if not rec.passed:
            kills += 1
            kill_idx.append(i)
            if first is None:
                first = (i, rec)
            if stop_at_first:
                break
    elapsed = time.perf_counter() - t0
    if first is None:
        return MutantRun(spec.id, strategy, seed, False, 0, None, exec_time_s=elapsed)
    i, rec = first
    return MutantRun(spec.id, strategy, seed, True, kills, i + 1, rec.test_id,
                     format_sequence(rec.sequence), rec.failure_kind or "",
                     rec.failure_details, elapsed, kill_idx)


# --------------------------------------------------------------------------- #
# Bounded exhaustive search: used to classify mutants that survive the generators
# --------------------------------------------------------------------------- #
def exhaustive_sequences(depth: int, customers=DEFAULT_CUSTOMERS,
                         near_miss: bool = False) -> Iterator[list[Command]]:
    """Every command sequence of exactly ``depth`` over the command alphabet."""
    def rec(model: LockerModel, prefix: list[Command], left: int):
        if left == 0:
            yield list(prefix)
            return
        for c in candidate_commands(model.snapshot(), customers, near_miss):
            nxt = model.clone()
            nxt.step(c)
            prefix.append(c)
            yield from rec(nxt, prefix, left - 1)
            prefix.pop()
    yield from rec(LockerModel(), [], depth)


def bounded_search(spec: MutantSpec, depth: int = 4, customers=DEFAULT_CUSTOMERS,
                   near_miss: bool = False) -> dict:
    """Look for ANY sequence (up to ``depth``) distinguishing the mutant from the model."""
    runner = SequenceRunner(sut_factory=spec.factory)
    checked = 0
    for seq in exhaustive_sequences(depth, customers, near_miss):
        checked += 1
        rec = runner.run(seq)
        if not rec.passed:
            return {"distinguishable": True, "checked": checked, "depth": depth,
                    "near_miss": near_miss, "witness": format_sequence(rec.sequence),
                    "details": rec.failure_details}
    return {"distinguishable": False, "checked": checked, "depth": depth,
            "near_miss": near_miss, "witness": "", "details": ""}
