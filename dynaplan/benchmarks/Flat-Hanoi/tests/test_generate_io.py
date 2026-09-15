import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from flat_hanoi.generate import DEFAULT_SEED, generate_instances, pair_from_index
from flat_hanoi.io import jsonl_bytes, read_instances, validate_dataset, write_dataset
from flat_hanoi.model import is_strict_flat


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = generate_instances("paper-baseline-v1")
        cls.extension = generate_instances("paper-extension-v1")
        cls.unrestricted = generate_instances("unrestricted-pairs-sensitivity-v1")
        cls.transformer = generate_instances("transformer-n4-v1")

    def test_default_seed_comes_from_arxiv_identifier(self):
        self.assertEqual(DEFAULT_SEED, 260807077)

    def test_baseline_exact_reported_counts(self):
        self.assertEqual(Counter(item.n for item in self.baseline), {3: 34, 4: 33, 5: 33})

    def test_extension_exact_reported_counts(self):
        self.assertEqual(Counter(item.n for item in self.extension), {6: 33, 7: 33})

    def test_pairs_and_ids_are_unique(self):
        for records in (self.baseline, self.extension, self.unrestricted, self.transformer):
            with self.subTest(profile=records[0].sampling_profile):
                self.assertEqual(len({item.instance_id for item in records}), len(records))
                self.assertEqual(
                    len({(item.n, item.start, item.goal) for item in records}),
                    len(records),
                )

    def test_endpoints_are_distinct(self):
        self.assertTrue(all(item.start != item.goal for item in self.baseline + self.extension))

    def test_primary_profile_has_no_minimum_distance_filter(self):
        self.assertTrue(any(item.optimal_distance < item.n for item in self.baseline))

    def test_paper_profiles_have_only_multi_peg_endpoints(self):
        self.assertTrue(all(is_strict_flat(item.start) and is_strict_flat(item.goal)
                            for item in self.baseline + self.extension))

    def test_unrestricted_sensitivity_uses_full_endpoint_population(self):
        self.assertEqual(
            Counter(item.n for item in self.unrestricted),
            {3: 34, 4: 33, 5: 33},
        )
        self.assertTrue(any(not is_strict_flat(item.start) or not is_strict_flat(item.goal)
                            for item in self.unrestricted))

    def test_generation_is_byte_deterministic(self):
        regenerated = generate_instances("paper-baseline-v1", DEFAULT_SEED)
        self.assertEqual(jsonl_bytes(self.baseline), jsonl_bytes(regenerated))

    def test_changing_seed_changes_sample(self):
        changed = generate_instances("paper-baseline-v1", DEFAULT_SEED + 1)
        self.assertNotEqual(jsonl_bytes(self.baseline), jsonl_bytes(changed))

    def test_pair_index_enumerates_every_distinct_ordered_pair(self):
        pairs = [pair_from_index(index, 2) for index in range(9 * 8)]
        self.assertEqual(len(set(pairs)), 72)
        self.assertTrue(all(start != goal for start, goal in pairs))

    def test_transformer_contains_all_6480_pairs(self):
        self.assertEqual(len(self.transformer), 6480)
        states = {item.start for item in self.transformer} | {item.goal for item in self.transformer}
        self.assertEqual(len(states), 81)
        self.assertEqual(
            len({(item.start, item.goal) for item in self.transformer}),
            81 * 80,
        )

    def test_transformer_exact_80_20_split(self):
        self.assertEqual(
            Counter(item.split for item in self.transformer),
            {"train": 5184, "validation": 1296},
        )

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            generate_instances("unknown")


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instances = generate_instances("paper-baseline-v1")

    def test_round_trip_and_manifest_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            manifest = write_dataset(path, self.instances)
            self.assertEqual(read_instances(path), self.instances)
            checked = validate_dataset(path)
            self.assertTrue(checked["validated"])
            self.assertEqual(checked["jsonl_sha256"], manifest["jsonl_sha256"])

    def test_manifest_records_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            manifest = write_dataset(path, self.instances)
            protocol = manifest["evaluation_protocol"]
            self.assertEqual(protocol["max_output_tokens"], 32000)
            self.assertIn("answer_only", protocol["output_budget_scope"])
            self.assertEqual(protocol["temperature"], 1.0)
            self.assertIn("inherited", protocol["temperature_basis"])
            self.assertFalse(protocol["tools_allowed"])
            self.assertTrue(protocol["unparseable_in_denominator"])
            self.assertEqual(protocol["headline_metric"], "optimal_accuracy")

    def test_byte_tampering_fails_manifest_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            write_dataset(path, self.instances)
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "manifest"):
                validate_dataset(path, check_oracle=False)

    def test_manifest_json_type_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            write_dataset(path, self.instances)
            manifest_path = path.with_suffix(".manifest.json")
            manifest = json.loads(manifest_path.read_text())
            manifest["schema_version"] = True
            manifest["instance_count"] = float(manifest["instance_count"])
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "manifest"):
                validate_dataset(path, check_oracle=False)

    def test_duplicate_id_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            first = self.instances[0].to_dict()
            second = self.instances[1].to_dict()
            second["instance_id"] = first["instance_id"]
            path.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")
            with self.assertRaisesRegex(ValueError, "ids"):
                validate_dataset(path, check_oracle=False)

    def test_bad_stored_distance_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            records = [item.to_dict() for item in self.instances]
            records[0]["optimal_distance"] += 1
            path.write_text("".join(json.dumps(row) + "\n" for row in records))
            with self.assertRaisesRegex(ValueError, "optimal_distance"):
                validate_dataset(path)

    def test_profile_count_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            path.write_bytes(jsonl_bytes(self.instances[:-1]))
            with self.assertRaisesRegex(ValueError, "counts"):
                validate_dataset(path, check_oracle=False)

    def test_missing_manifest_rejected_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            path.write_bytes(jsonl_bytes(self.instances))
            with self.assertRaisesRegex(ValueError, "manifest is missing"):
                validate_dataset(path)
            result = validate_dataset(path, require_manifest=False)
            self.assertFalse(result["manifest_checked"])


if __name__ == "__main__":
    unittest.main()
