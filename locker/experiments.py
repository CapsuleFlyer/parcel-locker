"""Experiment runner implementing the Task 5 protocol.

Defaults follow the assignment's minimum protocol: 3 strategies x 500 sequences x
max length 20 x 5 seeds, >= 8 mutants, with state / transition / transition-pair
coverage, mutation score and execution times reported. Everything is written to
machine-readable files in ``out_dir``.
"""
from __future__ import annotations

import csv
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from .generators import GENERATORS
from .metrics import calculate_coverage, mutation_summary, redundancy_report
from .mutants import MUTANTS, MutantSpec
from .mutation import bounded_search, run_mutant_on_set
from .runner import SequenceRunner, format_sequence
from .types import Command


@dataclass
class ExperimentConfig:
    sequences_per_strategy: int = 500
    max_length: int = 20
    seeds: tuple = (1, 2, 3, 4, 5)
    strategies: tuple = ("random", "coverage", "pair")
    near_miss: bool = False          # add near-miss credential inputs to the alphabet
    search_depth: int = 4            # bounded exhaustive search depth for survivors
    out_dir: str = "results"
    growth_checkpoints: tuple = (1, 2, 5, 10, 20, 50, 100, 200, 350, 500)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _mean_sd(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def _run_one_set(strategy: str, seed: int, cfg: ExperimentConfig,
                 mutants: tuple[MutantSpec, ...]) -> dict:
    gen = GENERATORS[strategy](seed, cfg.max_length, near_miss=cfg.near_miss)

    t0 = time.perf_counter()
    sequences: list[list[Command]] = gen.generate(cfg.sequences_per_strategy)
    gen_time = time.perf_counter() - t0

    runner = SequenceRunner()
    t0 = time.perf_counter()
    records = runner.run_many(sequences, strategy, seed)
    exec_time = time.perf_counter() - t0

    traces = [r.trace for r in records]
    coverage = calculate_coverage(traces)
    growth = []
    for n in cfg.growth_checkpoints:
        if n <= len(traces):
            c = calculate_coverage(traces[:n])
            growth.append({"strategy": strategy, "seed": seed, "tests": n,
                           "state_pct": c["state"]["percent"],
                           "transition_pct": c["transition"]["percent"],
                           "pair_pct": c["transition_pair"]["percent"]})

    t0 = time.perf_counter()
    mutant_runs = [run_mutant_on_set(m, sequences, strategy, seed) for m in mutants]
    mutation_time = time.perf_counter() - t0
    equiv = {m.id: m.expected_equivalent for m in mutants}
    msum = mutation_summary({"name": r.mutant_id, "detected": r.detected,
                             "equivalent": equiv[r.mutant_id]} for r in mutant_runs)
    detected_ttk = [r.tests_to_first_kill for r in mutant_runs
                    if r.detected and not equiv[r.mutant_id]]

    return {
        "strategy": strategy, "seed": seed,
        "sequences": len(sequences),
        "mean_length": round(statistics.mean(len(s) for s in sequences), 3),
        "total_steps": sum(len(s) for s in sequences),
        "reference_failures": sum(1 for r in records if not r.passed),
        "state_coverage": coverage["state"]["percent"],
        "transition_coverage": coverage["transition"]["percent"],
        "transition_pair_coverage": coverage["transition_pair"]["percent"],
        "transitions_covered": f'{coverage["transition"]["covered"]}/{coverage["transition"]["total"]}',
        "pairs_covered": f'{coverage["transition_pair"]["covered"]}/{coverage["transition_pair"]["total"]}',
        "missed_transitions": coverage["missed_transitions"],
        "mutation_score": msum["mutation_score"],
        "mutants_detected": len(msum["detected"]),
        "mutants_considered": msum["considered"],
        "mutants_survived": msum["survived"],
        "mean_tests_to_first_kill": round(statistics.mean(detected_ttk), 2) if detected_ttk else None,
        "unique_ratio": redundancy_report([[format_sequence([c]) for c in s] for s in sequences])["unique_ratio"],
        "duplicates": redundancy_report([[format_sequence([c]) for c in s] for s in sequences])["duplicates"],
        "gen_time_s": round(gen_time, 4),
        "exec_time_s": round(exec_time, 4),
        "mutation_exec_time_s": round(mutation_time, 4),
        "_records": records, "_mutant_runs": mutant_runs, "_growth": growth,
    }


METRICS = ["state_coverage", "transition_coverage", "transition_pair_coverage",
           "mutation_score", "mean_tests_to_first_kill", "unique_ratio", "mean_length",
           "total_steps", "gen_time_s", "exec_time_s", "mutation_exec_time_s"]


def run_experiment(cfg: ExperimentConfig = ExperimentConfig(),
                   mutants: tuple[MutantSpec, ...] = MUTANTS,
                   log: Callable[[str], None] = print) -> dict:
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    by_id = {m.id: m for m in mutants}

    sets = []
    for strategy in cfg.strategies:
        for seed in cfg.seeds:
            log(f"  running {strategy:9s} seed={seed} ...")
            sets.append(_run_one_set(strategy, seed, cfg, mutants))

    # ---- per-run summary + per-strategy aggregates --------------------------
    per_run = [{k: v for k, v in s.items() if not k.startswith("_") and k not in
                ("missed_transitions", "mutants_survived")} for s in sets]
    per_strategy = []
    for strategy in cfg.strategies:
        rows = [s for s in sets if s["strategy"] == strategy]
        agg = {"strategy": strategy, "runs": len(rows)}
        for m in METRICS:
            vals = [r[m] for r in rows if r[m] is not None]
            mean, sd = _mean_sd(vals)
            agg[f"{m}_mean"], agg[f"{m}_sd"] = round(mean, 4), round(sd, 4)
        agg["reference_failures"] = sum(r["reference_failures"] for r in rows)
        per_strategy.append(agg)

    # ---- raw test results (reference SUT) -----------------------------------
    raw_rows = [rec.to_row() for s in sets for rec in s["_records"]]

    # ---- mutant x strategy x seed ------------------------------------------
    mutant_run_rows = []
    for s in sets:
        for r in s["_mutant_runs"]:
            d = asdict(r)
            d["exec_time_s"] = round(d["exec_time_s"], 5)
            d["equivalent_expected"] = by_id[r.mutant_id].expected_equivalent
            mutant_run_rows.append(d)

    # ---- mutant catalogue with final classification ---------------------------
    mutant_rows = []
    for m in mutants:
        runs = [r for r in mutant_run_rows if r["mutant_id"] == m.id]
        row = {"id": m.id, "name": m.name, "category": m.category,
               "description": m.description, "expected_equivalent": m.expected_equivalent}
        for strategy in cfg.strategies:
            sr = [r for r in runs if r["strategy"] == strategy]
            row[f"{strategy}_seeds_detected"] = f'{sum(r["detected"] for r in sr)}/{len(sr)}'
            ttk = [r["tests_to_first_kill"] for r in sr if r["detected"]]
            row[f"{strategy}_mean_tests_to_first_kill"] = round(statistics.mean(ttk), 2) if ttk else ""
        detected_any = any(r["detected"] for r in runs)
        row["detected_by_any"] = detected_any
        first = next((r for r in runs if r["detected"]), None)
        row["example_killing_sequence"] = first["first_kill_sequence"] if first else ""
        row["observed_incorrect_behaviour"] = first["failure_details"] if first else ""

        search = None
        witness_failed = None
        if m.witness:
            witness_failed = not SequenceRunner(sut_factory=m.factory).run(m.witness).passed
        if m.expected_equivalent or (not detected_any and not m.witness):
            log(f"  bounded exhaustive search (depth {cfg.search_depth}) for {m.id} ...")
            search = bounded_search(m, cfg.search_depth, near_miss=cfg.near_miss)
        if m.expected_equivalent:
            status = ("equivalent-claim REFUTED" if detected_any or search["distinguishable"]
                      else "equivalent (excluded from score)")
        elif detected_any:
            killers = [st for st in cfg.strategies
                       if not row[f"{st}_seeds_detected"].startswith("0/")]
            status = ("killed (all strategies)" if len(killers) == len(cfg.strategies)
                      else "killed by: " + ", ".join(killers) + " only")
        elif witness_failed:
            status = "survived: non-equivalent (witness exists) - generator gap"
        elif search and search["distinguishable"]:
            status = "survived: killable, generator gap"
        else:
            status = (f"survived: no divergence within depth {cfg.search_depth} "
                      "(possibly equivalent - needs manual analysis)")
        row["witness"] = format_sequence(m.witness) if m.witness else ""
        row["witness_fails_mutant"] = "" if witness_failed is None else witness_failed
        row["status"] = status
        row["bounded_search"] = json.dumps(search) if search else ""
        row["note"] = m.note
        mutant_rows.append(row)

    # ---- overall (union) mutation scores --------------------------------------
    def union_score(strategy: Optional[str]) -> dict:
        items = []
        for m in mutants:
            rs = [r for r in mutant_run_rows if r["mutant_id"] == m.id
                  and (strategy is None or r["strategy"] == strategy)]
            items.append({"name": m.id, "detected": any(r["detected"] for r in rs),
                          "equivalent": m.expected_equivalent})
        return mutation_summary(items)

    union = {"all_strategies": union_score(None)}
    for strategy in cfg.strategies:
        union[strategy] = union_score(strategy)

    growth_rows = [g for s in sets for g in s["_growth"]]
    result = {
        "config": asdict(cfg),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "summary_by_strategy": per_strategy,
        "union_mutation": union,
        "per_run": per_run,
        "missed_transitions": {f'{s["strategy"]}-seed{s["seed"]}': s["missed_transitions"]
                               for s in sets if s["missed_transitions"]},
        "mutants": mutant_rows,
    }

    _write_csv(out / "raw_tests.csv", raw_rows)
    _write_csv(out / "summary_per_run.csv", per_run)
    _write_csv(out / "summary_by_strategy.csv", per_strategy)
    _write_csv(out / "mutant_runs.csv", mutant_run_rows)
    _write_csv(out / "mutants.csv", mutant_rows)
    _write_csv(out / "coverage_growth.csv", growth_rows)
    (out / "experiment.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    log(f"  wrote results to {out}/")
    return result
