from __future__ import annotations

import benchmark
from hanoi_benchmark import aggregate_token_usage


def _local_record(*, truncated: bool = False):
    return {
        "provider": "local-transformers",
        "model": "Qwen/Qwen3.5-4B",
        "stage": "direct",
        "system": "system",
        "max_tokens": 32,
        "reasoning_effort": "none",
        "prompt_char_count": 6,
        "output_char_count": 2,
        "reasoning_char_count": 0,
        "reasoning_content": None,
        "response_schema_name": None,
        "usage": {
            "usage_source": "local_exact",
            "input_tokens": 5,
            "cached_input_tokens": 0,
            "output_tokens": 2,
            "reasoning_tokens": 0,
            "total_tokens": 7,
        },
        "raw_usage": {"input_tokens": 5, "generated_tokens": 2},
        "thinking_budget_tokens": None,
        "truncated": truncated,
        "finish_reason": "length" if truncated else "eos_token",
        "backend_metadata": {
            "model_class": "Qwen3_5ForCausalLM",
            "text_only": True,
            "load_in_4bit": True,
        },
    }


def test_local_usage_is_exact_but_not_mislabeled_as_api() -> None:
    usage = aggregate_token_usage([_local_record()])

    assert usage["call_count"] == 1
    assert usage["local_exact_usage_call_count"] == 1
    assert usage["api_usage_call_count"] == 0
    assert usage["missing_usage_call_count"] == 0
    assert usage["total_tokens"] == 7


def test_local_vllm_has_zero_api_cost() -> None:
    assert benchmark._estimated_cost_usd("local-vllm", "qwen35-9b", {}) == 0.0


def test_unified_direct_local_response_preserves_runtime_attestation(
    monkeypatch,
) -> None:
    class FakeClient:
        def generate(self, **_kwargs):
            return "OK"

        def call_records_since(self, _index):
            return [_local_record()]

    monkeypatch.setattr(benchmark, "PROVIDER", "local-transformers")
    monkeypatch.setattr(benchmark, "MODEL", "Qwen/Qwen3.5-4B")
    monkeypatch.setattr(benchmark, "_shared_model_client", lambda: FakeClient())

    response = benchmark.call_model(
        system_prompt="system",
        user_prompt="prompt",
        max_output_tokens=32,
        timeout_seconds=10,
    )

    assert response.text == "OK"
    assert response.usage["total_tokens"] == 7
    assert response.backend_metadata == {
        "model_class": "Qwen3_5ForCausalLM",
        "text_only": True,
        "load_in_4bit": True,
    }
    assert response.finish_reason == "stop"
