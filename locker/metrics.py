"""Coverage and mutation metrics with explicit numerators and denominators.

Definitions (also documented in docs/MODEL.md and the report):

* A *trace* is the list of model ``TransitionKey`` s exercised by one test.
* State coverage      = |states visited| / |model states|. The initial state
  (AVAILABLE) counts as visited because every test starts there.
* Transition coverage = |distinct transitions exercised| / |catalogue|, where the
  catalogue is every (src, op, outcome, dst) the model can produce - including
  rejections, which are self-loops.
* Transition-pair coverage = |distinct adjacent pairs (t_i, t_i+1) exercised| /
  |defined pairs|, where a pair (t1, t2) is defined iff t1.dst == t2.src.
* Mutation score = detected / (all mutants - equivalent mutants).
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from .model import TransitionKey, transition_catalogue, transition_pairs
from .types import State


def _ratio(covered: int, total: int) -> dict:
    return {"covered": covered, "total": total,
            "percent": round(100.0 * covered / total, 2) if total else 0.0}


def calculate_coverage(executed_traces: Iterable[Sequence[TransitionKey]],
                       initial_state: State = State.AVAILABLE) -> dict:
    catalogue = set(transition_catalogue())
    pairs = set(transition_pairs())

    states = {initial_state}
    transitions: set[TransitionKey] = set()
    seen_pairs: set[tuple[TransitionKey, TransitionKey]] = set()

    for trace in executed_traces:
        prev: Optional[TransitionKey] = None
        for t in trace:
            states.add(t.src)
            states.add(t.dst)
            transitions.add(t)
            if prev is not None:
                seen_pairs.add((prev, t))
            prev = t

    return {
        "state": _ratio(len(states), len(State)),
        "transition": _ratio(len(transitions & catalogue), len(catalogue)),
        "transition_pair": _ratio(len(seen_pairs & pairs), len(pairs)),
        "missed_transitions": sorted(t.label() for t in catalogue - transitions),
        "missed_pairs": len(pairs - seen_pairs),
    }


def redundancy_report(sequences: Sequence[Sequence]) -> dict:
    """Duplicate test sequences (exact repeats)."""
    keys = [tuple(sequences_item) for sequences_item in sequences]
    unique = len(set(keys))
    return {"total": len(keys), "unique": unique, "duplicates": len(keys) - unique,
            "unique_ratio": round(unique / len(keys), 4) if keys else 0.0}


def mutation_summary(mutant_results: Iterable[dict]) -> dict:
    """Summarise mutant outcomes.

    Each item: ``{"name": str, "detected": bool, "equivalent": bool}``.
    Equivalent mutants are excluded from the score denominator and listed apart.
    """
    items = list(mutant_results)
    equivalent = [m["name"] for m in items if m.get("equivalent")]
    considered = [m for m in items if not m.get("equivalent")]
    detected = [m["name"] for m in considered if m["detected"]]
    survived = [m["name"] for m in considered if not m["detected"]]
    score = round(100.0 * len(detected) / len(considered), 2) if considered else 0.0
    return {
        "total_mutants": len(items),
        "equivalent": equivalent,
        "considered": len(considered),
        "detected": detected,
        "survived": survived,
        "mutation_score": score,
    }
