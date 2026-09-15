import unittest
from pathlib import Path

from flat_hanoi.generate import generate_instances
from flat_hanoi.io import jsonl_bytes, validate_dataset


ROOT = Path(__file__).resolve().parents[1]


class FrozenDataTests(unittest.TestCase):
    FILES = {
        "paper-baseline-v1": "paper_baseline_v1.jsonl",
        "paper-extension-v1": "paper_extension_n6_n7_v1.jsonl",
        "unrestricted-pairs-sensitivity-v1": "unrestricted_pairs_sensitivity_v1.jsonl",
        "transformer-n4-v1": "transformer_n4_all_pairs_v1.jsonl",
    }

    def test_all_checked_in_manifests_validate(self):
        for profile, filename in self.FILES.items():
            with self.subTest(profile=profile):
                result = validate_dataset(ROOT / "flat_hanoi" / "data" / filename)
                self.assertTrue(result["validated"])
                self.assertEqual(result["sampling_profile"], profile)

    def test_frozen_bytes_match_current_generator(self):
        for profile, filename in self.FILES.items():
            with self.subTest(profile=profile):
                expected = (ROOT / "flat_hanoi" / "data" / filename).read_bytes()
                self.assertEqual(expected, jsonl_bytes(generate_instances(profile)))


if __name__ == "__main__":
    unittest.main()
