import unittest
from locker.sut import ParcelLocker
from locker.types import Command, Operation, State

class TestReferenceSUT(unittest.TestCase):
    def test_reserve_deposit_retrieve_lifecycle(self):
        sut = ParcelLocker()
        self.assertTrue(sut.execute(Command(Operation.RESERVE, customer_id="C7")).accepted)
        self.assertEqual(sut.snapshot().state, State.RESERVED)
        self.assertTrue(sut.execute(Command(Operation.DEPOSIT, code="R-C7")).accepted)
        self.assertEqual(sut.snapshot().state, State.OCCUPIED)
        self.assertTrue(sut.execute(Command(Operation.RETRIEVE, code="P-C7")).accepted)
        self.assertEqual(sut.snapshot().state, State.AVAILABLE)

    def test_wrong_code_does_not_change_state(self):
        sut = ParcelLocker()
        sut.execute(Command(Operation.RESERVE, customer_id="C9"))
        before = sut.snapshot()
        self.assertFalse(sut.execute(Command(Operation.DEPOSIT, code="WRONG")).accepted)
        self.assertEqual(sut.snapshot(), before)

    def test_maintenance_lifecycle(self):
        sut = ParcelLocker()
        self.assertTrue(sut.execute(Command(Operation.DISABLE)).accepted)
        self.assertEqual(sut.snapshot().state, State.MAINTENANCE)
        self.assertTrue(sut.execute(Command(Operation.ENABLE)).accepted)
        self.assertEqual(sut.snapshot().state, State.AVAILABLE)

if __name__ == "__main__":
    unittest.main()
