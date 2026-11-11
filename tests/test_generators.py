import os
import subprocess
import sys
import unittest

from locker.generators import GENERATORS
from locker.metrics import calculate_coverage
from locker.runner import SequenceRunner, format_sequence


class TestGenerators(unittest.TestCase):
    def test_reproducible_for_same_seed_and_different_across_seeds(self):
        for name, G in GENERATORS.items():
            a = G(7, 12).generate(30)
            self.assertEqual(a, G(7, 12).generate(30), name)
            self.assertNotEqual(a, G(8, 12).generate(30), name)

    def test_reproducible_across_processes_and_hash_seeds(self):
        code = ("from locker.generators import GENERATORS;from locker.runner import format_sequence;"
                "print(hash(tuple(format_sequence(s) for s in GENERATORS['{n}'](3,15).generate(40))) "
                "if False else '\\n'.join(format_sequence(s) for s in GENERATORS['{n}'](3,15).generate(40)))")
        for name in GENERATORS:
            outs = set()
            for hs in ("0", "1", "12345"):
                env = dict(os.environ, PYTHONHASHSEED=hs)
                r = subprocess.run([sys.executable, "-c", code.format(n=name)], capture_output=True,
                                   text=True, env=env, check=True)
                outs.add(r.stdout)
            self.assertEqual(len(outs), 1, f"{name} depends on PYTHONHASHSEED")

    def test_length_bound_and_nonempty(self):
        for name, G in GENERATORS.items():
            for L in (1, 3, 20):
                seqs = G(1, L).generate(60)
                self.assertEqual(len(seqs), 60)
                self.assertTrue(all(1 <= len(s) <= L for s in seqs), (name, L))

    def test_generated_tests_pass_on_reference_sut(self):
        for name, G in GENERATORS.items():
            recs = SequenceRunner().run_many(G(2, 20).generate(100), name, 2)
            self.assertTrue(all(r.passed for r in recs), name)

    def test_valid_and_invalid_operations_both_generated(self):
        for name, G in GENERATORS.items():
            recs = SequenceRunner().run_many(G(2, 20).generate(100), name, 2)
            outcomes = {t.accepted for r in recs for t in r.trace}
            self.assertEqual(outcomes, {True, False}, name)

    def test_pair_strategy_reaches_full_pair_coverage(self):
        recs = SequenceRunner().run_many(GENERATORS["pair"](1, 20).generate(200), "pair", 1)
        cov = calculate_coverage(r.trace for r in recs)
        self.assertEqual(cov["transition_pair"]["percent"], 100.0)
        self.assertEqual(cov["transition"]["percent"], 100.0)

    def test_strategies_are_genuinely_different(self):
        outs = {n: [format_sequence(s) for s in G(1, 20).generate(50)] for n, G in GENERATORS.items()}
        names = list(outs)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                self.assertNotEqual(outs[names[i]], outs[names[j]])

    def test_coverage_guided_beats_random_on_early_transition_coverage(self):
        cov = {}
        for n in ("random", "coverage"):
            recs = SequenceRunner().run_many(GENERATORS[n](1, 20).generate(5), n, 1)
            cov[n] = calculate_coverage(r.trace for r in recs)["transition"]["covered"]
        self.assertGreater(cov["coverage"], cov["random"])


if __name__ == "__main__":
    unittest.main()
