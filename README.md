# Smart Parcel Locker — Model-Based Testing Framework

State-machine-based test generation, automated execution, mutation testing and
experimental evaluation for a smart parcel locker compartment (Python 3.10+,
**standard library only**; `matplotlib` is optional, for charts).

```
requirements ──► executable model ──► generators (A/B/C) ──► runner + oracle ──► SUT / mutants
 (data/)           locker/model.py     locker/generators.py    locker/runner.py     locker/sut.py
                                                               locker/oracle.py     locker/mutants.py
                                       metrics + experiments ──► results/ (CSV, JSON, charts)
```

## Quick start

```bash
python -m unittest discover -s tests -v     # 75 tests: model, generators, runner, oracle, metrics, mutants, extensions, change requests
python -m locker demo                       # 1-minute end-to-end walkthrough
python -m locker experiment                 # full Task-5 protocol -> results/   (~15 s)
python -m locker report                     # charts -> results/charts/          (needs matplotlib)
python -m locker extended                   # extended evaluation -> results/extended/ (~6 min)
python -m locker change --list              # change-request drill: ready-made rule changes (see below)
python -m locker report --extended --out results/extended
```

No installation is needed; run everything from the repository root.
`pip install -r requirements.txt` only adds matplotlib for `report`.

### Run one strategy

```bash
python -m locker strategy --name random   --seed 1                 # Strategy A
python -m locker strategy --name coverage --seed 1                 # Strategy B
python -m locker strategy --name pair     --seed 1                 # Strategy C
python -m locker strategy --name pair --seed 1 --mutant M17        # test a faulty version
python -m locker strategy --name random --count 100 --max-length 12 --seed 7
```

### Run mutation experiments

```bash
python -m locker mutation                       # every mutant x every strategy (seed 1)
python -m locker mutation --near-miss           # richer input alphabet (kills M16)
python -m locker experiment --out results       # 3 strategies x 5 seeds x 500 tests, max length 20
```

### Reproduce the reported results

`python -m locker experiment` uses seeds 1–5, 500 sequences per strategy, max length 20 and
regenerates every file in `results/`. Generation is deterministic (checked in tests, also across
`PYTHONHASHSEED` values); only the wall-clock timing columns vary between machines.

## Repository layout

| Path | Purpose |
|---|---|
| `locker/types.py`, `locker/sut.py` | **Provided** types and reference SUT (unchanged) |
| `locker/rules_config.py` | **The one file to edit for a rule change**: tweakable policy fields, 10 presets, active-policy switch |
| `locker/model.py` | Independent executable state machine (declarative rule table built from the policy), transition & pair catalogues |
| `locker/policy_sut.py`, `locker/change.py` | `PolicySUT` (the system after a change) and the `python -m locker change` drill |
| `locker/oracle.py` | Result/snapshot comparison, state invariants, rejection-purity checks |
| `locker/runner.py` | `SequenceRunner`: lock-step execution, per-test `ExecutionRecord` |
| `locker/generators.py` | Strategy A random, B coverage-directed, C transition-pair |
| `locker/metrics.py` | State / transition / transition-pair coverage, redundancy, mutation score |
| `locker/mutants.py` | 19 non-equivalent + 4 equivalent mutants (subclasses of the SUT) |
| `locker/mutants_heldout.py` | 12 held-out mutants (10 real, 2 equivalent) written independently of the generators |
| `locker/model_mutants.py` | 6 deliberately wrong models, used to validate the framework from the other side |
| `locker/extended.py` | Extended evaluation: 30 seeds, CIs, permutation tests, equal-step regime, oracle ablation |
| `locker/mutation.py` | Run mutants on test sets; bounded exhaustive search |
| `locker/experiments.py`, `report.py`, `cli.py` | Experiment protocol, charts, CLI |
| `tests/` | Unit tests (`test_sut_smoke.py` is the provided smoke test) |
| `docs/MODEL.md` | States, variables, operations, guards, invariants, assumptions, diagram |
| `docs/REPORT_SKELETON.md` | Technical-report outline pre-filled with findings and TODOs |
| `docs/VIVA_PREP.md` | Likely change requests and exactly which files each one touches |
| `docs/CHANGE_REQUESTS.md` | One-file change-request workflow, field reference, presets, what the config cannot express |
| `results/` | Required protocol: raw tests, summaries, mutant matrices, charts, `experiment.json` |
| `results/extended/` | Extended evaluation outputs (CSV, JSON, charts) |

## Design in one paragraph

The **model** never touches the SUT: it is a table of guarded rules per `(state, operation)`, and the
same table yields the 35-transition catalogue and 305 transition pairs used as coverage denominators.
**Generators** use the model (not the SUT) to choose commands, so they are independent of execution.
The **runner** executes each sequence on a fresh SUT and model in lock-step; after every command the
**oracle** checks (1) result and the *complete* snapshot against the model, (2) structural state
invariants on the SUT snapshot, (3) that rejected operations left the SUT unchanged. Mutants are
subclasses of the SUT; each test set is replayed against every mutant to compute the mutation score.

## Headline results (seeds 1–5, 500 tests, max length 20; see `results/`)

| Strategy | State % | Transition % | Pair % | Mutation score | Tests to 1st kill* | Unique tests |
|---|---|---|---|---|---|---|
| A random | 100 | 100 | 86.6 ± 1.4 | 89.5 | 19.6 | 96.4 % |
| B coverage | 100 | 100 | 99.9 ± 0.1 | 89.5 | 20.3 | 100 % |
| C pair | 100 | 100 | 100 | 89.5 | 5.9 | 100 % |

\*mean over detected mutants. All three score 17/19 but **miss different mutants**: random misses the
pair-triggered M17, B and C miss the three-cycle fault M19, and all miss M16 (needs a near-miss
credential; killed with `--near-miss`). Union over strategies: 18/19 = 94.7 %. Higher coverage did not
translate into a higher score — see `docs/REPORT_SKELETON.md` for the discussion points.

## Extended evaluation (beyond the minimum protocol)

The required protocol above is unchanged. `python -m locker extended` adds, each addressing a
limitation of it: 30 seeds with 95 % CIs and Bonferroni-corrected paired permutation tests; an
**equal step budget** regime (the strategies generate tests of different lengths); two supplementary
strategies (`scenario` usage-profile testing, `random_pure` = Strategy A without model guidance);
**12 held-out mutants** written by a separate agent that saw only the SUT and requirements, never the
generators or my mutants; an **enriched input alphabet** regime; an **oracle ablation**; and
**model mutation**. Required strategies A/B/C are untouched; the extras are supplementary.

Mutation score over all 29 non-equivalent mutants (core + held-out), mean over 30 seeds, 95 % CI:

| Strategy | 500 tests, default alphabet | Equal 5000-step budget | 500 tests, enriched alphabet | Pair cov. (default) |
|---|---|---|---|---|
| random (A) | 86.9 ± 0.5 | 86.9 ± 0.5 | 97.2 ± 0.5 | 87.2 % |
| coverage (B) | 82.8 ± 0.0 | 82.3 ± 0.5 | 92.8 ± 0.4 | 99.9 % |
| pair (C) | 82.8 ± 0.0 | 82.8 ± 0.0 | 93.3 ± 0.5 | 100 % |
| scenario (extra) | 87.9 ± 0.7 | 87.3 ± 0.6 | 96.9 ± 0.4 | 82.6 % |
| random_pure (ablation) | 80.6 ± 0.8 | 80.6 ± 0.8 | 89.5 ± 0.9 | 95.9 % |

What the data says (details and caveats in `docs/REPORT_SKELETON.md`):
* **Higher structural coverage did not give a higher mutation score; it was slightly lower.**
  The systematic strategies (B, C) never repeat full delivery cycles, so they miss the history-dependent
  faults M19 and H05 (third retrieval), which random and scenario testing find in 30/30 seeds.
  Random vs pair: +4.1 points, Bonferroni p = 0.0025. Random vs scenario is not significant.
* **The equal-budget regime does not change the conclusions.** Pair needs 250 tests where random needs 478
  for the same 5000 steps, and finds its first kill in about half the steps (114 vs 221).
* **Three mutants survived every strategy under the default alphabet** (M16 prefix-match, H01 lowercase
  customer IDs, H10 another customer's code). They need input classes the default alphabet lacks; the
  enriched alphabet kills all three in 30/30 seeds for every strategy.
* **Model guidance helps:** `random` beats `random_pure` by 6.3 points (86.9 vs 80.6).
* **Oracle ablation** (mutation score, random/coverage/pair): accepted flag only 55-59 %; + message text
  62-66 %; + full snapshot vs model 83-86 %; invariants + rejection purity *without* the model 45-48 %.
  The model comparison does the heavy lifting; invariants and rejection purity add no extra kills on this
  mutant set (they give better diagnostics). Message checking matters only for the two message-only
  mutants H03/H04, which is why assumption A8 is documented.
* **Model mutation:** all 6 deliberately wrong models are exposed against the reference SUT (e.g. "cancel
  allowed when occupied" takes 2 tests for B/C but 50 for A), evidence the framework would reveal a
  mis-specified model.

## Practising change requests (viva)

Edit a value in `POLICY` (`locker/rules_config.py`) and run `python -m locker change`: it shows the
policy diff, how the model's transitions/pairs changed, and how each strategy fares against the
unchanged SUT (flagged = the change is detected) and against `PolicySUT` (the changed system; must
pass). Presets: `python -m locker change --preset disable_when_occupied`, all of them with
`python -m locker change --all`; ad hoc: `--set cancel_from=RESERVED,OCCUPIED`. Revert by setting the value back
(or `git checkout locker/rules_config.py` once committed). Full guide: `docs/CHANGE_REQUESTS.md`.

## AI-assistance disclosure

> TODO (required by the assignment): state which parts were produced with AI assistance, which tool(s),
> and what you reviewed/changed yourself.

## Provided starter notes

Smoke tests: `python -m unittest discover -s tests -v`. Requirements: `data/requirements.md`.
Do not call the SUT from the model or inspect its internal fields (the model here obeys this; mutants
intentionally subclass the SUT).
