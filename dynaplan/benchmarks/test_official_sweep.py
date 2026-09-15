from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import benchmark
import official_sweep


def test_frozen_sweep_has_three_tasks_per_stratum_and_720_conditions() -> None:
    spec = official_sweep._read_json(official_sweep.SPEC_PATH)
    official_sweep._validate_spec(spec)
    conditions = official_sweep._conditions(spec)

    assert len(conditions) == 720
    assert Counter(item["provider"] for item in conditions) == {
        "openai": 360,
        "anthropic": 360,
    }
    assert set(Counter(item["method"] for item in conditions).values()) == {90}
    assert Counter(item["benchmark"] for item in conditions) == {
        "flat-hanoi": 240,
        "logistics": 240,
        "blocksworld": 240,
    }


def test_claude_literature_command_keeps_manual_thinking_budget(
    tmp_path: Path,
) -> None:
    spec = official_sweep._read_json(official_sweep.SPEC_PATH)
    condition = next(
        item
        for item in official_sweep._conditions(spec)
        if item["provider"] == "anthropic" and item["method"] == "tdp"
    )
    command = official_sweep._condition_command(
        condition, tmp_path, 1, tmp_path / ".env"
    )

    assert command[command.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert command[command.index("--anthropic-thinking-budget") + 1] == "4096"
    assert command[command.index("--max-output-tokens") + 1] == "8192"


def test_official_parser_exposes_offline_report_mode() -> None:
    args = official_sweep.build_parser().parse_args(["--report"])
    assert args.report is True
    assert args.execute is False
    assert args.register is False


def test_unified_parser_allows_claude_for_literature_ports() -> None:
    parser = benchmark.build_parser()
    args = parser.parse_args(
        [
            "--provider",
            "anthropic",
            "--model",
            "claude-haiku-4-5-20251001",
            "--anthropic-thinking-budget",
            "4096",
            "--max-output-tokens",
            "8192",
            "--baseline",
            "all-literature",
        ]
    )
    benchmark._configure_runtime(args, parser)

    assert benchmark.PROVIDER == "anthropic"
    assert benchmark.ANTHROPIC_THINKING_BUDGET_TOKENS == 4096


def test_literature_anthropic_schema_adapter_matches_dynaplan_policy() -> None:
    model_path = (
        official_sweep.WORKSPACE_ROOT
        / "simmer-style-libero"
        / "benchmarking"
        / "models.py"
    )
    spec = importlib.util.spec_from_file_location("literature_models_test", model_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original = {
        "type": "object",
        "properties": {
            "index": {"type": "integer", "minimum": 0, "maximum": 9},
            "nodes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string", "pattern": "^node_"},
            },
            "verdict": {"type": "string", "enum": ["VALID", "INVALID"]},
            "control": {
                "type": ["string", "null"],
                "enum": ["sequence", "fallback", None],
            },
        },
    }

    adapted = module._anthropic_compatible_schema(original)

    assert adapted["properties"]["index"] == {
        "type": "integer",
        "description": "Post-generation validation requirement(s): maximum=9, minimum=0.",
    }
    assert adapted["properties"]["nodes"] == {
        "type": "array",
        "items": {
            "type": "string",
            "description": "Post-generation validation requirement(s): pattern='^node_'.",
        },
        "description": "Post-generation validation requirement(s): maxItems=3, minItems=1.",
    }
    assert adapted["properties"]["verdict"] == original["properties"]["verdict"]
    assert adapted["properties"]["control"] == {
        "anyOf": [
            {"type": "string", "enum": ["sequence", "fallback"]},
            {"type": "null", "enum": [None]},
        ]
    }
    assert original["properties"]["index"]["minimum"] == 0


def test_comparison_contract_is_byte_identical_across_runtimes() -> None:
    shared = (
        official_sweep.WORKSPACE_ROOT
        / "simmer-style-libero"
        / "benchmarking"
        / "comparison_protocol.py"
    )
    copied = (
        official_sweep.DYNAPLAN_ROOT
        / "baselines"
        / "dynaplan"
        / "runtime"
        / "comparison_protocol.py"
    )
    assert shared.read_bytes() == copied.read_bytes()


def test_all_three_public_prompts_contain_one_shared_semantic_contract() -> None:
    benchmark._ensure_shared_adapter_root()
    from comparison_protocol import (
        MINIMUM_ACTION_OBJECTIVE,
        common_semantics_contract,
        with_comparison_contract,
    )

    for domain in ("logistics", "blocksworld"):
        case = benchmark.prepare_lexicon_case(domain, 1, 1)
        native = benchmark._native_lexicon_task(case)
        assert case.user_prompt == with_comparison_contract(
            native.prompt_text(), domain
        )
        assert case.user_prompt.count(common_semantics_contract(domain)) == 1
        assert case.user_prompt.count(MINIMUM_ACTION_OBJECTIVE) == 1

    hanoi = benchmark.prepare_flat_hanoi_case("n3-0032")
    assert hanoi.user_prompt.count(common_semantics_contract("flat-hanoi")) == 1
    assert hanoi.user_prompt.count(MINIMUM_ACTION_OBJECTIVE) == 1
