from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize_hf_model_snapshot.py"
SPEC = importlib.util.spec_from_file_location("materialize_hf_model_snapshot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HfModelMaterializerTest(unittest.TestCase):
    def test_resolves_environment_backed_contract_path(self) -> None:
        with patch.dict(os.environ, {"AGENT_ENHANCE_REMOTE_ROOT": "/data1/example/AgentEnhance"}):
            self.assertEqual(
                MODULE.resolve_manifest_path(
                    "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/example-model"
                ),
                Path("/data1/example/AgentEnhance/cache/models/example-model"),
            )

    def test_rejects_unresolved_environment_variable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "unresolved environment variable"):
                MODULE.resolve_manifest_path(
                    "${AGENT_ENHANCE_REMOTE_ROOT}/cache/models/example-model"
                )

    def test_repository_files_excludes_huggingface_metadata(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".cache" / "huggingface").mkdir(parents=True)
            (root / ".cache" / "huggingface" / "download.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (root / "config.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(MODULE.repository_files(root), [root / "config.json"])


if __name__ == "__main__":
    unittest.main()
