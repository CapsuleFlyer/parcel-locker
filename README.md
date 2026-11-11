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
python -m unittest discover -s tests -v     # 41 tests: model, generators, runner, oracle, metrics, mutants
python -m locker demo                       # 1-minute end-to-end walkthrough
python -m locker experiment                 # full Task-5 protocol -> results/   (~15 s)
python -m locker report                     # charts -> results/charts/          (needs matplotlib)
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
| `locker/model.py` | Independent executable state machine (declarative rule table), transition & pair catalogues |
| `locker/oracle.py` | Result/snapshot comparison, state invariants, rejection-purity checks |
| `locker/runner.py` | `SequenceRunner`: lock-step execution, per-test `ExecutionRecord` |
| `locker/generators.py` | Strategy A random, B coverage-directed, C transition-pair |
| `locker/metrics.py` | State / transition / transition-pair coverage, redundancy, mutation score |
| `locker/mutants.py` | 19 non-equivalent + 2 equivalent mutants (subclasses of the SUT) |
| `locker/mutation.py` | Run mutants on test sets; bounded exhaustive search |
| `locker/experiments.py`, `report.py`, `cli.py` | Experiment protocol, charts, CLI |
| `tests/` | Unit tests (`test_sut_smoke.py` is the provided smoke test) |
| `docs/MODEL.md` | States, variables, operations, guards, invariants, assumptions, diagram |
| `docs/REPORT_SKELETON.md` | Technical-report outline pre-filled with findings and TODOs |
| `docs/VIVA_PREP.md` | Likely change requests and exactly which files each one touches |
| `results/` | Raw tests, per-run/per-strategy summaries, mutant matrices, charts, `experiment.json` |

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

## AI-assistance disclosure

> TODO (required by the assignment): state which parts were produced with AI assistance, which tool(s),
> and what you reviewed/changed yourself.

## Provided starter notes

Smoke tests: `python -m unittest discover -s tests -v`. Requirements: `data/requirements.md`.
Do not call the SUT from the model or inspect its internal fields (the model here obeys this; mutants
intentionally subclass the SUT).
