import unittest

from flat_hanoi.parse import ParseError, parse_moves


class ParseTests(unittest.TestCase):
    def test_parses_strict_moves(self):
        self.assertEqual(parse_moves("moves = [[1, 0, 2], [2, 0, 1]]"), [(1, 0, 2), (2, 0, 1)])

    def test_empty_list_is_parseable(self):
        self.assertEqual(parse_moves("moves=[]"), [])

    def test_reasoning_and_code_fence_are_allowed(self):
        text = "Reasoning...\n```python\nmoves = [ [1,0,2] ]\n```"
        self.assertEqual(parse_moves(text), [(1, 0, 2)])

    def test_final_assignment_wins(self):
        text = "moves = [[9, 9, 9]]\nI revise this.\nmoves = [[1, 0, 2]]"
        self.assertEqual(parse_moves(text), [(1, 0, 2)])

    def test_malformed_final_assignment_invalidates_earlier_draft(self):
        text = "moves = [[1, 0, 2]]\nActually:\nmoves = [[1, 0"
        with self.assertRaises(ParseError) as caught:
            parse_moves(text)
        self.assertEqual(caught.exception.code, "unbalanced_list")

    def test_missing_assignment(self):
        with self.assertRaises(ParseError) as caught:
            parse_moves("[[1, 0, 2]]")
        self.assertEqual(caught.exception.code, "missing_assignment")

    def test_assignment_requires_list(self):
        with self.assertRaises(ParseError) as caught:
            parse_moves("moves = (1, 0, 2)")
        self.assertEqual(caught.exception.code, "missing_list")

    def test_outer_tuple_rejected(self):
        with self.assertRaises(ParseError):
            parse_moves("moves = ([1, 0, 2],)")

    def test_inner_tuple_rejected(self):
        with self.assertRaises(ParseError) as caught:
            parse_moves("moves = [(1, 0, 2)]")
        self.assertEqual(caught.exception.code, "invalid_move_shape")

    def test_wrong_arity_rejected(self):
        for answer in ("moves = [[1, 0]]", "moves = [[1, 0, 2, 1]]"):
            with self.subTest(answer=answer), self.assertRaises(ParseError):
                parse_moves(answer)

    def test_noninteger_fields_rejected_without_coercion(self):
        answers = [
            'moves = [["1", 0, 2]]',
            "moves = [[1.0, 0, 2]]",
            "moves = [[True, 0, 2]]",
            "moves = [[None, 0, 2]]",
        ]
        for answer in answers:
            with self.subTest(answer=answer), self.assertRaises(ParseError) as caught:
                parse_moves(answer)
            self.assertEqual(caught.exception.code, "invalid_move_type")

    def test_brackets_inside_strings_do_not_break_balancing(self):
        with self.assertRaises(ParseError) as caught:
            parse_moves('moves = [["[ignored]", 0, 2]] trailing ]')
        self.assertEqual(caught.exception.code, "invalid_move_type")

    def test_python_comments_are_removed_semantically(self):
        answer = "moves = [\n [1, 0, 2], # first ] bracket in comment\n [2, 0, 1] # note\n]"
        self.assertEqual(parse_moves(answer), [(1, 0, 2), (2, 0, 1)])

    def test_assignment_text_inside_comment_cannot_hijack_final_answer(self):
        answer = "moves = [[1,0,2]] # note moves = [[2,0,1]]"
        self.assertEqual(parse_moves(answer), [(1, 0, 2)])

    def test_assignment_text_inside_list_comment_cannot_hijack_answer(self):
        answer = "moves = [\n [1,0,2], # note moves = [[3,2,1]]\n [2,0,1]\n]"
        self.assertEqual(parse_moves(answer), [(1, 0, 2), (2, 0, 1)])

    def test_assignment_text_inside_quote_cannot_hijack_final_answer(self):
        answer = 'moves = [[1,0,2]]\nThe literal text "moves = [[2,0,1]]" is only commentary.'
        self.assertEqual(parse_moves(answer), [(1, 0, 2)])

    def test_prose_apostrophe_does_not_hide_later_assignment(self):
        answer = "The candidate's path works. moves = [[1,0,2]]"
        self.assertEqual(parse_moves(answer), [(1, 0, 2)])

    def test_plural_possessive_does_not_hide_later_assignment(self):
        answer = "The disks' positions are checked. moves = [[1,0,2]]"
        self.assertEqual(parse_moves(answer), [(1, 0, 2)])

    def test_unmatched_prose_quote_does_not_hide_later_assignment(self):
        answer = 'An unmatched " mark appears here. moves = [[1,0,2]]'
        self.assertEqual(parse_moves(answer), [(1, 0, 2)])

    def test_pathological_nesting_is_a_parse_error_not_a_crash(self):
        with self.assertRaises(ParseError) as caught:
            parse_moves("moves=" + "[" * 500 + "]" * 500)
        self.assertEqual(caught.exception.code, "excessive_nesting")

    def test_case_insensitive_assignment(self):
        self.assertEqual(parse_moves("MOVES = [[1, 0, 2]]"), [(1, 0, 2)])


if __name__ == "__main__":
    unittest.main()
