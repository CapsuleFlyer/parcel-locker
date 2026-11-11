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
