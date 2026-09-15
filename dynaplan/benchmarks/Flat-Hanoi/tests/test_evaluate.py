import unittest

from flat_hanoi.evaluate import Classification, evaluate_moves, evaluate_response
from flat_hanoi.model import Instance
from flat_hanoi.oracle import shortest_path


def instance_two():
    return Instance(
        schema_version=1,
        instance_id="test-n2",
        n=2,
        start=(0, 0),
        goal=(2, 2),
        optimal_distance=3,
        sampling_profile="test",
        generator_seed=1,
    )


class EvaluationTests(unittest.TestCase):
    def test_optimal(self):
        result = evaluate_response(
            instance_two(),
            "moves = [[1,0,1],[2,0,2],[1,1,2]]",
        )
        self.assertEqual(result.classification, Classification.OPTIMAL)
        self.assertTrue(result.parseable)
        self.assertTrue(result.legal)
        self.assertTrue(result.valid)
        self.assertTrue(result.goal_reached)
        self.assertTrue(result.optimal)

    def test_suboptimal(self):
        moves = shortest_path((0, 0), (2, 2)) + [(1, 2, 0), (1, 0, 2)]
        result = evaluate_moves((0, 0), (2, 2), moves, 3)
        self.assertEqual(result.classification, Classification.SUBOPTIMAL)
        self.assertTrue(result.parseable)
        self.assertTrue(result.legal)
        self.assertTrue(result.goal_reached)
        self.assertFalse(result.optimal)

    def test_incorrect_but_legal(self):
        result = evaluate_response(instance_two(), "moves = []")
        self.assertEqual(result.classification, Classification.INCORRECT)
        self.assertTrue(result.parseable)
        self.assertTrue(result.legal)
        self.assertFalse(result.goal_reached)

    def test_illegal_move_is_parseable_but_not_legal(self):
        result = evaluate_response(instance_two(), "moves = [[2, 0, 2]]")
        self.assertEqual(result.classification, Classification.ILLEGAL)
        self.assertTrue(result.parseable)
        self.assertFalse(result.legal)
        self.assertFalse(result.valid)
        self.assertEqual(result.first_failure_index, 1)
        self.assertEqual(result.failure_code, "not_top_disk")
        self.assertEqual(result.legal_prefix_length, 0)

    def test_unparseable_is_illegal_and_not_parseable(self):
        result = evaluate_response(instance_two(), "I could not solve this")
        self.assertEqual(result.classification, Classification.ILLEGAL)
        self.assertFalse(result.parseable)
        self.assertFalse(result.legal)
        self.assertIsNone(result.submitted_length)
        self.assertEqual(result.failure_code, "missing_assignment")

    def test_wrong_asserted_disk_is_not_silently_inferred(self):
        result = evaluate_response(instance_two(), "moves = [[2,0,1],[1,0,2]]")
        self.assertEqual(result.classification, Classification.ILLEGAL)
        self.assertEqual(result.failure_code, "not_top_disk")

    def test_out_of_range_peg_is_illegal_not_parse_failure(self):
        result = evaluate_response(instance_two(), "moves = [[1,0,3]]")
        self.assertTrue(result.parseable)
        self.assertFalse(result.legal)
        self.assertEqual(result.failure_code, "peg_out_of_range")

    def test_reaching_goal_then_leaving_is_incorrect(self):
        moves = shortest_path((0, 0), (2, 2)) + [(1, 2, 0)]
        result = evaluate_moves((0, 0), (2, 2), moves, 3)
        self.assertEqual(result.classification, Classification.INCORRECT)
        self.assertTrue(result.legal)
        self.assertFalse(result.goal_reached)

    def test_stored_oracle_mismatch_is_an_error(self):
        with self.assertRaises(ValueError):
            evaluate_moves((0, 0), (2, 2), shortest_path((0, 0), (2, 2)), 4)

    def test_zero_move_identical_state_supported_by_low_level_evaluator(self):
        result = evaluate_moves((0, 1), (0, 1), [], 0)
        self.assertEqual(result.classification, Classification.OPTIMAL)

    def test_result_serialization_has_independent_booleans(self):
        row = evaluate_response(instance_two(), "moves=[]").to_dict()
        for key in ("parseable", "legal", "valid", "goal_reached", "optimal"):
            self.assertIn(key, row)
        self.assertEqual(row["final_state"], [0, 0])

    def test_pathological_literal_remains_an_illegal_attempt(self):
        result = evaluate_response(instance_two(), "moves=" + "[" * 500 + "]" * 500)
        self.assertEqual(result.classification, Classification.ILLEGAL)
        self.assertFalse(result.parseable)
        self.assertEqual(result.failure_code, "excessive_nesting")


if __name__ == "__main__":
    unittest.main()
