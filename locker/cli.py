"""Command-line interface:  python -m locker <command> [options]

  demo        walk through model, generation, execution and fault detection
  strategy    generate + execute one strategy (optionally against a mutant)
  mutation    run all mutants against chosen strategies
  experiment  full Task-5 protocol -> results/ (CSV + JSON)
  extended    extended evaluation -> results/extended/ (30 seeds, CIs, held-out mutants, ...)
  change      change-request drill: edit locker/rules_config.py (or --preset/--set) and watch
              the framework react (see docs/CHANGE_REQUESTS.md)
  report      render charts from results/ (needs matplotlib; --extended for the extended set)
"""
from __future__ import annotations

import argparse
import sys

from .experiments import ExperimentConfig, run_experiment
from .generators import EXTENDED_GENERATORS, GENERATORS
from .metrics import calculate_coverage, mutation_summary
from .model import LockerModel, transition_catalogue, transition_pairs
from .mutants import MUTANTS
from .mutation import run_mutant_on_set
from .runner import SequenceRunner, format_command, format_sequence
from .types import Command, Operation as Op


def _mutant_by_name(key: str):
    from .mutants_heldout import HELDOUT_MUTANTS
    everything = tuple(MUTANTS) + tuple(HELDOUT_MUTANTS)
    for m in everything:
        if key in (m.id, m.name):
            return m
    raise SystemExit(f"unknown mutant {key!r}; choose from: " + ", ".join(m.id for m in everything))


def cmd_demo(args) -> int:
    print("== 1. Executable model: a hand-written scenario ==")
    model = LockerModel()
    script = [Command(Op.RESERVE, customer_id="C7"), Command(Op.DEPOSIT, code="WRONG"),
              Command(Op.DEPOSIT, code="R-C7"), Command(Op.DISABLE),
              Command(Op.RETRIEVE, code="P-C7"), Command(Op.DISABLE), Command(Op.ENABLE)]
    for c in script:
        r = model.step(c)
        print(f"  {format_command(c):28s} -> {'ACCEPT' if r.accepted else 'REJECT':6s} "
              f"{r.message:26s} state={model.state.value}")
    print(f"\n  model: {len(transition_catalogue())} transitions, {len(transition_pairs())} transition pairs")

    print("\n== 2. Test generation (seed 1, length<=8, 2 tests each) ==")
    for name, G in GENERATORS.items():
        for s in G(1, 8).generate(2):
            print(f"  [{name:8s}] {format_sequence(s)}")

    print("\n== 3. Execution against the reference SUT ==")
    runner = SequenceRunner()
    recs = runner.run_many(GENERATORS["pair"](1, 20).generate(50), "pair", 1)
    print(f"  50 pair-strategy tests: {sum(r.passed for r in recs)} PASS, "
          f"{sum(not r.passed for r in recs)} FAIL")

    print("\n== 4. Fault detection (injected mutant M03 RetrieveWithoutAuth) ==")
    mut = _mutant_by_name("M03")
    run = run_mutant_on_set(mut, GENERATORS["coverage"](1, 20).generate(500), "coverage", 1)
    print(f"  detected={run.detected} after {run.tests_to_first_kill} tests "
          f"({run.kill_count}/500 tests fail)")
    print(f"  test {run.first_kill_test_id}: {run.first_kill_sequence}")
    print(f"  incorrect behaviour: {run.failure_details}")

    print("\n== 5. Coverage of those 50 tests ==")
    cov = calculate_coverage(r.trace for r in recs)
    for k in ("state", "transition", "transition_pair"):
        c = cov[k]
        print(f"  {k:16s} {c['covered']}/{c['total']} = {c['percent']}%")
    return 0


def cmd_strategy(args) -> int:
    if args.preset or args.set or args.policy_sut:
        from .change import resolve_policy
        from .policy_sut import PolicySUT
        from .rules_config import use_policy
        policy, label = resolve_policy(args.preset, args.set)
        print(f"[model policy: {label}]")
        with use_policy(policy):
            return _run_strategy(args, sut_factory=(lambda: PolicySUT(policy)) if args.policy_sut else None)
    return _run_strategy(args)


def _run_strategy(args, sut_factory=None) -> int:
    gen = EXTENDED_GENERATORS[args.name](args.seed, args.max_length, near_miss=args.near_miss)
    seqs = gen.generate(args.count)
    spec = _mutant_by_name(args.mutant) if args.mutant else None
    if sut_factory is not None:
        runner = SequenceRunner(sut_factory=sut_factory)
    else:
        runner = SequenceRunner(sut_factory=spec.factory) if spec else SequenceRunner()
    recs = runner.run_many(seqs, args.name, args.seed)
    fails = [r for r in recs if not r.passed]
    target = (f"mutant {spec.id} {spec.name}" if spec else
              "PolicySUT (changed rules)" if sut_factory is not None else "reference SUT")
    print(f"strategy={args.name} seed={args.seed} tests={len(recs)} max_length={args.max_length} "
          f"target={target}")
    print(f"PASS={len(recs) - len(fails)}  FAIL={len(fails)}")
    for r in fails[:args.show_failures]:
        print(f"  {r.test_id} step {r.failure_index} {r.failure_command}: {r.failure_details}")
        print(f"      sequence: {format_sequence(r.sequence)}")
    cov = calculate_coverage(r.trace for r in recs)
    for k in ("state", "transition", "transition_pair"):
        c = cov[k]
        print(f"{k:16s} coverage: {c['covered']}/{c['total']} = {c['percent']}%")
    return 0


def cmd_mutation(args) -> int:
    print(f"{'mutant':34s} " + " ".join(f"{s:>9s}" for s in args.strategies))
    per_strategy = {s: [] for s in args.strategies}
    for m in MUTANTS:
        cells = []
        for s in args.strategies:
            seqs = GENERATORS[s](args.seed, args.max_length, near_miss=args.near_miss).generate(args.count)
            run = run_mutant_on_set(m, seqs, s, args.seed)
            per_strategy[s].append({"name": m.id, "detected": run.detected,
                                    "equivalent": m.expected_equivalent})
            cells.append(f"{run.tests_to_first_kill or '-':>9}")
        tag = " (equiv)" if m.expected_equivalent else ""
        print(f"{m.id + ' ' + m.name + tag:34s} " + " ".join(cells))
    print()
    for s in args.strategies:
        ms = mutation_summary(per_strategy[s])
        print(f"{s:9s} mutation score = {ms['mutation_score']}% "
              f"({len(ms['detected'])}/{ms['considered']})  survived: {ms['survived'] or '-'}")
    print("(cells = number of tests until first kill; '-' = survived)")
    return 0


def cmd_experiment(args) -> int:
    cfg = ExperimentConfig(sequences_per_strategy=args.count, max_length=args.max_length,
                           seeds=tuple(args.seeds), strategies=tuple(args.strategies),
                           near_miss=args.near_miss, out_dir=args.out)
    print(f"Experiment: {cfg}")
    res = run_experiment(cfg)
    print("\nstrategy   state%  trans%  pair%   mut%   gen_s   exec_s  uniq")
    for s in res["summary_by_strategy"]:
        print(f"{s['strategy']:9s} {s['state_coverage_mean']:7.2f} {s['transition_coverage_mean']:7.2f} "
              f"{s['transition_pair_coverage_mean']:6.2f} {s['mutation_score_mean']:6.2f} "
              f"{s['gen_time_s_mean']:7.3f} {s['exec_time_s_mean']:7.3f} {s['unique_ratio_mean']:5.3f}")
    print("\nmutant status:")
    for m in res["mutants"]:
        print(f"  {m['id']} {m['name']:34s} {m['status']}")
    if any(s["reference_failures"] for s in res["summary_by_strategy"]):
        print("\nWARNING: tests FAILED on the reference SUT - model/SUT disagreement!")
        return 1
    return 0


def cmd_extended(args) -> int:
    from .extended import ExtendedConfig, run_extended
    cfg = ExtendedConfig(seeds=tuple(range(1, args.seeds + 1)), count=args.count,
                         max_length=args.max_length, step_budget=args.step_budget, out_dir=args.out)
    res = run_extended(cfg)
    for regime in ("fixed_tests", "equal_steps", "enriched_fixed_tests"):
        print(f"\n[{regime}]  strategy      pair%  mut_all%  mut_core%  mut_held%  steps->1st kill")
        for s in (x for x in res["summary"] if x["regime"] == regime):
            print(f"  {s['strategy']:13s} {s['pair_cov_mean']:8.2f} {s['mut_all_mean']:9.2f} "
                  f"{s['mut_core_mean']:10.2f} {s['mut_heldout_mean']:10.2f} "
                  f"{s['steps_to_first_kill_mean']:12.1f}")
    return 0


def cmd_report(args) -> int:
    try:
        from .report import make_charts
    except ImportError:  # pragma: no cover
        raise SystemExit("matplotlib is required for charts: pip install matplotlib")
    if args.extended:
        from .report import make_extended_charts
        paths = make_extended_charts(args.out)
    else:
        paths = make_charts(args.out)
    for p in paths:
        print("wrote", p)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m locker", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, strategies=False):
        sp.add_argument("--count", type=int, default=500, help="sequences per strategy (default 500)")
        sp.add_argument("--max-length", type=int, default=20, help="max sequence length (default 20)")
        sp.add_argument("--near-miss", action="store_true",
                        help="add near-miss credentials (e.g. 'R-C1x') to the input alphabet")

    sub.add_parser("demo", help="end-to-end demonstration").set_defaults(fn=cmd_demo)

    sp = sub.add_parser("strategy", help="run a single strategy")
    sp.add_argument("--name", choices=sorted(EXTENDED_GENERATORS), required=True,
                    help="random|coverage|pair (required strategies) or scenario|random_pure (extras)")
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--mutant", help="mutant id/name to test instead of the reference SUT")
    sp.add_argument("--show-failures", type=int, default=3)
    sp.add_argument("--preset", help="use a change-request preset as the model policy (see `change --list`)")
    sp.add_argument("--set", action="append", metavar="FIELD=VALUE",
                    help="override a rules_config policy field for the model (repeatable)")
    sp.add_argument("--policy-sut", action="store_true",
                    help="execute against PolicySUT (the changed system) instead of the provided SUT")
    common(sp)
    sp.set_defaults(fn=cmd_strategy)

    sp = sub.add_parser("mutation", help="run all mutants")
    sp.add_argument("--strategies", nargs="+", choices=sorted(GENERATORS), default=sorted(GENERATORS))
    sp.add_argument("--seed", type=int, default=1)
    common(sp)
    sp.set_defaults(fn=cmd_mutation)

    sp = sub.add_parser("experiment", help="full experimental protocol")
    sp.add_argument("--strategies", nargs="+", choices=sorted(GENERATORS), default=list(GENERATORS))
    sp.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    sp.add_argument("--out", default="results")
    common(sp)
    sp.set_defaults(fn=cmd_experiment)

    sp = sub.add_parser("extended", help="extended evaluation (30 seeds, CIs, held-out mutants, ...)")
    sp.add_argument("--seeds", type=int, default=30, help="number of seeds 1..N (default 30)")
    sp.add_argument("--step-budget", type=int, default=5000, help="equal-steps regime budget")
    sp.add_argument("--out", default="results/extended")
    sp.add_argument("--count", type=int, default=500)
    sp.add_argument("--max-length", type=int, default=20)
    sp.set_defaults(fn=cmd_extended)

    from .change import cmd_change
    sp = sub.add_parser("change", help="change-request drill (edit rules_config.py, then run this)")
    sp.add_argument("--preset", help="ready-made change request; see --list")
    sp.add_argument("--set", action="append", metavar="FIELD=VALUE",
                    help="override a policy field, e.g. --set cancel_from=RESERVED,OCCUPIED (repeatable)")
    sp.add_argument("--list", action="store_true", help="list the presets")
    sp.add_argument("--all", action="store_true", help="run every preset and print one summary table")
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--count", type=int, default=500)
    sp.add_argument("--max-length", type=int, default=20)
    sp.set_defaults(fn=cmd_change)

    sp = sub.add_parser("report", help="render charts from results")
    sp.add_argument("--extended", action="store_true", help="charts for the extended evaluation")
    sp.add_argument("--out", default="results")
    sp.set_defaults(fn=cmd_report)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
