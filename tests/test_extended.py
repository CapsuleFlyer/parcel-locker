import unittest

from locker.extended import (ALL_MUTANTS, ORACLES, ExtendedConfig, model_mutation, mean_sd_ci,
                             paired_permutation_p, t_crit)
from locker.generators import EXTENDED_GENERATORS, GENERATORS
from locker.model_mutants import MODEL_MUTANTS
from locker.mutants import MUTANTS
from locker.mutants_heldout import HELDOUT_MUTANTS
from locker.mutation import bounded_search, run_mutant_on_set
from locker.runner import SequenceRunner
from locker.types import Command, Operation as Op


class TestSupplementaryStrategies(unittest.TestCase):
    def test_required_strategies_unchanged(self):
        self.assertEqual(sorted(GENERATORS), ["coverage", "pair", "random"])
        self.assertEqual(sorted(EXTENDED_GENERATORS),
                         ["coverage", "pair", "random", "random_pure", "scenario"])

    def test_reproducible_bounded_and_passing(self):
        for name in ("scenario", "random_pure"):
            G = EXTENDED_GENERATORS[name]
            a = G(5, 15).generate(40)
            self.assertEqual(a, G(5, 15).generate(40))
            self.assertTrue(all(1 <= len(s) <= 15 for s in a))
            self.assertTrue(all(r.passed for r in SequenceRunner().run_many(a, name, 5)))

    def test_scenario_contains_repeated_delivery_cycles(self):
        m19 = next(m for m in MUTANTS if m.id == "M19")
        seqs = EXTENDED_GENERATORS["scenario"](1, 20).generate(500)
        self.assertTrue(run_mutant_on_set(m19, seqs, "scenario", 1).detected)

    def test_pure_random_has_more_rejections_than_guided(self):
        def rejected_share(name):
            recs = SequenceRunner().run_many(EXTENDED_GENERATORS[name](1, 20).generate(200), name, 1)
            tr = [t for r in recs for t in r.trace]
            return sum(not t.accepted for t in tr) / len(tr)
        self.assertGreater(rejected_share("random_pure"), rejected_share("random"))


class TestHeldOutMutants(unittest.TestCase):
    def test_count_and_unique_ids(self):
        self.assertEqual(len(HELDOUT_MUTANTS), 12)
        self.assertEqual(len({m.id for m in ALL_MUTANTS}), len(ALL_MUTANTS))

    def test_witnesses(self):
        for m in HELDOUT_MUTANTS:
            if m.expected_equivalent:
                continue
            self.assertTrue(SequenceRunner().run(list(m.witness)).passed, m.id)
            self.assertFalse(SequenceRunner(sut_factory=m.factory).run(list(m.witness)).passed, m.id)

    def test_equivalent_heldout_survive_bounded_search(self):
        for m in HELDOUT_MUTANTS:
            if m.expected_equivalent:
                self.assertFalse(bounded_search(m, depth=4, near_miss=True)["distinguishable"], m.id)


class TestOracleLayers(unittest.TestCase):
    CYCLE = [Command(Op.RESERVE, customer_id="C1"), Command(Op.DEPOSIT, code="R-C1"),
             Command(Op.RETRIEVE, code="P-C1")]

    def test_state_only_defect_needs_state_layer(self):
        m09 = next(m for m in MUTANTS if m.id == "M09")   # stale retrieval code after retrieve
        weak = SequenceRunner(sut_factory=m09.factory, **ORACLES["O0 accepted-flag only"])
        self.assertTrue(weak.run(self.CYCLE).passed)       # return values identical
        self.assertFalse(SequenceRunner(sut_factory=m09.factory).run(self.CYCLE).passed)

    def test_invariants_alone_catch_it_without_the_model(self):
        m09 = next(m for m in MUTANTS if m.id == "M09")
        inv = SequenceRunner(sut_factory=m09.factory, **ORACLES["O4 invariants + purity only (no model)"])
        self.assertFalse(inv.run(self.CYCLE).passed)

    def test_message_only_defect_needs_message_layer(self):
        h03 = next(m for m in HELDOUT_MUTANTS if m.id == "H03")
        no_msg = SequenceRunner(sut_factory=h03.factory, **ORACLES["O0 accepted-flag only"])
        self.assertTrue(no_msg.run(list(h03.witness)).passed)
        self.assertFalse(SequenceRunner(sut_factory=h03.factory).run(list(h03.witness)).passed)


class TestModelMutation(unittest.TestCase):
    def test_every_wrong_model_is_exposed(self):
        rows = model_mutation(ExtendedConfig(model_mutant_tests=150))
        self.assertEqual(len(rows), len(MODEL_MUTANTS))
        for r in rows:
            self.assertTrue(r["detected"], r["model_mutant"])


class TestStats(unittest.TestCase):
    def test_permutation_test(self):
        self.assertEqual(paired_permutation_p([0, 0, 0], 1000), 1.0)
        self.assertLess(paired_permutation_p([5.0] * 20, 5000), 0.001)
        self.assertGreater(paired_permutation_p([1, -1, 1, -1, 1, -1], 2000), 0.5)

    def test_ci(self):
        m, sd, ci = mean_sd_ci([1.0, 2.0, 3.0])
        self.assertAlmostEqual(m, 2.0)
        self.assertGreater(ci, 0)
        self.assertEqual(mean_sd_ci([4.0]), (4.0, 0.0, 0.0))
        self.assertAlmostEqual(t_crit(30), 2.045)


if __name__ == "__main__":
    unittest.main()
