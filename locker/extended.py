"""Extended evaluation (goes BEYOND the minimum Task-5 protocol; additive only).

The required protocol (3 strategies x 5 seeds x 500 tests, ``experiments.py``) is unchanged.
This module adds, each addressing a known limitation of the minimum protocol:

1. 30 seeds with 95 % confidence intervals and paired sign-flip permutation tests.
2. An *equal step budget* regime (fair comparison: strategies generate tests of different length).
3. Two supplementary strategies: ``scenario`` (usage-profile) and ``random_pure`` (ablation of A).
4. A held-out mutant set written independently of the generators (``mutants_heldout.py``),
   plus two non-trivial equivalent mutants.
5. Oracle ablation: mutation score when oracle layers are removed.
6. Model mutation: deliberately wrong models must be exposed against the reference SUT.
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Optional

from .generators import EXTENDED_GENERATORS, GENERATORS
from .metrics import calculate_coverage, mutation_summary
from .model_mutants import MODEL_MUTANTS
from .mutants import MUTANTS
from .mutation import run_mutant_on_set
from .runner import SequenceRunner, format_sequence

try:  # held-out mutants are written independently; tolerate absence
    from .mutants_heldout import HELDOUT_MUTANTS
except ImportError:  # pragma: no cover
    HELDOUT_MUTANTS = ()

CORE_IDS = {m.id for m in MUTANTS}
ALL_MUTANTS = tuple(MUTANTS) + tuple(HELDOUT_MUTANTS)

_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
        10: 2.228, 14: 2.145, 19: 2.093, 24: 2.064, 29: 2.045, 39: 2.023}


@dataclass
class ExtendedConfig:
    seeds: tuple = tuple(range(1, 31))
    count: int = 500
    max_length: int = 20
    step_budget: int = 5000
    strategies: tuple = ("random", "coverage", "pair", "scenario", "random_pure")
    ablation_seeds: tuple = (1, 2, 3, 4, 5)
    model_mutant_tests: int = 300
    out_dir: str = "results/extended"
    permutations: int = 20000


def t_crit(n: int) -> float:
    """Two-sided 95 % t critical value for n samples (conservative table lookup)."""
    df = max(1, n - 1)
    keys = [k for k in _T95 if k <= df]
    return _T95[max(keys)] if keys else 12.706


def mean_sd_ci(values: list[float]) -> tuple[float, float, float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0, 0.0, 0.0
    m = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    ci = t_crit(len(vals)) * sd / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
    return m, sd, ci


def paired_permutation_p(diffs: list[float], rounds: int, seed: int = 12345) -> float:
    """Two-sided sign-flip permutation test on paired differences (Monte-Carlo, fixed seed)."""
    if not diffs or all(d == 0 for d in diffs):
        return 1.0
    rng = random.Random(seed)
    observed = abs(sum(diffs))
    hits = 0
    for _ in range(rounds):
        if abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (rounds + 1)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if rows:
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


# --------------------------------------------------------------------------- #
# 1-4: seeds / regimes / strategies / held-out mutants
# --------------------------------------------------------------------------- #
def _regime_metrics(sequences, traces, mutant_runs, k: int) -> dict:
    cov = calculate_coverage(traces[:k])
    lens = [len(s) for s in sequences[:k]]
    flags = {m.id: m.expected_equivalent for m in ALL_MUTANTS}

    def score(ids) -> float:
        items = [{"name": r.mutant_id, "detected": any(i < k for i in r.kill_indices),
                  "equivalent": flags[r.mutant_id]} for r in mutant_runs if r.mutant_id in ids]
        return mutation_summary(items)["mutation_score"] if items else 0.0

    all_ids = {m.id for m in ALL_MUTANTS}
    held_ids = all_ids - CORE_IDS
    steps_first = []
    detected = {}
    for r in mutant_runs:
        idx = [i for i in r.kill_indices if i < k]
        detected[r.mutant_id] = bool(idx)
        if idx and not flags[r.mutant_id]:
            steps_first.append(sum(lens[: idx[0] + 1]))
    return {
        "tests": k, "steps": sum(lens),
        "state_cov": cov["state"]["percent"],
        "transition_cov": cov["transition"]["percent"],
        "pair_cov": cov["transition_pair"]["percent"],
        "mut_all": score(all_ids), "mut_core": score(CORE_IDS), "mut_heldout": score(held_ids),
        "steps_to_first_kill": statistics.mean(steps_first) if steps_first else None,
        "_detected": detected,
    }


ENRICHED = dict(near_miss=True, customers=("C1", "C2", "c1"))
REGIMES = ("fixed_tests", "equal_steps", "enriched_fixed_tests")


def _collect(cfg: ExtendedConfig, log, enriched: bool = False) -> list[dict]:
    out = []
    ref = SequenceRunner()
    for strategy in cfg.strategies:
        for seed in cfg.seeds:
            gen = EXTENDED_GENERATORS[strategy](seed, cfg.max_length, **(ENRICHED if enriched else {}))
            t0 = time.perf_counter()
            seqs = gen.generate(cfg.count)
            gen_t = time.perf_counter() - t0
            recs = ref.run_many(seqs, strategy, seed)
            assert all(r.passed for r in recs), f"reference SUT failed under {strategy}/{seed}"
            traces = [r.trace for r in recs]
            runs = [run_mutant_on_set(m, seqs, strategy, seed) for m in ALL_MUTANTS]
            cum, k_budget = 0, 0
            for s in seqs:
                if cum + len(s) > cfg.step_budget:
                    break
                cum += len(s)
                k_budget += 1
            k_budget = max(1, k_budget)
            regimes = ((("enriched_fixed_tests", len(seqs)),) if enriched
                       else (("fixed_tests", len(seqs)), ("equal_steps", k_budget)))
            for regime, k in regimes:
                row = {"regime": regime, "strategy": strategy, "seed": seed,
                       "gen_time_s": round(gen_t, 4)}
                row.update(_regime_metrics(seqs, traces, runs, k))
                out.append(row)
        log(f"  collected {strategy} ({len(cfg.seeds)} seeds, "
            f"{'enriched' if enriched else 'default'} alphabet)")
    return out


METRICS = ["state_cov", "transition_cov", "pair_cov", "mut_core", "mut_heldout", "mut_all",
           "steps_to_first_kill", "tests", "steps"]
COMPARED = ["pair_cov", "mut_core", "mut_heldout", "mut_all", "steps_to_first_kill"]


def _summaries(rows: list[dict], cfg: ExtendedConfig):
    summary, comps = [], []
    for regime in REGIMES:
        for strategy in cfg.strategies:
            rs = [r for r in rows if r["regime"] == regime and r["strategy"] == strategy]
            d = {"regime": regime, "strategy": strategy, "n_seeds": len(rs)}
            for m in METRICS:
                mean, sd, ci = mean_sd_ci([r[m] for r in rs])
                d[f"{m}_mean"], d[f"{m}_sd"], d[f"{m}_ci95"] = round(mean, 3), round(sd, 3), round(ci, 3)
            summary.append(d)
        pairs = list(combinations(cfg.strategies, 2))
        for a, b in pairs:
            for m in COMPARED:
                da = {r["seed"]: r[m] for r in rows if r["regime"] == regime and r["strategy"] == a}
                db = {r["seed"]: r[m] for r in rows if r["regime"] == regime and r["strategy"] == b}
                diffs = [da[s] - db[s] for s in da if da[s] is not None and db.get(s) is not None]
                p = paired_permutation_p(diffs, cfg.permutations)
                mean, sd, ci = mean_sd_ci(diffs)
                comps.append({"regime": regime, "metric": m, "a": a, "b": b,
                              "mean_diff_a_minus_b": round(mean, 3), "ci95": round(ci, 3),
                              "p_raw": round(p, 5),
                              "p_bonferroni": round(min(1.0, p * len(pairs) * len(COMPARED)), 5)})
    return summary, comps


def _mutant_matrix(rows: list[dict], cfg: ExtendedConfig) -> list[dict]:
    out = []
    for m in ALL_MUTANTS:
        row = {"id": m.id, "name": m.name, "source": "core" if m.id in CORE_IDS else "held-out",
               "category": m.category, "expected_equivalent": m.expected_equivalent}
        for regime in REGIMES:
            for strategy in cfg.strategies:
                rs = [r for r in rows if r["regime"] == regime and r["strategy"] == strategy]
                hits = sum(1 for r in rs if r["_detected"].get(m.id))
                row[f"{regime}:{strategy}"] = f"{hits}/{len(rs)}"
        out.append(row)
    return out


# --------------------------------------------------------------------------- #
# 5: oracle ablation
# --------------------------------------------------------------------------- #
ORACLES = {
    "O0 accepted-flag only": dict(compare_messages=False, compare_state=False,
                                  check_invariants=False, check_reject_purity=False),
    "O1 + message text": dict(compare_messages=True, compare_state=False,
                              check_invariants=False, check_reject_purity=False),
    "O2 + full snapshot vs model": dict(compare_messages=True, compare_state=True,
                                        check_invariants=False, check_reject_purity=False),
    "O3 full (model + invariants + purity)": dict(),
    "O4 invariants + purity only (no model)": dict(compare_result=False, compare_state=False,
                                                    check_invariants=True, check_reject_purity=True),
}


def oracle_ablation(cfg: ExtendedConfig, log) -> list[dict]:
    real = [m for m in ALL_MUTANTS if not m.expected_equivalent]
    rows = []
    sets = {}
    for strategy in ("random", "coverage", "pair"):
        for seed in cfg.ablation_seeds:
            sets[(strategy, seed)] = GENERATORS[strategy](seed, cfg.max_length).generate(cfg.count)
    for name, kw in ORACLES.items():
        per_strategy = {}
        missed_everywhere = None
        for (strategy, seed), seqs in sets.items():
            det = {m.id: run_mutant_on_set(m, seqs, strategy, seed, kw, stop_at_first=True).detected
                   for m in real}
            per_strategy.setdefault(strategy, []).append(100.0 * sum(det.values()) / len(real))
            missed = {i for i, v in det.items() if not v}
            missed_everywhere = missed if missed_everywhere is None else missed_everywhere & missed
        for strategy, vals in per_strategy.items():
            mean, sd, _ = mean_sd_ci(vals)
            rows.append({"oracle": name, "strategy": strategy, "mutation_score_mean": round(mean, 2),
                         "mutation_score_sd": round(sd, 2),
                         "never_detected_by_any_strategy": " ".join(sorted(missed_everywhere))})
        log(f"  oracle {name}")
    return rows


# --------------------------------------------------------------------------- #
# 6: model mutation
# --------------------------------------------------------------------------- #
def model_mutation(cfg: ExtendedConfig) -> list[dict]:
    rows = []
    for name, cls in MODEL_MUTANTS.items():
        row = {"model_mutant": name}
        for strategy in ("random", "coverage", "pair"):
            seqs = GENERATORS[strategy](1, cfg.max_length).generate(cfg.model_mutant_tests)
            runner = SequenceRunner(model_factory=cls)
            first = next(((i, r) for i, r in enumerate(runner.run_many(seqs, strategy, 1))
                          if not r.passed), None)
            row[f"{strategy}_tests_to_detect"] = first[0] + 1 if first else ""
            if first and "example_failing_sequence" not in row:
                row["example_failing_sequence"] = format_sequence(first[1].sequence)
                row["observed_disagreement"] = first[1].failure_details
        row["detected"] = any(row[f"{s}_tests_to_detect"] != "" for s in ("random", "coverage", "pair"))
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
def run_extended(cfg: ExtendedConfig = ExtendedConfig(), log=print) -> dict:
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log(f"Extended evaluation: {len(cfg.seeds)} seeds, {len(cfg.strategies)} strategies, "
        f"{len(ALL_MUTANTS)} mutants ({len(HELDOUT_MUTANTS)} held-out)")
    rows = _collect(cfg, log) + _collect(cfg, log, enriched=True)
    summary, comps = _summaries(rows, cfg)
    matrix = _mutant_matrix(rows, cfg)
    ablation = oracle_ablation(cfg, log)
    model_mut = model_mutation(cfg)

    per_run = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    _write_csv(out / "per_run.csv", per_run)
    _write_csv(out / "summary.csv", summary)
    _write_csv(out / "comparisons.csv", comps)
    _write_csv(out / "mutant_matrix.csv", matrix)
    _write_csv(out / "oracle_ablation.csv", ablation)
    _write_csv(out / "model_mutants.csv", model_mut)
    result = {"config": asdict(cfg), "summary": summary, "comparisons": comps,
              "mutant_matrix": matrix, "oracle_ablation": ablation, "model_mutants": model_mut}
    (out / "experiment_extended.json").write_text(json.dumps(result, indent=2, default=str),
                                                  encoding="utf-8")
    log(f"  wrote {out}/")
    return result
