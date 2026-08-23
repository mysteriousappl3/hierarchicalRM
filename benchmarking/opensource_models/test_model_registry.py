from __future__ import annotations

import unittest

from model_registry import build_vllm_command, load_registry


class ModelRegistryTests(unittest.TestCase):
    def test_expected_six_models_are_registered(self) -> None:
        models = load_registry()
        self.assertEqual(len(models), 6)
        self.assertEqual(
            {config["capacity_tier"] for config in models.values()},
            {"low", "medium", "high"},
        )

    def test_every_model_builds_a_vllm_command(self) -> None:
        for config in load_registry().values():
            command = build_vllm_command(config)
            self.assertEqual(command[:2], ["vllm", "serve"])
            self.assertIn(str(config["model_id"]), command)
            self.assertIn(str(config["served_model_name"]), command)

    def test_family_specific_reasoning_parsers(self) -> None:
        for config in load_registry().values():
            command = build_vllm_command(config)
            parser_index = command.index("--reasoning-parser")
            expected = "qwen3" if config["family"] == "qwen3.5" else "mistral"
            self.assertEqual(command[parser_index + 1], expected)


if __name__ == "__main__":
    unittest.main()
