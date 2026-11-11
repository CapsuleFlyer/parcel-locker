# Technical Report Skeleton (assignment §8)

Pre-filled with facts from this repo's results; **rewrite the analysis in your own words** and
check every number against `results/` before submitting. Items marked TODO need your judgement.

## 1. Introduction
Objectives of the MBT assignment; one-paragraph overview of the locker case study. TODO

## 2. Requirements analysis
Requirements 1–12 → rules table in `docs/MODEL.md`; assumptions A1–A9 and why (esp. A2, A3, A8).

## 3. State-machine model
States, extended variables, guards, 35 transitions / 305 pairs, invariants I1–I4/R12,
mermaid diagram from `docs/MODEL.md`. Explain the rule-table design and why the model is independent of
the SUT.

## 4. Test-generation strategies  (algorithms are documented in `locker/generators.py` docstrings)
| | A random | B coverage-directed | C transition-pair |
|---|---|---|---|
| Selection | uniform over commands; with p=0.5 restricted to model-valid ones | uncovered transition first, else BFS toward nearest state with an uncovered transition, else rarest-first | plan paths (BFS) to uncovered adjacent pairs, chain on uncovered successors |
| Valid/invalid | mixed by `p_valid` | all transitions incl. rejections | all pairs incl. rejection self-loops |
| Length | U(1..20) | U(10..20) | fills budget (≤20), never truncates a planned pair |
| Memory across tests | none | global execution counts | global set of uncovered pairs |
| Seeds | `random.Random(seed)` per `generate` call, sets sorted before any choice → deterministic |
Advantages / limitations — TODO, use the results below. Note the strategies differ in *mean length*
(10.4 / 15.0 / 20.0), so compare per-step efficiency as well as per-test.

## 5. Test execution framework and oracle
`SequenceRunner` lock-step execution; `ExecutionRecord` fields = assignment Task 3 table (`raw_tests.csv`).
Three oracle layers (model comparison incl. full snapshot, invariants, rejection purity). How oracle
duplication was reduced (§3 + assumption A8). Exceptions in the SUT are recorded as failures.

## 6. Mutation testing
19 non-equivalent mutants + 2 equivalent (`results/mutants.csv`, categories: illegal acceptance,
missing/weak authentication, stale data, state change on rejection, wrong credential policy,
history-dependent). For each: defect, killing strategies, example killing sequence, observed
incorrect behaviour (columns in `mutants.csv`), survivors and why.
* **M16 PrefixCodeMatchOnDeposit — survives all strategies.** Needs a near-miss credential (`R-C1x`)
  that is not an input class of the default alphabet; non-equivalent (witness exists). With
  `--near-miss` it is killed by all three strategies (seed 1: random after 2 tests, pair 6, coverage 21).
* **E01/E02 — equivalent** (redundant clearing/re-assignment); excluded from the denominator and
  checked by bounded exhaustive search (depth 4) plus `tests/test_runner_metrics_mutants.py`.
* **M17–M19 were authored deliberately to probe sequence-based strategies**, after inspecting which
  pairs random testing misses (M17 targets a pair random missed in all five seeds). Say so in the
  threats-to-validity section.

## 7. Experimental setup
3 strategies × 5 seeds × 500 sequences × max length 20, 21 mutants, Python version/platform in
`experiment.json`. Metrics as defined in `docs/MODEL.md`. Timing: generation vs execution
measured separately (`gen_time_s`, `exec_time_s`, `mutation_exec_time_s`).

## 8. Results (means over 5 seeds; `results/summary_by_strategy.csv`)
| Strategy | State % | Transition % | Pair % | Mutation score | Mean tests to 1st kill | Gen s | Exec s | Unique |
|---|---|---|---|---|---|---|---|---|
| random | 100 | 100 | 86.56 ± 1.45 | 89.47 | 19.6 | 0.075 | 0.016 | 0.964 |
| coverage | 100 | 100 | 99.93 ± 0.15 | 89.47 | 20.3 | 0.298 | 0.025 | 1.000 |
| pair | 100 | 100 | 100 | 89.47 | 5.9 | 0.473 | 0.029 | 1.000 |

Charts: `results/charts/*.png` (coverage by strategy, coverage growth, mutation score, time,
mutant-detection heatmap). Insert them.

## 9. Discussion — prompts answered by the data (verify, then write up)
* *Highest state / transition coverage?* All reach 100 %; B reaches full transition coverage fastest
  (≈5 tests) — `coverage_growth.png`. Pair coverage: C 100 % > B 99.9 % > A 86.6 %.
* *Most mutants detected?* Equal score (17/19 per run), but **different** survivors: A misses M17
  (needs the pair CANCEL-reject→CANCEL-reject in OCCUPIED, which random testing rarely produces), B and C
  miss M19 (needs three complete delivery cycles; pair coverage only constrains history of length 2).
  Union over strategies 18/19.
* *Did higher coverage give a higher score?* No: 100 % transition coverage and up to 100 % pair
  coverage did not detect M19; random with the lowest pair coverage did. Coverage ≠ fault-detection;
  the fault class matters. Also the ceiling effect: 15/19 mutants die almost immediately under any strategy.
* *Efficiency?* C finds the first kill fastest (5.9 tests) but generation is ~6× slower than A
  (planning). Time per test is negligible for all (ms-scale); per *step*: compute from `total_steps`.
* *Redundancy?* A repeats 3.6 % of sequences; B and C 0 %.
* *Strengths / limitations* — TODO: A cheap, finds long-history faults by chance, poor on rare pairs;
  B fast transition coverage but greedy/no memory of history; C systematic for length-2 history, but
  fixed full-length tests and blind to length-3+ faults and to input classes outside the alphabet.

## 10. Threats to validity
* Small model (4 states) → ceiling effects; results may not generalise.
* Mutants hand-written by the author; M17–M19 designed with knowledge of generator behaviour (bias).
* Equivalence of E01/E02 argued + bounded search (depth 4), not formally proved.
* Alphabet fixed (2 customer IDs, 4–5 code classes): M16 shows alphabet gaps matter.
* Messages compared (A8). Timing noise on shared machines; sample size n = 5 seeds.
* Time-boxing via `expired` flag, no real time.

## 11. Conclusion and future work
Near-miss credentials by default, longer-history (n-wise) path coverage, mutation-guided generation,
multiple compartments. TODO

## Demonstration checklist (assignment §7.4)
`python -m locker demo` shows model execution, generation, execution, detection of an injected fault
(M03) and coverage; then show `results/` + charts.
