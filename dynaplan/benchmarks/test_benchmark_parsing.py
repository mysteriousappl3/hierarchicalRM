from __future__ import annotations

from pathlib import Path

import pytest

import benchmark


def test_runs_md_hanoi_ids_are_accepted_as_cli_aliases() -> None:
    expected = ("paper-baseline-v1-n3-0017", 3)
    assert benchmark._resolve_hanoi_alias("n3-0017") == expected
    assert benchmark._resolve_hanoi_alias("3n-0017") == expected


def test_registered_reactree_protocol_matches_pinned_depth_and_keeps_budgets() -> None:
    config = benchmark._baseline_config("reactree")

    # max_depth=3 remains the shared AdaPlan-H/ADaPT setting; ReAcTree has its
    # own upstream-matched depth key and independent finite runtime budgets.
    assert config["max_depth"] == 3
    assert config["reactree_max_depth"] == 20
    assert config["reactree_max_model_calls"] == 96
    assert config["reactree_max_decisions"] == 96
    assert config["reactree_max_actions"] == 64
    assert benchmark.EXPECTED_ARCHITECTURES["logistics"]["reactree"] == (
        "reactree_lexicon_v3"
    )
    assert benchmark.EXPECTED_ARCHITECTURES["blocksworld"]["reactree"] == (
        "reactree_lexicon_blocksworld_v2"
    )
    assert benchmark.EXPECTED_ARCHITECTURES["flat-hanoi"]["reactree"] == (
        "reactree_flat_hanoi_v2"
    )

    source = benchmark._baseline_source_status(
        "reactree", require_fast_downward=False
    )
    assert source["verified"] is True
    assert source["upstream_default_config_matches"] is True
    assert source["upstream_default_config"] == {
        "max_depth": 20,
        "max_steps": 49,
        "max_decisions": 99,
    }


def test_flat_hanoi_direct_and_ports_share_fair_prompt_contract() -> None:
    case = benchmark.prepare_flat_hanoi_case("3_00")
    benchmark._ensure_shared_adapter_root()
    from comparison_protocol import (
        FLAT_HANOI_ACTION_REPRESENTATION,
        FLAT_HANOI_SHARED_SOLVED_EXAMPLE,
        MINIMUM_ACTION_OBJECTIVE,
        flat_hanoi_direct_prompt,
    )
    from flat_hanoi_baseline_core import public_problem_text

    native_problem = public_problem_text(benchmark._native_flat_task(case))
    combined_direct_prompt = case.system_prompt + "\n" + case.user_prompt

    assert case.user_prompt == flat_hanoi_direct_prompt(native_problem)
    assert combined_direct_prompt.count(MINIMUM_ACTION_OBJECTIVE) == 1
    assert case.user_prompt.count(FLAT_HANOI_SHARED_SOLVED_EXAMPLE) == 1
    assert FLAT_HANOI_ACTION_REPRESENTATION in case.user_prompt
    assert "[disk_id, source_peg, destination_peg]" not in case.user_prompt
    assert case.metadata["paper_derived_reference_prompt"]["role"].startswith(
        "frozen reconstruction reference only"
    )


def test_flat_hanoi_named_action_adapter_is_semantic_not_search_based() -> None:
    case = benchmark.prepare_flat_hanoi_case("3_00")
    instance = benchmark._load_flat_instance(case)
    source = instance.start[0]
    targets = [peg for peg in (0, 1, 2) if peg != source]
    target = targets[0]

    normalized, warning = benchmark._flat_candidate_as_numeric(
        case, f"MoveHoop(peg_{source}, peg_{target})"
    )

    assert normalized == f"moves = [[1, {source}, {target}]]"
    assert warning is None


def test_direct_flat_run_uses_shared_named_actions_and_numeric_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = benchmark.prepare_flat_hanoi_case("3_00")
    instance = benchmark._load_flat_instance(case)
    _read, _validate, _render, evaluation_tools = benchmark._load_flat_hanoi_modules()
    _evaluate_response, shortest_path = evaluation_tools
    oracle = shortest_path(instance.start, instance.goal)
    named_plan = "\n".join(
        f"MoveHoop(peg_{source}, peg_{target})"
        for _disk, source, target in oracle
    )

    monkeypatch.setattr(
        benchmark,
        "call_model",
        lambda **_kwargs: benchmark.ModelResponse(
            text=named_plan,
            finish_reason="stop",
            response_id="test-response",
            request_id="test-request",
            returned_model="test-model",
            usage={
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "uncached_input_tokens": 1,
                "output_tokens": 1,
                "reasoning_tokens": 0,
                "total_tokens": 2,
            },
            raw_usage={},
            reasoning_char_count=0,
            runtime_seconds=0.0,
        ),
    )

    result = benchmark._run_case(
        case,
        campaign_dir=tmp_path,
        max_output_tokens=128,
        timeout_seconds=10,
    )

    assert result["status"] == "OPTIMAL"
    assert result["success"] is True
    assert result["optimal"] is True
    assert result["action_conversion_warning"] is None
    assert (tmp_path / "flat-hanoi" / "normalized_candidate.txt").read_text(
        encoding="utf-8"
    ).startswith("moves = [[")


def test_exact_bare_fenced_plan_is_format_adherent() -> None:
    actions, metadata = benchmark._parse_lexicon_response_with_format(
        "```\npickup block_1\nputdown block_1\n```\n"
    )

    assert actions == [
        ("pickup", ("block_1",)),
        ("putdown", ("block_1",)),
    ]
    assert metadata["format_adherent"] is True
    assert metadata["format_issues"] == []
    assert metadata["plan_extraction"] == "official_first_fenced_block"


def test_official_extraction_scores_plan_despite_surrounding_prose() -> None:
    actions, metadata = benchmark._parse_lexicon_response_with_format(
        "I reasoned about the task.\n\n```\npickup block_1\n```\nDone."
    )

    assert actions == [("pickup", ("block_1",))]
    assert metadata["format_adherent"] is False
    assert metadata["format_issues"] == [
        "prose_before_plan",
        "prose_after_plan",
    ]


def test_official_extraction_uses_first_fenced_block() -> None:
    actions, metadata = benchmark._parse_lexicon_response_with_format(
        "```text\npickup block_1\n```\n```\nputdown block_1\n```"
    )

    assert actions == [("pickup", ("block_1",))]
    assert metadata["format_adherent"] is False
    assert "opening_fence_not_bare" in metadata["format_issues"]
    assert "prose_after_plan" in metadata["format_issues"]
    assert "additional_fence_delimiters" in metadata["format_issues"]


def test_missing_opening_fence_is_a_plan_format_error() -> None:
    with pytest.raises(
        benchmark.RunnerError, match="does not contain a fenced action block"
    ):
        benchmark._parse_lexicon_response_with_format("pickup block_1")


def test_missing_closing_fence_matches_released_eof_extraction() -> None:
    actions, metadata = benchmark._parse_lexicon_response_with_format(
        "```\npickup block_1"
    )

    assert actions == [("pickup", ("block_1",))]
    assert metadata["format_adherent"] is False
    assert "missing_closing_fence" in metadata["format_issues"]
    assert metadata["closing_fence_line"] is None


def _tiny_lexicon_scorer(tmp_path: Path):
    domain = tmp_path / "domain.pddl"
    problem = tmp_path / "problem.pddl"
    domain.write_text(
        """
(define (domain tiny)
  (:requirements :strips :typing)
  (:types item)
  (:predicates (ready ?x - item) (done ?x - item))
  (:action finish
    :parameters (?x - item)
    :precondition (ready ?x)
    :effect (and (done ?x) (not (ready ?x)))))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    problem.write_text(
        """
(define (problem tiny-1)
  (:domain tiny)
  (:objects i - item)
  (:init (ready i))
  (:goal (done i)))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return benchmark._make_lexicon_scorer(domain, problem, optimum=1)


def test_format_diagnostic_does_not_gate_semantic_success(tmp_path: Path) -> None:
    result = _tiny_lexicon_scorer(tmp_path)(
        "Reasoning that the released parser ignores.\n```\nfinish i\n```"
    )

    assert result["status"] == "OPTIMAL"
    assert result["valid"] is True
    assert result["optimal"] is True
    assert result["format_adherent"] is False
    assert result["format_issues"] == ["prose_before_plan"]


def test_semantic_failure_retains_format_metadata(tmp_path: Path) -> None:
    result = _tiny_lexicon_scorer(tmp_path)(
        "Reasoning.\n```\nfinish i\nfinish i\n```"
    )

    assert result["status"] == "INVALID"
    assert result["failure_kind"] == "action_precondition"
    assert result["first_failed_action_index"] == 2
    assert result["format_adherent"] is False
    assert result["format_issues"] == ["prose_before_plan"]


def test_malformed_action_retains_independent_envelope_metadata(
    tmp_path: Path,
) -> None:
    result = _tiny_lexicon_scorer(tmp_path)(
        "Reasoning.\n```\nfinish i\nnot-an-action(\n```"
    )

    assert result["status"] == "INVALID"
    assert result["failure_kind"] == "plan_format"
    assert result["format_adherent"] is False
    assert result["format_issues"] == ["prose_before_plan"]
