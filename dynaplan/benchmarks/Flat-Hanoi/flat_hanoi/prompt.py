"""A paper-style, flat-state-aware prompt renderer."""

from __future__ import annotations

from importlib import resources
from typing import Dict, List

from .model import Instance, State, peg_stacks


def _format_stacks(state: State) -> str:
    lines: List[str] = []
    for peg, stack in enumerate(peg_stacks(state)):
        contents = ", ".join(str(disk) for disk in stack)
        lines.append("  Peg {}: [{}]".format(peg, contents))
    return "\n".join(lines)


def render_messages(instance: Instance) -> List[Dict[str, str]]:
    """Render distinct system and user messages for an API runner.

    These are paraphrased adaptations of the two-role protocol described by the
    paper. They do not claim to reproduce unpublished exact prompt text.
    """

    system_template = resources.read_text(
        "flat_hanoi", "paper_derived_system_v1.txt", encoding="utf-8"
    )
    user_template = resources.read_text(
        "flat_hanoi", "paper_derived_user_v1.txt", encoding="utf-8"
    )
    values = {
        "n": instance.n,
        "start_stacks": _format_stacks(instance.start),
        "goal_stacks": _format_stacks(instance.goal),
    }
    return [
        {"role": "system", "content": system_template.format(**values)},
        {"role": "user", "content": user_template.format(**values)},
    ]


def render_prompt(instance: Instance) -> str:
    """Render a labeled text preview; API runners should use render_messages."""

    messages = render_messages(instance)
    return "SYSTEM MESSAGE\n{}\n\nUSER MESSAGE\n{}".format(
        messages[0]["content"], messages[1]["content"]
    )
