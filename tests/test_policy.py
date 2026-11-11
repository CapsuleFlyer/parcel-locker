"""Tests for the editable-rules layer (rules_config.py, PolicySUT, `change` drill)."""
import hashlib
import itertools
import unittest
from dataclasses import replace

from locker import rules_config as rc
from locker.change import reachable_states, resolve_policy, run_change
from locker.cli import main as cli_main
from locker.generators import EXTENDED_GENERATORS, candidate_commands
from locker.model import LockerModel, transition_catalogue, transition_pairs
from locker.oracle import check_snapshot_invariants
from locker.policy_sut import PolicySUT
from locker.rules_config import BASELINE, POLICY, PRESETS, Policy, parse_overrides, use_policy
from locker.runner import format_sequence
from locker.sut import ParcelLocker
from locker.types import Command, Operation as Op, Snapshot, State

A, R, O, M = State.AVAILABLE, State.RESERVED, State.OCCUPIED, State.MAINTENANCE


class TestBaselineIsUntouched(unittest.TestCase):
    def test_shipped_policy_is_the_baseline(self):
        """If this fails you edited POLICY (fine for a drill) - revert before the final run."""
        self.assertEqual(POLICY, BASELINE)

    def test_baseline_sizes(self):
        self.assertEqual(len(transition_catalogue(BASELINE)), 35)
        self.assertEqual(len(transition_pairs(BASELINE)), 305)

    def test_default_generators_and_catalogue_are_byte_identical_to_pre_policy_version(self):
        """Golden hash captured before the policy refactor: results/ stay valid."""
        h = hashlib.sha256()
        with use_policy(BASELINE):
            for t in transition_catalogue():
                h.update(t.label().encode())
            for a, b in transition_pairs():
                h.update((a.label() + b.label()).encode())
            for name, gen in sorted(EXTENDED_GENERATORS.items()):
                for near in (False, True):
                    for seq in gen(1, 20, near_miss=near).generate(40):
                        h.update(format_sequence(seq).encode())
        self.assertEqual(h.hexdigest(),
                         "ea14a603d619ce3bc4c2a0d5c48ec401500273f07c1ed17b67d550ae2e219dc9")


class TestPolicySutBaseline(unittest.TestCase):
    def test_policy_sut_equals_reference_sut_exhaustively_to_depth_4(self):
        alphabet = ([Command(Op.RESERVE, customer_id=c) for c in ("C1", "C2")] + [Command(Op.CANCEL)]
                    + [Command(Op.DEPOSIT, code=c) for c in ("R-C1", "R-C2", "P-C1", "", "WRONG")]
                    + [Command(Op.RETRIEVE, code=c) for c in ("P-C1", "P-C2", "R-C1", "", "WRONG")]
                    + [Command(Op.EXPIRE, expired=True), Command(Op.EXPIRE, expired=False),
                       Command(Op.DISABLE), Command(Op.ENABLE), Command(Op.INVALID_ACCESS, code="X")])
        for seq in itertools.product(alphabet, repeat=4):
            ref, pol = ParcelLocker(), PolicySUT(BASELINE)
            for cmd in seq:
                self.assertEqual(ref.execute(cmd), pol.execute(cmd), seq)
                self.assertEqual(ref.snapshot(), pol.snapshot(), seq)


class TestValidation(unittest.TestCase):
    def test_rejects_bad_policies(self):
        bad = [
            dict(reserve_from=frozenset()),
            dict(reserve_from=frozenset({O})),
            dict(cancel_from=frozenset({A})),
            dict(disable_from=frozenset({M})),
            dict(enable_from=frozenset({A})),
            dict(expire_target=O),
            dict(reservation_code_template="NOID"),
            dict(retrieval_code_template="R-{cid}"),       # same code as reservation
            dict(retrieval_code_template="P-{cid"),        # stray brace
            dict(cancel_from={R}),                         # a set, not a frozenset
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, KeyError, IndexError)):
                replace(BASELINE, **kwargs).validate()

    def test_same_template_allowed_when_either_code_opens_the_locker(self):
        replace(BASELINE, retrieval_code_template="R-{cid}",
                retrieve_also_accepts_reservation_code=True).validate()

    def test_parse_overrides(self):
        p = parse_overrides(BASELINE, ["cancel_from=reserved,occupied", "expire_requires_flag=false",
                                       "expire_target=maintenance", "retrieval_code_template=PIN-{cid}",
                                       "disable_from=none"])
        self.assertEqual(p.cancel_from, frozenset({R, O}))
        self.assertFalse(p.expire_requires_flag)
        self.assertEqual(p.expire_target, M)
        self.assertEqual(p.retrieval_code("C9"), "PIN-C9")
        self.assertEqual(p.disable_from, frozenset())

    def test_parse_overrides_errors(self):
        for item in ("nope=1", "cancel_from", "cancel_from=BOGUS", "expire_requires_flag=maybe",
                     "disable_from=MAINTENANCE"):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_overrides(BASELINE, [item])


class TestActivePolicy(unittest.TestCase):
    def test_use_policy_switches_and_restores(self):
        before = rc.get_policy()
        with use_policy(PRESETS["cancel_when_occupied"][1]):
            m = LockerModel()
            for c in (Command(Op.RESERVE, customer_id="C1"), Command(Op.DEPOSIT, code="R-C1")):
                m.step(c)
            self.assertTrue(m.step(Command(Op.CANCEL)).accepted)      # new rule active
        self.assertIs(rc.get_policy(), before)
        m = LockerModel()
        for c in (Command(Op.RESERVE, customer_id="C1"), Command(Op.DEPOSIT, code="R-C1")):
            m.step(c)
        self.assertFalse(m.step(Command(Op.CANCEL)).accepted)         # baseline again

    def test_use_policy_restores_even_on_error(self):
        before = rc.get_policy()
        with self.assertRaises(RuntimeError):
            with use_policy(PRESETS["new_code_format"][1]):
                raise RuntimeError("boom")
        self.assertIs(rc.get_policy(), before)

    def test_cancel_codes_enter_the_alphabet_only_when_required(self):
        snap = Snapshot(R, "C1", "R-C1", None)
        plain = [c for c in candidate_commands(snap) if c.operation == Op.CANCEL]
        self.assertEqual(plain, [Command(Op.CANCEL)])
        with use_policy(PRESETS["cancel_needs_code"][1]):
            coded = {c.code for c in candidate_commands(snap) if c.operation == Op.CANCEL}
        self.assertEqual(coded, {"R-C1", "WRONG", ""})

    def test_invariants_follow_the_credential_templates(self):
        good = Snapshot(R, "C1", "RSV-C1-A", None)
        with use_policy(PRESETS["new_code_format"][1]):
            self.assertEqual(check_snapshot_invariants(good), [])
            self.assertTrue(check_snapshot_invariants(Snapshot(R, "C1", "R-C1", None)))
        self.assertTrue(check_snapshot_invariants(good))              # baseline formats: violation


class TestPresets(unittest.TestCase):
    def test_every_preset_differs_from_baseline_and_is_valid(self):
        for name, (desc, pol) in PRESETS.items():
            with self.subTest(preset=name):
                self.assertTrue(desc)
                self.assertTrue(pol.diff(BASELINE))
                pol.validate()

    def test_every_preset_has_a_well_formed_catalogue(self):
        for name, (_, pol) in PRESETS.items():
            with self.subTest(preset=name):
                cat = transition_catalogue(pol)
                self.assertEqual(len(cat), len(set(cat)))
                for a, b in transition_pairs(pol):
                    self.assertEqual(a.dst, b.src)
                self.assertEqual(reachable_states(pol), set(State))

    def test_model_and_policy_sut_agree_and_original_sut_is_flagged(self):
        """The core drill: new model == PolicySUT; the unchanged SUT is detected as different."""
        for name, (_, pol) in PRESETS.items():
            with self.subTest(preset=name):
                res = run_change(pol, count=150, max_length=20, seed=1)
                self.assertTrue(res["model_matches_policy_sut"],
                                [(o.strategy, o.first_failure) for o in res["outcomes"]])
                self.assertTrue(any(o.fails_original for o in res["outcomes"]))

    def test_documented_catalogue_deltas(self):
        def delta(name):
            p = PRESETS[name][1]
            return len(transition_catalogue(p)), len(transition_pairs(p))
        self.assertEqual(delta("disable_when_occupied"), (35, 304))
        self.assertEqual(delta("cancel_when_occupied"), (35, 304))
        self.assertEqual(delta("cancel_needs_code"), (36, 324))
        self.assertEqual(delta("expire_ignores_flag"), (34, 288))
        self.assertEqual(delta("expire_when_occupied"), (36, 322))

    def test_specific_semantics(self):
        with use_policy(PRESETS["expire_to_maintenance"][1]):
            m = LockerModel()
            m.step(Command(Op.RESERVE, customer_id="C1"))
            r = m.step(Command(Op.EXPIRE, expired=True))
            self.assertTrue(r.accepted)
            self.assertEqual(m.state, M)
            self.assertEqual(m.snapshot(), Snapshot(M, None, None, None))   # data cleared
        with use_policy(PRESETS["retrieve_either_code"][1]):
            m = LockerModel()
            for c in (Command(Op.RESERVE, customer_id="C1"), Command(Op.DEPOSIT, code="R-C1")):
                m.step(c)
            self.assertTrue(m.step(Command(Op.RETRIEVE, code="R-C1")).accepted)
        with use_policy(PRESETS["disable_when_busy"][1]):
            m = LockerModel()
            m.step(Command(Op.RESERVE, customer_id="C1"))
            self.assertTrue(m.step(Command(Op.DISABLE)).accepted)
            self.assertEqual(m.snapshot(), Snapshot(M, None, None, None))   # booking discarded


class TestDegeneratePolicies(unittest.TestCase):
    def test_generators_survive_unreachable_states(self):
        for kwargs in (dict(disable_from=frozenset()), dict(enable_from=frozenset()),
                       dict(reserve_from=frozenset({M}), disable_from=frozenset())):
            pol = replace(BASELINE, **kwargs).validate()
            with use_policy(pol):
                for name, gen in EXTENDED_GENERATORS.items():
                    with self.subTest(policy=kwargs, strategy=name):
                        seqs = gen(1, 20).generate(30)
                        self.assertEqual(len(seqs), 30)
                        self.assertTrue(all(1 <= len(s) <= 20 for s in seqs))
        self.assertIn(M, set(State) - reachable_states(replace(BASELINE, disable_from=frozenset())))


class TestCli(unittest.TestCase):
    def test_list_and_preset_and_errors(self):
        self.assertEqual(cli_main(["change", "--list"]), 0)
        self.assertEqual(cli_main(["change", "--preset", "cancel_when_occupied", "--count", "60"]), 0)
        self.assertEqual(cli_main(["change", "--set", "cancel_from=RESERVED,OCCUPIED", "--count", "60"]), 0)
        with self.assertRaises(SystemExit):
            cli_main(["change", "--set", "bogus=1"])
        with self.assertRaises(SystemExit):
            cli_main(["change", "--preset", "nope"])

    def test_strategy_with_preset_and_policy_sut_passes(self):
        self.assertEqual(cli_main(["strategy", "--name", "pair", "--preset", "disable_when_occupied",
                                   "--policy-sut", "--count", "40"]), 0)

    def test_resolve_policy_labels(self):
        pol, label = resolve_policy("cancel_needs_code", ["expire_requires_flag=false"])
        self.assertTrue(pol.cancel_requires_code and not pol.expire_requires_flag)
        self.assertIn("cancel_needs_code", label)


if __name__ == "__main__":
    unittest.main()
