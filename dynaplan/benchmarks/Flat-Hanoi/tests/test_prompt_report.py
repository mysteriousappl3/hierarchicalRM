import unittest

from flat_hanoi.evaluate import evaluate_response
from flat_hanoi.model import Instance
from flat_hanoi.prompt import render_messages, render_prompt
from flat_hanoi.report import summarize


def sample_instance():
    return Instance(1, "sample", 3, (1, 2, 0), (2, 0, 1), 3, "test", 1)


class PromptTests(unittest.TestCase):
    def test_prompt_states_numeric_conventions(self):
        prompt = render_prompt(sample_instance())
        self.assertIn("disk 1 is the smallest", prompt)
        self.assertIn("Pegs are numbered 0, 1, and 2", prompt)
        self.assertIn("[disk_id, source_peg, destination_peg]", prompt)

    def test_prompt_shows_arbitrary_stacks_bottom_to_top(self):
        prompt = render_prompt(sample_instance())
        self.assertIn("Peg 0: [3]", prompt)
        self.assertIn("Peg 1: [1]", prompt)
        self.assertIn("Peg 2: [2]", prompt)

    def test_prompt_contains_correct_classic_demo(self):
        prompt = render_prompt(sample_instance())
        expected = "[[1, 0, 2], [2, 0, 1], [1, 2, 1], [3, 0, 2]"
        self.assertIn(expected, prompt)

    def test_prompt_requests_shortest_solution_and_final_assignment(self):
        prompt = render_prompt(sample_instance())
        self.assertIn("shortest legal solution", prompt)
        self.assertIn("End with exactly one final assignment", prompt)

    def test_prompt_preserves_system_and_user_roles(self):
        messages = render_messages(sample_instance())
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        self.assertIn("Legal-move rules", messages[0]["content"])
        self.assertIn("initial configuration", messages[1]["content"])
        self.assertIn("goal configuration", messages[1]["content"])
        self.assertIn("only one top disk", messages[1]["content"])
        self.assertIn("never put a larger disk", messages[1]["content"])

    def test_system_requests_complete_lists_for_reasoned_candidates(self):
        system = render_messages(sample_instance())[0]["content"]
        self.assertIn("every candidate solution", system)
        self.assertIn("complete move list", system)

    def test_text_prompt_is_explicitly_a_labeled_preview(self):
        prompt = render_prompt(sample_instance())
        self.assertTrue(prompt.startswith("SYSTEM MESSAGE\n"))
        self.assertIn("\n\nUSER MESSAGE\n", prompt)


class ReportTests(unittest.TestCase):
    def test_all_rows_remain_in_denominator(self):
        rows = [
            {"classification": "optimal", "n": 3, "parseable": True, "legal": True},
            {"classification": "suboptimal", "n": 3, "parseable": True, "legal": True},
            {"classification": "incorrect", "n": 3, "parseable": True, "legal": True},
            {"classification": "illegal", "n": 3, "parseable": False, "legal": False},
        ]
        result = summarize(rows)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["optimal_accuracy"], 0.25)
        self.assertEqual(result["goal_reaching_rate"], 0.5)
        self.assertEqual(result["parseable_rate"], 0.75)
        self.assertEqual(result["legal_response_rate"], 0.75)

    def test_usage_is_summed_not_averaged(self):
        result = summarize([
            {"classification": "illegal", "input_tokens": 2, "total_tokens": 5},
            {"classification": "illegal", "input_tokens": 7, "total_tokens": 11},
        ])
        self.assertEqual(result["usage_totals"], {"input_tokens": 9, "total_tokens": 16})

    def test_empty_summary_is_well_defined(self):
        result = summarize([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["optimal_accuracy"], 0.0)


if __name__ == "__main__":
    unittest.main()
