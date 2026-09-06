from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from models import AnthropicClient, GeminiClient, OpenAICompatibleClient, build_local_extra_options, create_client


class StructuredModelOutputTest(unittest.TestCase):
    def test_openai_adapter_sends_strict_json_schema(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        response = {
            "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            "usage": {},
        }
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
            include_response_schema=True,
        )
        with patch("models.post_json", return_value=response) as request:
            output = client.generate(
                "system",
                "prompt",
                response_schema=schema,
                schema_name="test_answer",
            )

        self.assertEqual(output, '{"answer":"ok"}')
        payload = request.call_args.args[1]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], schema)
        self.assertEqual(client.call_history[0].response_schema_name, "test_answer")

    def test_compatible_adapter_can_use_prompt_only_fallback(self) -> None:
        response = {
            "choices": [{"message": {"content": '{"answer":"ok"}'}}],
            "usage": {},
        }
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
            include_response_schema=False,
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate(
                "system",
                "prompt",
                response_schema={"type": "object"},
                schema_name="test_answer",
            )

        self.assertNotIn("response_format", request.call_args.args[1])
        self.assertIsNone(client.call_history[0].response_schema_name)

    def test_compatible_adapter_sends_extra_options_when_set(self) -> None:
        response = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
            extra_options={"num_ctx": 8192},
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate("system", "prompt")

        payload = request.call_args.args[1]
        self.assertEqual(payload["options"], {"num_ctx": 8192})

    def test_compatible_adapter_omits_options_by_default(self) -> None:
        response = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate("system", "prompt")

        self.assertNotIn("options", request.call_args.args[1])

    def test_compatible_adapter_reads_ollama_reasoning_field(self) -> None:
        response = {
            "choices": [{"message": {"content": "ok", "reasoning": "thinking..."}}],
            "usage": {},
        }
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
        )
        with patch("models.post_json", return_value=response):
            client.generate("system", "prompt")

        self.assertEqual(client.call_history[0].reasoning_content, "thinking...")

    def test_compatible_adapter_defaults_temperature_to_zero(self) -> None:
        response = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate("system", "prompt")

        self.assertEqual(request.call_args.args[1]["temperature"], 0)

    def test_compatible_adapter_sends_explicit_temperature(self) -> None:
        response = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
        client = OpenAICompatibleClient(
            model="test-model",
            base_url="https://example.invalid/v1/chat/completions",
            temperature=0.6,
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate("system", "prompt")

        self.assertEqual(request.call_args.args[1]["temperature"], 0.6)

    def test_build_local_extra_options_merges_num_ctx_think_and_json(self) -> None:
        env = {
            "LOCAL_NUM_CTX": "16384",
            "LOCAL_THINK": "low",
            "LOCAL_MODEL_OPTIONS": '{"top_p": 0.9, "num_ctx": 32768}',
        }
        with patch.dict(os.environ, env, clear=False):
            options = build_local_extra_options()

        # LOCAL_MODEL_OPTIONS wins on the overlapping num_ctx key.
        self.assertEqual(options, {"num_ctx": 32768, "think": "low", "top_p": 0.9})

    def test_build_local_extra_options_returns_none_when_unset(self) -> None:
        env_keys = ["LOCAL_NUM_CTX", "LOCAL_THINK", "LOCAL_MODEL_OPTIONS"]
        with patch.dict(os.environ, {}, clear=False):
            for key in env_keys:
                os.environ.pop(key, None)
            self.assertIsNone(build_local_extra_options())

    def test_create_client_local_reads_temperature_from_env(self) -> None:
        env = {
            "LOCAL_TEMPERATURE": "0.6",
            "LOCAL_OPENAI_BASE_URL": "https://example.invalid/v1/chat/completions",
        }
        with patch.dict(os.environ, env, clear=False):
            client = create_client(provider="local", model="test-model")

        self.assertEqual(client.temperature, 0.6)

    def test_anthropic_adapter_sends_output_config_schema(self) -> None:
        schema = {"type": "object", "properties": {}, "required": []}
        response = {"content": [{"type": "text", "text": "{}"}], "usage": {}}
        client = AnthropicClient(
            "claude-opus-4-8", "test-key", "https://example.invalid/v1/messages"
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate(
                "system", "prompt", response_schema=schema, schema_name="test_answer"
            )

        payload = request.call_args.args[1]
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(payload["output_config"]["format"]["schema"], schema)
        self.assertEqual(client.call_history[0].response_schema_name, "test_answer")

    def test_gemini_25_adapter_sends_generate_content_schema(self) -> None:
        schema = {"type": "object", "properties": {}, "required": []}
        response = {
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
            "usageMetadata": {},
        }
        client = GeminiClient(
            "gemini-2.5-pro", "test-key", "https://example.invalid/v1beta"
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate(
                "system", "prompt", response_schema=schema, schema_name="test_answer"
            )

        config = request.call_args.args[1]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseSchema"], schema)
        self.assertEqual(client.call_history[0].response_schema_name, "test_answer")

    def test_gemini_3_adapter_uses_current_response_format(self) -> None:
        schema = {"type": "object", "properties": {}, "required": []}
        response = {
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
            "usageMetadata": {},
        }
        client = GeminiClient(
            "gemini-3.1-pro-preview", "test-key", "https://example.invalid/v1beta"
        )
        with patch("models.post_json", return_value=response) as request:
            client.generate("system", "prompt", response_schema=schema)

        response_format = request.call_args.args[1]["generationConfig"]["responseFormat"]
        self.assertEqual(response_format["text"]["mimeType"], "application/json")
        self.assertEqual(response_format["text"]["schema"], schema)


if __name__ == "__main__":
    unittest.main()
