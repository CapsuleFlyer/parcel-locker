# Viva Preparation: likely "unseen change requests"

Assignment §10 says the instructor may change a rule live. For each, this lists what to edit and what
to re-run. Practise at least three of them before the viva.

**General workflow (details in `docs/CHANGE_REQUESTS.md`):** edit the matching field of `POLICY` in
`locker/rules_config.py` → `python -m locker change` (model vs the unchanged SUT = detected change;
model vs `PolicySUT` = consistent implementation) → note the catalogue/pair delta it prints →
`python -m unittest discover -s tests` (the baseline pins fail on purpose while `POLICY` is edited) →
revert by setting the value back (or `git checkout locker/rules_config.py` once committed). Presets: `python -m locker change --list`.

| Change request | Edit | Fallout to explain |
|---|---|---|
| "Maintenance may now start while OCCUPIED" | `disable_from=_states(A, O)` (preset `disable_when_occupied`) | 305 → 304 pairs, new transition `OCCUPIED--DISABLE[disabled]-->MAINTENANCE`; the parcel is discarded (data cleared). A variant where the parcel *stays* needs a new state (doc: "What the config cannot express"). Strategies B and C adapt through the catalogue; A only reaches it by chance. |
| "Cancel allowed in OCCUPIED" | `cancel_from=_states(R, O)` (`cancel_when_occupied`) | Mutant M05 (`CancelWhenOccupied`) becomes *correct* behaviour → retire it from the score. |
| "Cancel under an extra condition" | `cancel_requires_code=True` (`cancel_needs_code`) | New rejection transitions (36 transitions, 324 pairs); `CANCEL` gets credential input classes in the alphabet. |
| "Retrieval auth changes" | `retrieve_also_accepts_reservation_code=True` (`retrieve_either_code`) or the code templates (`new_code_format`) | Oracle invariants I2/I3 follow the templates; mutants M03, M09, M15, M16 interact. A non-template mechanism (PIN + customer match) is a code edit of `_code_matches_*`. |
| "Expiry policy changes" | `expire_target=M`, `expire_requires_flag=False`, `expire_from=_states(R, O)` (`expire_*` presets) | Catalogue size changes (34/36 transitions for the last two); M04 `EarlyExpire` and M08 `ExpireWhenOccupied` encode old rules. A *grace state* is a new `State`. |
| "New operation (e.g. EXTEND, REPORT_FAULT)" | code: `Operation` enum, `DEFAULT_REJECTION`, `build_rules`, `candidate_commands`, `PolicySUT` | Catalogue grows by ≥ 4 (one per state); generators pick it up through the alphabet. |
| "Compare only accepted flag, not message" | `SequenceRunner(compare_messages=False)` | Message-only mutants (H03/H04) would survive. |
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
* Pair coverage reached 100 % but the mutation score was *lower* than random's. Why? (M19/H05 need 3
  repeated cycles; pair coverage constrains history length 2; strategies stop caring once covered.)
* Why is the extended `scenario` strategy partly post-hoc, and why do the held-out mutants matter?
* What did the oracle ablation show about invariants vs the model? Which mutants need message checks?
* What is model mutation and what does it tell you about the framework?
* Why can a zero-width confidence interval be misleading here?
* Which parts did you (not the AI tool) write and how would you modify them live?
