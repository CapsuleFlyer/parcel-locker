"""Change-request drill: apply a rule change to the model and watch the framework react.

    python -m locker change --list
    python -m locker change                              # the POLICY currently in rules_config.py
    python -m locker change --preset cancel_when_occupied
    python -m locker change --set cancel_from=RESERVED,OCCUPIED --set expire_requires_flag=false
    python -m locker change --all                        # every preset, one summary table

For one change the report shows: the policy diff, how the model's catalogue changed, how each
strategy fares against (a) the ORIGINAL provided SUT (expected: failures = the change is detected)
and (b) ``PolicySUT`` (expected: all pass = model and the "implemented" change agree), and how
often each strategy actually exercised the NEW transitions.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .generators import GENERATORS
from .metrics import calculate_coverage
from .model import transition_catalogue, transition_pairs
from .policy_sut import PolicySUT
from .rules_config import (BASELINE, POLICY, PRESETS, Policy, fmt_value, parse_overrides,
                           use_policy)
from .runner import SequenceRunner, format_sequence
from .sut import ParcelLocker
from .types import State


@dataclass
class StrategyOutcome:
    strategy: str
    n_tests: int
    fails_original: int
    fails_policy_sut: int
    coverage: dict
    tests_hitting_new: int
    first_failure: Optional[str]


def reachable_states(policy: Policy) -> set[State]:
    edges: dict[State, list[State]] = {s: [] for s in State}
    for t in transition_catalogue(policy):
        if t.accepted and t.src != t.dst:
            edges[t.src].append(t.dst)
    seen, queue = {State.AVAILABLE}, deque([State.AVAILABLE])
    while queue:
        for nxt in edges[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def run_change(policy: Policy, count: int = 500, max_length: int = 20, seed: int = 1,
               strategies=None) -> dict:
    """Run the drill for ``policy`` and return a result dict (printing is done by ``format_report``)."""
    strategies = list(strategies or GENERATORS)
    with use_policy(policy):
        base_cat = set(transition_catalogue(BASELINE))
        cat = transition_catalogue(policy)
        new_transitions = [t for t in cat if t not in base_cat]
        removed_transitions = [t for t in base_cat if t not in set(cat)]
        reach = reachable_states(policy)
        outcomes = []
        for name in strategies:
            seqs = GENERATORS[name](seed, max_length).generate(count)
            orig = SequenceRunner(sut_factory=ParcelLocker).run_many(seqs, name, seed)
            impl = SequenceRunner(sut_factory=lambda: PolicySUT(policy)).run_many(seqs, name, seed)
            fails_o = [r for r in orig if not r.passed]
            fails_i = [r for r in impl if not r.passed]
            new_set = set(new_transitions)
            hitting = sum(1 for r in impl if new_set.intersection(r.trace))
            first = None
            if fails_o:
                f = min(fails_o, key=lambda r: (r.failure_index, r.test_id))
                prefix = format_sequence(f.sequence[:f.failure_index + 1])
                first = (f"{f.test_id}: {prefix}\n        -> {f.failure_details}")
            elif fails_i:
                f = fails_i[0]
                first = f"[PolicySUT FAILED] {f.test_id}: {format_sequence(f.sequence[:f.failure_index + 1])}"
            outcomes.append(StrategyOutcome(
                name, len(seqs), len(fails_o), len(fails_i),
                calculate_coverage(r.trace for r in impl), hitting, first))
        return {
            "policy": policy,
            "diff": policy.diff(BASELINE),
            "n_transitions": (len(base_cat), len(cat)),
            "n_pairs": (len(transition_pairs(BASELINE)), len(transition_pairs(policy))),
            "new_transitions": new_transitions,
            "removed_transitions": removed_transitions,
            "unreachable_states": sorted(s.value for s in set(State) - reach),
            "outcomes": outcomes,
            "model_matches_policy_sut": all(o.fails_policy_sut == 0 for o in outcomes),
            "original_sut_flagged": all(o.fails_original > 0 for o in outcomes),
        }


def format_report(label: str, res: dict) -> str:
    out = [f"=== Change request: {label} ===", "", "Policy changes vs the requirements baseline:"]
    if not res["diff"]:
        out.append("  (none - this is the baseline behaviour)")
    for k, (new, old) in res["diff"].items():
        out.append(f"  {k}: {fmt_value(old)} -> {fmt_value(new)}")
    (t0, t1), (p0, p1) = res["n_transitions"], res["n_pairs"]
    out += ["", f"Model size: transitions {t0} -> {t1}, transition pairs {p0} -> {p1}"]
    for t in res["new_transitions"]:
        out.append(f"  + {t.label()}")
    for t in res["removed_transitions"]:
        out.append(f"  - {t.label()}")
    if res["unreachable_states"]:
        out.append(f"  WARNING: states unreachable under this policy: {', '.join(res['unreachable_states'])}"
                   " (coverage denominators include their transitions)")
    out += ["", "strategy   tests | orig. SUT fails | PolicySUT fails | state%  trans%  pair% | "
                "tests hitting new transitions",
            "-" * 108]
    for o in res["outcomes"]:
        c = o.coverage
        out.append(f"{o.strategy:9s} {o.n_tests:6d} | {o.fails_original:15d} | {o.fails_policy_sut:15d} | "
                   f"{c['state']['percent']:6.1f} {c['transition']['percent']:7.1f} "
                   f"{c['transition_pair']['percent']:6.1f} | {o.tests_hitting_new:5d}"
                   f" ({100 * o.tests_hitting_new / o.n_tests:.0f}%)")
    shown = next((o for o in res["outcomes"] if o.first_failure), None)
    if shown:
        out += ["", f"First discrepancy vs the ORIGINAL SUT ({shown.strategy}):", "    " + shown.first_failure]
    out.append("")
    if not res["diff"]:
        verdict = "Baseline: every strategy passes on the reference SUT, as in the main results."
    elif not res["model_matches_policy_sut"]:
        verdict = ("PROBLEM: the model and PolicySUT disagree - the model rules, the oracle, or "
                   "PolicySUT is inconsistent with this change.")
    elif res["original_sut_flagged"]:
        verdict = ("OK: model and PolicySUT agree on all tests; the unchanged SUT is flagged by "
                   "every strategy (the change request is detected).")
    else:
        flagged = [o.strategy for o in res["outcomes"] if o.fails_original]
        verdict = ("OK: model and PolicySUT agree. The unchanged SUT is flagged by: "
                   f"{', '.join(flagged) or 'no strategy'} (a strategy that never exercises the new "
                   "behaviour cannot see the change).")
    out.append(verdict)
    return "\n".join(out)


def resolve_policy(preset: Optional[str], assignments: Optional[list[str]]) -> tuple[Policy, str]:
    """Pick the policy a CLI run should use: preset | current POLICY, plus --set overrides."""
    if preset:
        if preset not in PRESETS:
            raise SystemExit(f"unknown preset {preset!r}; choose from: {', '.join(PRESETS)}")
        desc, base = PRESETS[preset]
        label = f"{preset} - {desc}"
    else:
        base, label = POLICY, "current POLICY in locker/rules_config.py"
    if assignments:
        try:
            base = parse_overrides(base, assignments)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}")
        label += "  [+ " + ", ".join(assignments) + "]"
    return base, label


def cmd_change(args) -> int:
    if args.list:
        w = max(len(n) for n in PRESETS)
        for name, (desc, pol) in PRESETS.items():
            print(f"  {name:{w}s}  {desc}")
        return 0
    if args.all:
        print(f"{'preset':26s} {'trans':>5s} {'pairs':>5s} {'orig SUT fails (A/B/C)':>24s} "
              f"{'PolicySUT fails':>16s}  verdict")
        bad = 0
        for name, (_, pol) in PRESETS.items():
            res = run_change(pol, args.count, args.max_length, args.seed)
            fo = "/".join(str(o.fails_original) for o in res["outcomes"])
            fi = "/".join(str(o.fails_policy_sut) for o in res["outcomes"])
            ok = res["model_matches_policy_sut"] and any(o.fails_original for o in res["outcomes"])
            bad += not ok
            print(f"{name:26s} {res['n_transitions'][1]:5d} {res['n_pairs'][1]:5d} {fo:>24s} {fi:>16s}  "
                  f"{'ok' if ok else 'PROBLEM'}")
        return 1 if bad else 0
    policy, label = resolve_policy(args.preset, args.set)
    res = run_change(policy, args.count, args.max_length, args.seed)
    print(format_report(label, res))
    return 0 if res["model_matches_policy_sut"] else 1
