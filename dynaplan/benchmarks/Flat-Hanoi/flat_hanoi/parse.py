"""Strict extraction of the final ``moves = [...]`` answer block."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import List

from .model import Move

_MOVES_ASSIGNMENT = re.compile(r"\bmoves\s*=", re.IGNORECASE)


@dataclass
class ParseError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _balanced_list(text: str, start: int) -> str:
    if start >= len(text) or text[start] != "[":
        raise ParseError("missing_list", "the final moves assignment is not followed by a list")
    depth = 0
    quote = None
    escaped = False
    comment = False
    for index in range(start, len(text)):
        character = text[index]
        if comment:
            if character in ("\n", "\r"):
                comment = False
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ("'", '\"'):
            quote = character
        elif character == "#":
            # The predecessor protocol tolerated Python-style annotations in
            # candidate lists. ast.literal_eval also accepts these comments;
            # ignoring their brackets here prevents a comment from breaking
            # balanced-list extraction.
            comment = True
        elif character == "[":
            depth += 1
            if depth > 64:
                raise ParseError("excessive_nesting", "the final moves list is nested too deeply")
        elif character == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
            if depth < 0:
                break
    raise ParseError("unbalanced_list", "the final moves list is truncated or unbalanced")


def _assignments_outside_comments_and_strings(text: str) -> List[re.Match]:
    """Find assignments while ignoring Python-style comments and quoted text."""

    matches = []
    index = 0
    quote = None
    triple = False
    escaped = False
    comment = False
    while index < len(text):
        character = text[index]
        if comment:
            if character in ("\n", "\r"):
                comment = False
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
                index += 1
                continue
            if character == "\\":
                escaped = True
                index += 1
                continue
            if triple and text.startswith(quote * 3, index):
                index += 3
                quote = None
                triple = False
                continue
            if not triple and character == quote:
                quote = None
            index += 1
            continue
        if character == "#":
            comment = True
            index += 1
            continue
        if character in ("'", '\"'):
            # Treat an apostrophe between word characters as prose punctuation,
            # not the start of a Python-style quoted string. This also covers a
            # plural possessive such as ``disks' positions``.
            if character == "'" and index > 0 and text[index - 1].isalnum():
                index += 1
                continue
            candidate_triple = text.startswith(character * 3, index)
            closing = character * 3 if candidate_triple else character
            line_end = len(text) if candidate_triple else min(
                [position for position in (
                    text.find("\n", index + 1), text.find("\r", index + 1)
                ) if position != -1] or [len(text)]
            )
            search_start = index + (3 if candidate_triple else 1)
            closing_index = text.find(closing, search_start, None if candidate_triple else line_end)
            # An unmatched prose quote must not swallow a later real assignment.
            if closing_index == -1:
                index += 1
                continue
            quote = character
            triple = candidate_triple
            index += 3 if triple else 1
            continue
        match = _MOVES_ASSIGNMENT.match(text, index)
        if match is not None:
            matches.append(match)
            index = match.end()
            continue
        index += 1
    return matches


def parse_moves(response: str) -> List[Move]:
    """Parse only the last moves assignment and require strict integer triples."""

    if not isinstance(response, str):
        raise ParseError("not_text", "model response must be text")
    assignments = _assignments_outside_comments_and_strings(response)
    if not assignments:
        raise ParseError("missing_assignment", "no moves = [...] assignment was found")
    final = assignments[-1]
    list_start = final.end()
    while list_start < len(response) and response[list_start].isspace():
        list_start += 1
    literal = _balanced_list(response, list_start)
    try:
        value = ast.literal_eval(literal)
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError) as exc:
        raise ParseError("invalid_literal", "the final moves block is not a Python-style list") from exc
    if type(value) is not list:
        raise ParseError("outer_not_list", "moves must be an outer list")
    parsed: List[Move] = []
    for index, move in enumerate(value, start=1):
        if type(move) is not list or len(move) != 3:
            raise ParseError(
                "invalid_move_shape",
                "move {} must be a three-element list".format(index),
            )
        if any(type(field) is not int for field in move):
            raise ParseError(
                "invalid_move_type",
                "move {} fields must be integers".format(index),
            )
        parsed.append((move[0], move[1], move[2]))
    return parsed
