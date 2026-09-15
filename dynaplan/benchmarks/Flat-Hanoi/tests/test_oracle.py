import unittest
from collections import deque

from flat_hanoi.model import index_to_state
from flat_hanoi.oracle import shortest_distance, shortest_path
from flat_hanoi.state import neighbors, replay


class OracleTests(unittest.TestCase):
    def test_identical_endpoints_need_no_moves(self):
        self.assertEqual(shortest_path((0, 1, 2), (0, 1, 2)), [])

    def test_classic_tower_distances(self):
        for n in range(1, 8):
            with self.subTest(n=n):
                self.assertEqual(shortest_distance((0,) * n, (2,) * n), 2 ** n - 1)

    def test_path_reaches_goal(self):
        cases = [
            ((0, 1, 2), (2, 0, 1)),
            ((1, 2, 0, 0), (2, 1, 1, 0)),
            ((0, 2, 1, 0, 2), (1, 0, 2, 2, 1)),
        ]
        for start, goal in cases:
            with self.subTest(start=start, goal=goal):
                path = shortest_path(start, goal)
                self.assertEqual(replay(start, path), goal)
                self.assertEqual(len(path), shortest_distance(start, goal))

    def test_path_choice_is_deterministic(self):
        start, goal = (0, 1, 2, 0), (2, 0, 1, 2)
        self.assertEqual(shortest_path(start, goal), shortest_path(start, goal))

    def test_goal_dimension_must_match(self):
        with self.assertRaises(ValueError):
            shortest_path((0, 0), (1, 1, 1))

    def test_every_state_connected_for_n_up_to_five(self):
        for n in range(1, 6):
            start = (0,) * n
            reached = {start}
            queue = deque([start])
            while queue:
                state = queue.popleft()
                for _, following in neighbors(state):
                    if following not in reached:
                        reached.add(following)
                        queue.append(following)
            self.assertEqual(len(reached), 3 ** n)
            self.assertEqual(reached, {index_to_state(index, n) for index in range(3 ** n)})


if __name__ == "__main__":
    unittest.main()

