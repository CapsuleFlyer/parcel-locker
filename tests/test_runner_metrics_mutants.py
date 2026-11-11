import unittest

from locker.metrics import calculate_coverage, mutation_summary, redundancy_report
from locker.model import transition_catalogue
from locker.mutants import MUTANTS
from locker.mutation import bounded_search, run_mutant_on_set
from locker.oracle import check_no_mutation_on_reject, check_snapshot_invariants
from locker.runner import SequenceRunner
from locker.sut import ParcelLocker
from locker.types import Command, Operation as Op, Result, Snapshot, State

LIFECYCLE = [Command(Op.RESERVE, customer_id="C1"), Command(Op.DEPOSIT, code="R-C1"),
             Command(Op.RETRIEVE, code="P-C1")]


class TestRunner(unittest.TestCase):
    def test_pass_on_reference(self):
        rec = SequenceRunner().run(LIFECYCLE, "t1", "manual", None)
        self.assertTrue(rec.passed)
        self.assertEqual(rec.steps_executed, 3)
        self.assertEqual(len(rec.trace), 3)
        self.assertEqual(rec.initial_state, "AVAILABLE")

    def test_empty_sequence_passes(self):
        self.assertTrue(SequenceRunner().run([]).passed)

    def test_fail_record_is_complete(self):
        spec = next(m for m in MUTANTS if m.name == "RetrieveWithoutAuth")
        rec = SequenceRunner(sut_factory=spec.factory).run(
            LIFECYCLE[:2] + [Command(Op.RETRIEVE, code="WRONG")], "t2", "manual", 9)
        self.assertFalse(rec.passed)
        self.assertEqual(rec.failure_index, 2)
        self.assertEqual(rec.failure_kind, "result_mismatch")
        self.assertEqual((rec.expected_result.accepted, rec.actual_result.accepted), (False, True))
        self.assertEqual(rec.expected_final_state.state, State.OCCUPIED)
        self.assertEqual(rec.actual_final_state.state, State.AVAILABLE)
        row = rec.to_row()
        self.assertEqual(row["outcome"], "FAIL")
        self.assertEqual(row["seed"], 9)

    def test_sut_exception_is_a_failure_not_a_crash(self):
        class Boom(ParcelLocker):
            def execute(self, c):
                raise RuntimeError("boom")
        rec = SequenceRunner(sut_factory=Boom).run(LIFECYCLE)
        self.assertFalse(rec.passed)
        self.assertEqual(rec.failure_kind, "sut_exception")


class TestOracle(unittest.TestCase):
    def test_invariants(self):
        ok = Snapshot(State.OCCUPIED, "C1", "R-C1", "P-C1")
        self.assertEqual(check_snapshot_invariants(ok), [])
        self.assertTrue(check_snapshot_invariants(Snapshot(State.AVAILABLE, "C1", None, None)))
        self.assertTrue(check_snapshot_invariants(Snapshot(State.RESERVED, "C1", "R-C2", None)))
        self.assertTrue(check_snapshot_invariants(Snapshot(State.OCCUPIED, "C1", "R-C1", None)))

    def test_reject_must_not_mutate(self):
        a, b = Snapshot(State.RESERVED, "C1", "R-C1", None), Snapshot(State.AVAILABLE, None, None, None)
        self.assertTrue(check_no_mutation_on_reject(a, b, Result(False, "x")))
        self.assertFalse(check_no_mutation_on_reject(a, b, Result(True, "x")))


class TestMetrics(unittest.TestCase):
    def test_empty_trace(self):
        c = calculate_coverage([])
        self.assertEqual((c["state"]["covered"], c["state"]["total"]), (1, 4))  # initial state only
        self.assertEqual(c["transition"]["covered"], 0)

    def test_lifecycle_counts(self):
        rec = SequenceRunner().run(LIFECYCLE)
        c = calculate_coverage([rec.trace])
        self.assertEqual(c["state"]["covered"], 3)           # AVAILABLE, RESERVED, OCCUPIED
        self.assertEqual(c["transition"]["covered"], 3)
        self.assertEqual(c["transition_pair"]["covered"], 2)  # 3 transitions -> 2 adjacent pairs
        self.assertEqual(c["transition"]["total"], len(transition_catalogue()))

    def test_duplicates_not_double_counted(self):
        rec = SequenceRunner().run(LIFECYCLE)
        self.assertEqual(calculate_coverage([rec.trace, rec.trace]), calculate_coverage([rec.trace]))

    def test_mutation_summary_excludes_equivalent(self):
        s = mutation_summary([{"name": "a", "detected": True}, {"name": "b", "detected": False},
                              {"name": "e", "detected": False, "equivalent": True}])
        self.assertEqual(s["considered"], 2)
        self.assertEqual(s["mutation_score"], 50.0)
        self.assertEqual(s["survived"], ["b"])
        self.assertEqual(s["equivalent"], ["e"])

    def test_redundancy(self):
        r = redundancy_report([["a"], ["a"], ["b"]])
        self.assertEqual((r["total"], r["unique"], r["duplicates"]), (3, 2, 1))


class TestMutants(unittest.TestCase):
    def test_at_least_eight_distinct_non_equivalent_mutants(self):
        real = [m for m in MUTANTS if not m.expected_equivalent]
        self.assertGreaterEqual(len(real), 8)
        self.assertEqual(len({m.id for m in MUTANTS}), len(MUTANTS))

    def test_every_non_equivalent_mutant_is_killed_by_its_witness(self):
        runner_ref = SequenceRunner()
        for m in MUTANTS:
            if m.expected_equivalent:
                continue
            self.assertTrue(m.witness, m.id)
            self.assertTrue(runner_ref.run(m.witness).passed, f"{m.id} witness fails on reference SUT")
            self.assertFalse(SequenceRunner(sut_factory=m.factory).run(m.witness).passed,
                             f"{m.id} witness does not expose mutant")

    def test_equivalent_mutants_survive_bounded_exhaustive_search(self):
        for m in MUTANTS:
            if m.expected_equivalent:
                res = bounded_search(m, depth=4, near_miss=True)
                self.assertFalse(res["distinguishable"], f"{m.id}: {res}")

    def test_near_miss_alphabet_kills_prefix_mutant(self):
        m = next(x for x in MUTANTS if x.id == "M16")
        self.assertFalse(bounded_search(m, depth=3, near_miss=False)["distinguishable"])
        self.assertTrue(bounded_search(m, depth=3, near_miss=True)["distinguishable"])

    def test_run_mutant_on_set(self):
        m = next(x for x in MUTANTS if x.id == "M07")
        run = run_mutant_on_set(m, [LIFECYCLE, m.witness], "manual", 1)
        self.assertTrue(run.detected)
        self.assertEqual((run.kill_count, run.tests_to_first_kill), (1, 2))


if __name__ == "__main__":
    unittest.main()
