# Viva Preparation: likely "unseen change requests"

Assignment §10 says the instructor may change a rule live. For each, this lists what to edit and what
to re-run. Practise at least three of them before the viva.

**General workflow:** edit the rule table (`locker/model.py`) → note the catalogue changes
(`python -c "from locker.model import *; print(len(transition_catalogue()), len(transition_pairs()))"`)
→ if the SUT is changed too, the reference SUT's behaviour must match (or generate a SUT variant via
`locker/mutants.py` style subclass) → `python -m unittest discover -s tests` → `python -m locker experiment`.

| Change request | Edit | Fallout to explain |
|---|---|---|
| "Maintenance may now start while OCCUPIED" | add `(O, Op.DISABLE): [Rule("disabled", M, True)]` in `RULES`; decide effect on data (keep? clear?) via `EFFECTS["disabled"]`; invariant I1 must now allow data in MAINTENANCE | New transition(s) → catalogue/pairs grow; `ENABLE` from MAINTENANCE may now need to restore OCCUPIED (new state or flag). `tests/test_model.py::test_maintenance` and `test_counts_match_hand_derivation` (35/305) must be updated deliberately. Strategies B and C adapt automatically because they read the catalogue; A needs no change. |
| "Cancel allowed in OCCUPIED" / "under an extra condition" | add a Rule in `RULES[(O, Op.CANCEL)]` with a guard function | Mutant M05 (`CancelWhenOccupied`) becomes *correct* behaviour → update/retire it. Oracle `I*` unaffected. |
| "Retrieval auth changes (e.g. PIN, or code must match customer + parcel)" | change `retrieval_code_for` / `_code_matches_retrieval`; add input class in `candidate_commands` | Credential input classes in the generators; mutants M03, M09, M15, M16 interact. |
| "Expiry policy: expired RESERVED goes to a grace state / parcel returned" | new `State` in `types.py` and `RULES`; adjust `_on_clear`/EXPIRE rule | New state raises state denominator to 5; coverage tables change; invariants add I5. |
| "New operation (e.g. EXTEND reservation, REPORT_FAULT)" | add to `Operation` enum, `DEFAULT_REJECTION`, `RULES`, `candidate_commands` | Catalogue grows by ≥4 (one per state); generators pick it up through the alphabet. |
| "Compare only accepted flag, not message" | `SequenceRunner(compare_messages=False)` | M-series mutants that only change messages would survive. |
| "Add 2 more customers / multiple compartments" | `DEFAULT_CUSTOMERS` in `generators.py` | Larger alphabet; M14 detection time changes. |

## Questions to be able to answer

* Why is the model independent of the SUT, and where is the residual risk? (rule table vs if-chain;
  A8; both from same prose.)
* How is a transition defined? How are transition pairs defined and counted (305)? Why do
  rejections count as transitions? Why are all 305 pairs realisable?
* Why does B reach full transition coverage in ~5 tests, and why does it still miss M19?
* Why does random miss M17, and why can pair coverage miss M19? (length-2 vs length-9 history)
* Why does M16 survive, and what did you do about it? (alphabet gap; `--near-miss`; witness test)
* Why are E01/E02 equivalent? How did you check? What is *not* proved?
* What does the oracle check beyond return values? What would an unauthorised retrieve look like in
  the failure record? (`python -m locker strategy --name random --mutant M03`)
* How do seeds make the experiment reproducible? Why are sets sorted before choices?
  (`PYTHONHASHSEED` test)
* Which parts did you (not the AI tool) write and how would you modify them live?
