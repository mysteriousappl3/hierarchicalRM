import unittest

from flat_hanoi.model import (
    Instance,
    index_to_state,
    is_strict_flat,
    peg_stacks,
    state_to_index,
    validate_move_shape,
    validate_state,
)
from flat_hanoi.state import IllegalMove, apply_move, neighbors, replay, top_disks


class ModelTests(unittest.TestCase):
    def test_state_is_smallest_disk_first(self):
        self.assertEqual(validate_state([1, 2, 0]), (1, 2, 0))

    def test_rejects_empty_state(self):
        with self.assertRaises(ValueError):
            validate_state([])

    def test_rejects_bad_peg(self):
        with self.assertRaises(ValueError):
            validate_state((0, 3))

    def test_rejects_bool_peg(self):
        with self.assertRaises(ValueError):
            validate_state((False, 1))

    def test_rejects_wrong_n(self):
        with self.assertRaises(ValueError):
            validate_state((0, 1), 3)

    def test_exact_move_shape(self):
        self.assertEqual(validate_move_shape([1, 0, 2]), (1, 0, 2))
        for bad in ([1, 0], [1, 0, 2, 2], [True, 0, 2], [1.0, 0, 2]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_move_shape(bad)

    def test_index_round_trip_and_cardinality(self):
        for n in range(1, 6):
            states = [index_to_state(index, n) for index in range(3 ** n)]
            self.assertEqual(len(set(states)), 3 ** n)
            self.assertEqual([state_to_index(state) for state in states], list(range(3 ** n)))

    def test_index_validation(self):
        for index, n in ((-1, 3), (27, 3), (0, 0), (True, 2)):
            with self.subTest(index=index, n=n), self.assertRaises(ValueError):
                index_to_state(index, n)

    def test_stack_display_is_bottom_to_top(self):
        self.assertEqual(peg_stacks((1, 2, 0, 0)), ((4, 3), (1,), (2,)))

    def test_strict_flat(self):
        self.assertFalse(is_strict_flat((0, 0, 0)))
        self.assertTrue(is_strict_flat((0, 1, 0)))

    def test_schema_version_rejects_boolean(self):
        with self.assertRaises(ValueError):
            Instance(True, "bad", 2, (0, 0), (1, 1), 3, "test", 1)


class TransitionTests(unittest.TestCase):
    def assert_illegal(self, state, move, code):
        with self.assertRaises(IllegalMove) as caught:
            apply_move(state, move)
        self.assertEqual(caught.exception.code, code)

    def test_top_disks(self):
        self.assertEqual(top_disks((1, 2, 0, 0)), (3, 1, 2))

    def test_legal_move(self):
        self.assertEqual(apply_move((0, 0, 0), (1, 0, 2)), (2, 0, 0))

    def test_wrong_source(self):
        self.assert_illegal((0, 0), (1, 1, 2), "wrong_source")

    def test_asserted_disk_must_be_top(self):
        self.assert_illegal((0, 0), (2, 0, 1), "not_top_disk")

    def test_larger_cannot_land_on_smaller(self):
        self.assert_illegal((1, 0), (2, 0, 1), "larger_on_smaller")

    def test_same_source_and_destination(self):
        self.assert_illegal((0, 0), (1, 0, 0), "same_peg")

    def test_disk_range(self):
        self.assert_illegal((0, 0), (3, 0, 1), "disk_out_of_range")

    def test_peg_range(self):
        self.assert_illegal((0, 0), (1, 0, 3), "peg_out_of_range")

    def test_malformed_move(self):
        self.assert_illegal((0, 0), (1, 0), "malformed_move")

    def test_neighbors_are_legal_unique_and_reversible(self):
        for n in range(1, 5):
            for index in range(3 ** n):
                state = index_to_state(index, n)
                outgoing = list(neighbors(state))
                self.assertEqual(len({following for _, following in outgoing}), len(outgoing))
                for move, following in outgoing:
                    self.assertEqual(apply_move(state, move), following)
                    reverse = (move[0], move[2], move[1])
                    self.assertEqual(apply_move(following, reverse), state)

    def test_neighbor_order_is_stable(self):
        self.assertEqual(
            [move for move, _ in neighbors((0, 0, 0))],
            [(1, 0, 1), (1, 0, 2)],
        )

    def test_replay(self):
        moves = [(1, 0, 1), (2, 0, 2), (1, 1, 2)]
        self.assertEqual(replay((0, 0), moves), (2, 2))


if __name__ == "__main__":
    unittest.main()
