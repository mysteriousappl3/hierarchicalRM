from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


METHOD_ROOT = Path(__file__).resolve().parent
ENTRYPOINT = METHOD_ROOT / "benchmark.py"
OFFICIAL_ROOT = METHOD_ROOT.parents[1]
WORKSPACE_ROOT = OFFICIAL_ROOT.parent


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("official_dynaplan_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requested_hanoi_aliases_resolve_to_same_frozen_instance():
    module = _load_entrypoint()
    expected = ("paper-baseline-v1-n3-0017", 3)
    assert module._resolve_hanoi_task("n3-0017") == expected
    assert module._resolve_hanoi_task("3n-0017") == expected
    assert module._resolve_hanoi_task(expected[0]) == expected


def test_framework_manifest_points_only_inside_official_method_directory():
    manifest = json.loads((METHOD_ROOT / "framework.json").read_text(encoding="utf-8"))
    assert manifest["framework_version"] == "dynaplan_final_nlevel_hierarchy_v1"
    for relative in manifest["primary_architecture_files"]:
        path = WORKSPACE_ROOT / relative
        assert path.is_file(), relative
        assert path.resolve().is_relative_to(METHOD_ROOT.resolve())


def test_all_three_public_task_boundaries_preflight_without_model_calls():
    for domain in ("logistics", "blocksworld", "flat-hanoi"):
        completed = subprocess.run(
            [
                sys.executable,
                str(ENTRYPOINT),
                "--domain",
                domain,
                "--task",
                "n3-0017",
                "--constraints",
                "1",
                "--lexicon-id",
                "1",
                "--preflight",
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(OFFICIAL_ROOT),
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout.splitlines()[-1])
        assert payload["status"] == "PASS"
        assert payload["model_inference_performed"] is False
        boundary = payload["public_task_boundary"]
        assert boundary["oracle_fields_structurally_absent"] is True
        assert boundary["slot_only"] is True


def test_copied_runtime_does_not_symlink_to_development_tree():
    runtime = METHOD_ROOT / "runtime"
    sources = list(runtime.rglob("*.py")) + list(runtime.rglob("*.json"))
    assert len(sources) >= 50
    assert not [path for path in sources if path.is_symlink()]


def test_anthropic_schema_adapter_removes_only_validation_annotations():
    model_path = METHOD_ROOT / "runtime" / "models.py"
    spec = importlib.util.spec_from_file_location("copied_dynaplan_models", model_path)
    assert spec is not None and spec.loader is not None
    models = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = models
    spec.loader.exec_module(models)
    _anthropic_compatible_schema = models._anthropic_compatible_schema

    original = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "index": {"type": "integer", "minimum": 0},
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
        "required": ["index", "verdict"],
    }
    adapted = _anthropic_compatible_schema(original)
    assert adapted["properties"]["index"] == {
        "type": "integer",
        "description": "Post-generation validation requirement(s): minimum=0.",
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
    assert "minimum" in original["properties"]["index"]
