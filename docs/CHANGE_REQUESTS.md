# Change requests: the one-file workflow

Assignment §10: the instructor may change a rule live and ask you to update the model, oracle and
tests, run them, and explain the effect on coverage and fault detection. Everything an instructor is
likely to tweak is a field of `POLICY` in **`locker/rules_config.py`**.

## 30-second workflow

1. Open `locker/rules_config.py`, change a value in `POLICY` (comments show example values).
2. `python -m locker change` — drill report (below).
3. Say what happened (answer template at the bottom).
4. Revert: set the value back, or `git checkout locker/rules_config.py` once the repo has a commit. `tests/test_policy.py::
   test_shipped_policy_is_the_baseline` and the baseline tests in `test_model.py` fail while `POLICY` is
   edited, on purpose: they pin the hand-derived 35 transitions / 305 pairs of the *requirements*.

No-edit variants: `python -m locker change --preset cancel_when_occupied`,
`python -m locker change --set cancel_from=RESERVED,OCCUPIED --set expire_requires_flag=false`,
`python -m locker change --list`, `python -m locker change --all` (every preset, one table).

## Who reads the policy

| Consumer | What it takes from `rules_config` |
|---|---|
| `model.py` `build_rules(policy)` | builds the declarative rule table (guards, destinations, outcomes) and the data effects; catalogue + pairs are derived from it, so coverage denominators follow automatically |
| `oracle.py` `check_snapshot_invariants` | the credential formats used by invariants I2/I3 (this was hardcoded `R-`/`P-` before) |
| `generators.py` `candidate_commands` | adds credential input classes for `CANCEL` when `cancel_requires_code` is on; strategies B and C re-plan over the new catalogue (`_accepted_edges` is cached per policy) |
| `policy_sut.py` `PolicySUT` | hand-written if-chain implementing the same knobs = "the system after the change was implemented" |
| `change.py` / CLI | the drill itself |

The provided `sut.py` is never edited. Mutants subclass it and are unaffected.

## Fields

| Field | Meaning | Allowed |
|---|---|---|
| `reservation_code_template`, `retrieval_code_template` | credential formats, `{cid}` = customer id | must contain `{cid}`; must differ unless `retrieve_also_accepts_reservation_code` |
| `retrieve_also_accepts_reservation_code` | auth change: either code opens an occupied locker | bool |
| `reserve_from` | states RESERVE is accepted from | subset of {AVAILABLE, MAINTENANCE}, non-empty |
| `cancel_from` | states CANCEL is accepted from (data cleared) | subset of {RESERVED, OCCUPIED} |
| `expire_from` | states EXPIRE is accepted from | subset of {RESERVED, OCCUPIED} |
| `disable_from` | states DISABLE is accepted from (booking/parcel discarded) | subset of {AVAILABLE, RESERVED, OCCUPIED} |
| `enable_from` | states ENABLE is accepted from | subset of {MAINTENANCE} |
| `cancel_requires_code` | CANCEL must carry the reservation code (else `invalid_reservation_code`) | bool |
| `expire_requires_flag` | EXPIRE needs `expired=True` (else `not_expired`) | bool |
| `expire_target` | state after a successful EXPIRE (data cleared either way) | AVAILABLE or MAINTENANCE |

Invalid combinations raise a `ValueError` that says what is allowed.

## Presets (each = baseline + a few edits; sizes are model transitions / transition pairs)

| Preset | Instructor sentence | Trans. | Pairs |
|---|---|---|---|
| `disable_when_occupied` | "Maintenance may now be initiated while a compartment is occupied" | 35 | 304 |
| `disable_when_busy` | same, also from RESERVED | 35 | 302 |
| `cancel_when_occupied` | "A reservation may be cancelled under an additional condition" (state) | 35 | 304 |
| `cancel_needs_code` | "...under an additional condition" (credential) | 36 | 324 |
| `retrieve_either_code` | "The retrieval authentication mechanism may change" | 35 | 305 |
| `new_code_format` | same, credential format change | 35 | 305 |
| `expire_ignores_flag` | "The expiry policy may be modified" | 34 | 288 |
| `expire_to_maintenance` | same, destination changes | 35 | 305 |
| `expire_when_occupied` | same, parcel expiry | 36 | 322 |
| `reserve_in_maintenance` | "A locker in maintenance may be pre-reserved" | 35 | 307 |

Baseline: 35 / 305. `tests/test_policy.py` pins these sizes and checks, for every preset, that the new
model and `PolicySUT` agree on all tests while the unchanged SUT is flagged.

## Reading the `change` output

```
strategy   tests | orig. SUT fails | PolicySUT fails | state% trans% pair% | tests hitting new transitions
```
* **orig. SUT fails > 0** is *good*: the provided SUT does not implement the new rule, so the
  framework detects the changed behaviour. The "First discrepancy" block is your live
  "detected a fault" demo (sequence, expected vs actual, oracle layer that fired).
* **PolicySUT fails = 0**: model and the changed implementation agree. Non-zero means the change is
  inconsistent (a bug in the edit, not in the framework).
* **coverage columns** are measured on the new model's catalogue: this is the "how does the change
  affect coverage" answer. `pairs` shows how the denominator moved (`305 -> 304`).
* **tests hitting new transitions** shows which strategy actually exercises the changed behaviour
  (random gets there by chance; B and C are steered by the catalogue).
* A `WARNING: states unreachable` line means the policy cuts a state off, so 100 % coverage is
  impossible by construction (e.g. `--set disable_from=none` makes MAINTENANCE unreachable).

## What the config cannot express (do these as code edits)

* **New operation** (e.g. `EXTEND`): add to `Operation` in `types.py`; add a row to `DEFAULT_REJECTION`
  and the rules in `build_rules` (`model.py`); add commands to `candidate_commands`
  (`generators.py`); extend `PolicySUT.execute`. The catalogue grows by one transition per state
  at least; B and C pick it up through the catalogue, A through the alphabet.
* **New state** (e.g. `GRACE`, or a maintenance state that *keeps* the parcel): add to `State` in
  `types.py`; rules and `_on_*` effects in `model.py`; invariants in `oracle.py` (new `I5`); `PolicySUT`.
  A "disabled while occupied but the parcel stays" request needs this: if MAINTENANCE could hold a
  parcel without being a different state, which transition `ENABLE` takes would depend on hidden data,
  and the generators plan over abstract states, so the catalogue would contain unrealisable pairs.
* **Counters** (lock-out after 3 wrong codes): add a field to `_Data`, update guards/effects, add
  invariants, extend the SUT. Transition identity then depends on the counter, so decide whether it
  is a state variable (bounded) or a new state.
* **Authentication that is not a template** (e.g. PIN plus customer match): change
  `_code_matches_reservation` / `_code_matches_retrieval` in `model.py`, the `*_code` helpers, and
  `candidate_commands` (new input classes, e.g. right PIN wrong customer).

## What to say in the viva (answer template)

1. *Impact on the model:* which `(state, operation)` rules changed, how many transitions/pairs the
   catalogue gained or lost (read it from the report).
2. *Which strategies are affected:* all three read the catalogue/alphabet, so the denominators change; A is
   only affected through chance of reaching the new rule (see "tests hitting new transitions").
3. *Oracle:* comparison with the model follows automatically; the invariants only needed an edit
   if the change touches credential formats or data in a state (I1 to I3).
4. *Evidence:* the unchanged SUT is flagged (live fault detection) and the changed SUT passes.
5. *Coverage / fault detection:* coverage was re-measured on the new catalogue; existing mutants that
   encoded the old rule (e.g. M05 `CancelWhenOccupied` under `cancel_when_occupied`) become correct
   behaviour and must be retired from the mutation score.

## Honest limits

`PolicySUT` is written by the same author from the same knobs, so "model == PolicySUT" shows the change
was applied consistently, not that either is correct. The independent evidence is the comparison with the
*provided* SUT and the unit tests of individual rules. In the real viva the instructor's changed SUT may
behave differently from your reading of the request: re-run against it and read the failure details.
