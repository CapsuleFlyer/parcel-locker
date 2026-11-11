"""Render charts from ``results/`` (requires matplotlib; optional dependency)."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def make_charts(results_dir: str = "results") -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rd = Path(results_dir)
    out_dir = rd / "charts"
    out_dir.mkdir(exist_ok=True)
    data = json.loads((rd / "experiment.json").read_text(encoding="utf-8"))
    summary = data["summary_by_strategy"]
    strategies = [s["strategy"] for s in summary]
    colors = {"random": "#4c78a8", "coverage": "#f58518", "pair": "#54a24b"}
    written = []

    def save(fig, name):
        p = out_dir / name
        fig.tight_layout()
        fig.savefig(p, dpi=160)
        plt.close(fig)
        written.append(str(p))

    # 1. coverage by strategy
    fig, ax = plt.subplots(figsize=(7, 4))
    metrics = [("state_coverage", "State"), ("transition_coverage", "Transition"),
               ("transition_pair_coverage", "Transition-pair")]
    w = 0.25
    for i, s in enumerate(summary):
        xs = [j + (i - 1) * w for j in range(len(metrics))]
        ys = [s[f"{m}_mean"] for m, _ in metrics]
        es = [s[f"{m}_sd"] for m, _ in metrics]
        ax.bar(xs, ys, w, yerr=es, capsize=3, label=s["strategy"], color=colors.get(s["strategy"]))
    ax.set_xticks(range(len(metrics)), [n for _, n in metrics])
    ax.set_ylim(60, 101)
    ax.set_ylabel("coverage % (mean ± sd over seeds)")
    ax.set_title("Model coverage by strategy")
    ax.legend()
    save(fig, "coverage_by_strategy.png")

    # 2. coverage growth
    growth = _read_csv(rd / "coverage_growth.csv")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharex=True)
    for ax, key, title in ((axes[0], "transition_pct", "Transition coverage"),
                           (axes[1], "pair_pct", "Transition-pair coverage")):
        for strat in strategies:
            by_n: dict[int, list[float]] = {}
            for g in growth:
                if g["strategy"] == strat:
                    by_n.setdefault(int(g["tests"]), []).append(float(g[key]))
            ns = sorted(by_n)
            ax.plot(ns, [sum(by_n[n]) / len(by_n[n]) for n in ns], marker="o", ms=3,
                    label=strat, color=colors.get(strat))
        ax.set_xscale("log")
        ax.set_xlabel("number of tests executed")
        ax.set_ylabel("%")
        ax.set_title(title)
        ax.legend()
    save(fig, "coverage_growth.png")

    # 3. mutation score
    fig, ax = plt.subplots(figsize=(6, 4))
    ys = [s["mutation_score_mean"] for s in summary]
    es = [s["mutation_score_sd"] for s in summary]
    ax.bar(strategies, ys, yerr=es, capsize=4, color=[colors.get(s) for s in strategies])
    for i, y in enumerate(ys):
        ax.text(i, y + 1, f"{y:.1f}", ha="center")
    ax.set_ylim(0, 110)
    ax.set_ylabel("mutation score % (mean ± sd)")
    ax.set_title("Mutation score by strategy")
    save(fig, "mutation_score.png")

    # 4. time
    fig, ax = plt.subplots(figsize=(6, 4))
    gen = [s["gen_time_s_mean"] for s in summary]
    exe = [s["exec_time_s_mean"] for s in summary]
    ax.bar(strategies, gen, label="generation", color="#9ecae9")
    ax.bar(strategies, exe, bottom=gen, label="execution (reference SUT)", color="#3182bd")
    ax.set_ylabel("seconds per 500-test set (mean)")
    ax.set_title("Generation vs execution time")
    ax.legend()
    save(fig, "time.png")

    # 5. mutant detection heatmap
    mutants = data["mutants"]
    fig, ax = plt.subplots(figsize=(6, 0.38 * len(mutants) + 1.5))
    grid = []
    for m in mutants:
        row = []
        for s in strategies:
            k, n = m[f"{s}_seeds_detected"].split("/")
            row.append(int(k) / int(n))
        grid.append(row)
    im = ax.imshow(grid, vmin=0, vmax=1, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(strategies)), strategies)
    ax.set_yticks(range(len(mutants)), [f'{m["id"]} {m["name"]}' for m in mutants], fontsize=8)
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v:.0%}", ha="center", va="center",
                    color="white" if v > 0.6 else "black", fontsize=8)
    ax.set_title("Mutant detection rate across 5 seeds", fontsize=10)
    save(fig, "mutant_detection.png")
    return written


def make_extended_charts(results_dir: str = "results/extended") -> list[str]:
    """Charts for the extended evaluation (CI bars, equal-budget, mutant matrix, oracle ablation)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rd = Path(results_dir)
    data = json.loads((rd / "experiment_extended.json").read_text(encoding="utf-8"))
    out_dir = rd / "charts"
    out_dir.mkdir(exist_ok=True)
    summary = data["summary"]
    strategies = data["config"]["strategies"]
    colors = {"random": "#4c78a8", "coverage": "#f58518", "pair": "#54a24b",
              "scenario": "#b279a2", "random_pure": "#9d9d9d"}
    regimes = [("fixed_tests", "500 tests each"), ("equal_steps", "equal step budget"),
               ("enriched_fixed_tests", "500 tests, enriched alphabet")]
    written = []

    def save(fig, name):
        p = out_dir / name
        fig.tight_layout()
        fig.savefig(p, dpi=160)
        plt.close(fig)
        written.append(str(p))

    for metric, title, fname, lo in (("mut_all", "Mutation score (all mutants, % ± 95% CI)",
                                      "ext_mutation_score.png", 0),
                                     ("pair_cov", "Transition-pair coverage (% ± 95% CI)",
                                      "ext_pair_coverage.png", 50)):
        fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
        for ax, (reg, label) in zip(axes, regimes):
            rows = {s["strategy"]: s for s in summary if s["regime"] == reg}
            ys = [rows[s][f"{metric}_mean"] for s in strategies]
            es = [rows[s][f"{metric}_ci95"] for s in strategies]
            ax.bar(range(len(strategies)), ys, yerr=es, capsize=3,
                   color=[colors[s] for s in strategies])
            ax.set_xticks(range(len(strategies)), strategies, rotation=30, ha="right")
            ax.set_title(label, fontsize=10)
            ax.set_ylim(lo, 101)
        axes[0].set_ylabel("%")
        fig.suptitle(title)
        save(fig, fname)

    # mutant detection matrix (fixed_tests and enriched)
    matrix = data["mutant_matrix"]
    cols = [(r, s) for r in ("fixed_tests", "enriched_fixed_tests") for s in strategies]
    grid = []
    for m in matrix:
        row = []
        for r, s in cols:
            k, n = m[f"{r}:{s}"].split("/")
            row.append(int(k) / int(n))
        grid.append(row)
    fig, ax = plt.subplots(figsize=(11, 0.28 * len(matrix) + 1.8))
    ax.imshow(grid, vmin=0, vmax=1, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(cols)), [f"{'enr.' if r.startswith('enriched') else 'def.'}\n{s}"
                                     for r, s in cols], fontsize=7)
    ax.set_yticks(range(len(matrix)), [f'{m["id"]} {m["name"]}' for m in matrix], fontsize=7)
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=6,
                    color="white" if v > 0.6 else "black")
    ax.set_title("Mutant detection rate over seeds (def. = default alphabet, enr. = enriched)",
                 fontsize=9)
    save(fig, "ext_mutant_matrix.png")

    # oracle ablation
    ab = data["oracle_ablation"]
    names = list(dict.fromkeys(r["oracle"] for r in ab))
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, strat in enumerate(("random", "coverage", "pair")):
        ys = [next(r["mutation_score_mean"] for r in ab if r["oracle"] == n and r["strategy"] == strat)
              for n in names]
        ax.barh([j + (i - 1) * 0.27 for j in range(len(names))], ys, 0.27, label=strat,
                color=colors[strat])
    ax.set_yticks(range(len(names)), names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("mutation score %")
    ax.set_title("Oracle ablation: what each oracle layer contributes")
    ax.legend(fontsize=8)
    save(fig, "ext_oracle_ablation.png")
    return written
