"""Unit tests for the executable model (independent of the SUT)."""
import unittest

from locker.model import (LockerModel, transition_catalogue, transition_pairs,
                          DEFAULT_REJECTION)
from locker.oracle import check_snapshot_invariants
from locker.types import Command, Operation as Op, State


def run(model, *cmds):
    return [model.step(c) for c in cmds]


class TestModelTransitions(unittest.TestCase):
    def setUp(self):
        self.m = LockerModel()

    def test_initial_state(self):
        s = self.m.snapshot()
        self.assertEqual((s.state, s.customer_id, s.reservation_code, s.retrieval_code),
                         (State.AVAILABLE, None, None, None))

    def test_full_lifecycle(self):
        r = run(self.m, Command(Op.RESERVE, customer_id="C7"), Command(Op.DEPOSIT, code="R-C7"),
                Command(Op.RETRIEVE, code="P-C7"))
        self.assertTrue(all(x.accepted for x in r))
        s = self.m.snapshot()
        self.assertEqual((s.state, s.customer_id, s.reservation_code, s.retrieval_code),
                         (State.AVAILABLE, None, None, None))   # req 7

    def test_codes(self):
        run(self.m, Command(Op.RESERVE, customer_id="C3"))
        self.assertEqual(self.m.snapshot().reservation_code, "R-C3")      # req 2
        run(self.m, Command(Op.DEPOSIT, code="R-C3"))
        self.assertEqual(self.m.snapshot().retrieval_code, "P-C3")        # req 5

    def test_reserve_only_when_available(self):
        run(self.m, Command(Op.RESERVE))
        for setup in ([], [Command(Op.DEPOSIT, code="R-C1")]):
            run(self.m, *setup)
            self.assertFalse(self.m.step(Command(Op.RESERVE, customer_id="C2")).accepted)
        m2 = LockerModel(); run(m2, Command(Op.DISABLE))
        self.assertFalse(m2.step(Command(Op.RESERVE)).accepted)

    def test_cancel_only_in_reserved(self):
        self.assertFalse(self.m.step(Command(Op.CANCEL)).accepted)
        run(self.m, Command(Op.RESERVE))
        self.assertTrue(self.m.step(Command(Op.CANCEL)).accepted)
        self.assertEqual(self.m.state, State.AVAILABLE)
        run(self.m, Command(Op.RESERVE), Command(Op.DEPOSIT, code="R-C1"))
        self.assertFalse(self.m.step(Command(Op.CANCEL)).accepted)        # assumption A1

    def test_deposit_needs_correct_code_and_reserved(self):
        self.assertFalse(self.m.step(Command(Op.DEPOSIT, code="R-C1")).accepted)
        run(self.m, Command(Op.RESERVE))
        before = self.m.snapshot()
        r = self.m.step(Command(Op.DEPOSIT, code="WRONG"))
        self.assertEqual((r.accepted, r.message), (False, "invalid_reservation_code"))
        self.assertEqual(self.m.snapshot(), before)                       # req 12

    def test_retrieve_needs_correct_code_and_occupied(self):
        run(self.m, Command(Op.RESERVE))
        self.assertFalse(self.m.step(Command(Op.RETRIEVE, code="P-C1")).accepted)  # not yet deposited
        run(self.m, Command(Op.DEPOSIT, code="R-C1"))
        before = self.m.snapshot()
        self.assertFalse(self.m.step(Command(Op.RETRIEVE, code="R-C1")).accepted)  # cross-use of codes
        self.assertFalse(self.m.step(Command(Op.RETRIEVE, code="")).accepted)
        self.assertEqual(self.m.snapshot(), before)
        self.assertTrue(self.m.step(Command(Op.RETRIEVE, code="P-C1")).accepted)
        self.assertFalse(self.m.step(Command(Op.RETRIEVE, code="P-C1")).accepted)  # no re-retrieval

    def test_expire(self):
        self.assertFalse(self.m.step(Command(Op.EXPIRE, expired=True)).accepted)   # not reserved
        run(self.m, Command(Op.RESERVE))
        r = self.m.step(Command(Op.EXPIRE, expired=False))
        self.assertEqual((r.accepted, r.message), (False, "not_expired"))
        self.assertEqual(self.m.state, State.RESERVED)
        self.assertTrue(self.m.step(Command(Op.EXPIRE, expired=True)).accepted)
        self.assertEqual(self.m.snapshot().customer_id, None)
        run(self.m, Command(Op.RESERVE), Command(Op.DEPOSIT, code="R-C1"))
        self.assertFalse(self.m.step(Command(Op.EXPIRE, expired=True)).accepted)   # OCCUPIED

    def test_maintenance(self):
        run(self.m, Command(Op.RESERVE))
        self.assertFalse(self.m.step(Command(Op.DISABLE)).accepted)       # assumption A2
        run(self.m, Command(Op.CANCEL))
        self.assertTrue(self.m.step(Command(Op.DISABLE)).accepted)
        self.assertEqual(self.m.state, State.MAINTENANCE)
        self.assertFalse(self.m.step(Command(Op.DISABLE)).accepted)
        self.assertTrue(self.m.step(Command(Op.ENABLE)).accepted)
        self.assertFalse(self.m.step(Command(Op.ENABLE)).accepted)

    def test_invalid_access_never_changes_state(self):
        for setup in ([], [Command(Op.RESERVE)], [Command(Op.RESERVE), Command(Op.DEPOSIT, code="R-C1")],
                      [Command(Op.DISABLE)]):
            m = LockerModel(); run(m, *setup)
            before = m.snapshot()
            r = m.step(Command(Op.INVALID_ACCESS, code="x"))
            self.assertFalse(r.accepted)
            self.assertEqual(m.snapshot(), before)


class TestCatalogue(unittest.TestCase):
    def test_counts_match_hand_derivation(self):
        # AVAILABLE 8 + RESERVED 10 + OCCUPIED 9 + MAINTENANCE 8, derived by hand from the rules
        self.assertEqual(len(transition_catalogue()), 35)
        self.assertEqual(len(set(transition_catalogue())), 35)
        # sum over states of (#incoming x #outgoing): 80 + 80 + 81 + 64
        self.assertEqual(len(transition_pairs()), 305)

    def test_every_op_has_a_default_rejection(self):
        self.assertEqual(set(DEFAULT_REJECTION), set(Op))

    def test_step_only_produces_catalogue_transitions_and_invariants_hold(self):
        """Exhaustive BFS over the alphabet: all 35 transitions reachable, none outside."""
        from locker.generators import candidate_commands
        cat = set(transition_catalogue())
        seen, frontier, visited = set(), [LockerModel()], set()
        for _ in range(6):
            nxt = []
            for m in frontier:
                for c in candidate_commands(m.snapshot(), ("C1", "C2"), near_miss=True):
                    k = m.peek(c)
                    self.assertIn(k, cat)
                    seen.add(k)
                    n = m.clone(); n.step(c)
                    self.assertEqual(check_snapshot_invariants(n.snapshot()), [])
                    sig = (n.snapshot().state, n.snapshot().customer_id)
                    if sig not in visited:
                        visited.add(sig); nxt.append(n)
            frontier = nxt
        self.assertEqual(seen, cat)

    def test_peek_does_not_mutate(self):
        m = LockerModel()
        m.peek(Command(Op.RESERVE))
        self.assertEqual(m.state, State.AVAILABLE)


if __name__ == "__main__":
    unittest.main()
