import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from flat_hanoi.cli import command_generate, main
from flat_hanoi.io import read_instances, write_dataset
from flat_hanoi.model import Instance


def run_cli(arguments):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        status = main(arguments)
    return status, stream.getvalue()


class CliTests(unittest.TestCase):
    def test_generate_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = str(Path(directory) / "baseline.jsonl")
            status, output = run_cli([
                "generate", "--profile", "paper-baseline-v1", "--output", dataset,
            ])
            self.assertEqual(status, 0)
            self.assertEqual(len(read_instances(dataset)), 100)
            self.assertIn("jsonl_sha256", json.loads(output)["manifest"])
            status, output = run_cli(["validate", dataset])
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(output)["validated"])

    def test_prompt_oracle_and_score(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = str(Path(directory) / "one.jsonl")
            instance = Instance(1, "one", 2, (0, 0), (2, 2), 3, "test", 1)
            write_dataset(dataset, [instance])
            status, prompt = run_cli(["prompt", "--dataset", dataset, "--instance", "one"])
            self.assertEqual(status, 0)
            messages = json.loads(prompt)
            self.assertEqual([message["role"] for message in messages], ["system", "user"])
            self.assertIn("moves =", messages[1]["content"])
            status, oracle = run_cli(["oracle", "--dataset", dataset, "--instance", "one"])
            self.assertEqual(json.loads(oracle)["optimal_distance"], 3)
            status, score = run_cli([
                "score", "--dataset", dataset, "--instance", "one",
                "--text", "moves=[[1,0,1],[2,0,2],[1,1,2]]",
            ])
            self.assertEqual(json.loads(score)["classification"], "optimal")

    def test_text_prompt_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = str(Path(directory) / "one.jsonl")
            write_dataset(dataset, [Instance(1, "one", 2, (0, 0), (2, 2), 3, "test", 1)])
            status, prompt = run_cli([
                "prompt", "--dataset", dataset, "--instance", "one", "--format", "text",
            ])
            self.assertEqual(status, 0)
            self.assertTrue(prompt.startswith("SYSTEM MESSAGE"))

    def test_generate_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "tasks.jsonl"
            output.write_text("do not overwrite")
            args = type("Args", (), {
                "output": str(output), "profile": "paper-baseline-v1",
                "seed": 260807077, "force": False,
            })()
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                command_generate(args)
            self.assertEqual(output.read_text(), "do not overwrite")

    def test_batch_preserves_missing_response_as_illegal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "two.jsonl"
            results = root / "results.jsonl"
            summary = root / "summary.json"
            instances = [
                Instance(1, "one", 2, (0, 0), (2, 2), 3, "test", 1),
                Instance(1, "two", 2, (2, 2), (0, 0), 3, "test", 1),
            ]
            write_dataset(dataset, instances)
            responses = root / "responses.jsonl"
            responses.write_text(json.dumps({
                "instance_id": "one",
                "response": "moves=[[1,0,1],[2,0,2],[1,1,2]]",
                "total_tokens": 42,
            }) + "\n")
            status, output = run_cli([
                "score-batch", "--dataset", str(dataset),
                "--responses", str(responses), "--output", str(results),
                "--summary", str(summary),
            ])
            self.assertEqual(status, 0)
            report = json.loads(output)["summary"]
            self.assertEqual(report["total"], 2)
            self.assertEqual(report["counts"], {"illegal": 1, "optimal": 1})
            self.assertEqual(report["optimal_accuracy"], 0.5)
            self.assertEqual(report["usage_totals"]["total_tokens"], 42)
            result_rows = [json.loads(line) for line in results.read_text().splitlines()]
            missing = next(row for row in result_rows if row["instance_id"] == "two")
            self.assertFalse(missing["parseable"])
            self.assertEqual(missing["classification"], "illegal")
            self.assertEqual(json.loads(summary.read_text())["total"], 2)

    def test_summarize_command(self):
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results.jsonl"
            results.write_text(
                json.dumps({"classification": "optimal", "parseable": True, "legal": True}) + "\n"
            )
            status, output = run_cli(["summarize", str(results)])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["optimal_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
