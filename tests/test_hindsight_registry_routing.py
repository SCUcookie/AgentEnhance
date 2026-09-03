from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "split_hindsight_requirements_by_registry.py"
SPEC = importlib.util.spec_from_file_location("split_hindsight_requirements_by_registry", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightRegistryRoutingTest(unittest.TestCase):
    def test_split_preserves_blocks_and_order_manifest(self) -> None:
        first = b"alpha==1 \\\n    --hash=sha256:a\n    # via root\n"
        torch = b"torch==2.10.0+cpu ; sys_platform != 'darwin' \\\n    --hash=sha256:t\n"
        last = b"zeta==2 \\\n    --hash=sha256:z\n"
        payload = first + torch + last
        pypi, pytorch, manifest = MODULE.split_payload(payload)
        self.assertEqual(pypi, first + last)
        self.assertEqual(pytorch, torch)
        self.assertEqual([row["route"] for row in manifest], ["pypi", "pytorch-cpu", "pypi"])
        self.assertEqual([row["sequence_index"] for row in manifest], [0, 1, 2])

    def test_rejects_non_requirement_prefix(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "does not begin"):
            MODULE.requirement_blocks(b"# unexpected prefix\na==1\n")

    def test_frozen_cardinality_and_sources(self) -> None:
        self.assertEqual(MODULE.TOTAL_REQUIREMENTS, 208)
        self.assertEqual(MODULE.PYPI_REQUIREMENTS, 206)
        self.assertEqual(MODULE.PYTORCH_REQUIREMENTS, 2)
        self.assertEqual(
            {MODULE.PYPI_URL, MODULE.PYTORCH_URL},
            {"https://pypi.org/simple", "https://download.pytorch.org/whl/cpu"},
        )


if __name__ == "__main__":
    unittest.main()
