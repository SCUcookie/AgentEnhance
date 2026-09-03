from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Wave1ProjectionControlV2Tests(unittest.TestCase):
    def test_projection_control_is_exact_and_result_free(self) -> None:
        module = load_module(
            "wave1_projection_v2", ROOT / "scripts/remote_wma_wave1_project_v2.py"
        )
        self.assertEqual(len(module.EXPECTED_IMPLEMENTATIONS), 4)
        self.assertEqual(len(set(module.EXPECTED_IMPLEMENTATIONS)), 4)
        self.assertEqual(len(module.PACKAGE_FILES), 10)
        for relative, expected in module.PACKAGE_FILES.items():
            self.assertEqual(module.sha256_file(ROOT / relative), expected)
        self.assertTrue(str(module.OUTPUT_ROOT).startswith("/data1/2026/ldh/AgentEnhance/runs/"))
        self.assertFalse(module.OUTPUT_ROOT.exists())

    def test_projection_prefreeze_binds_the_control(self) -> None:
        module = load_module(
            "wave1_projection_v2_manifest", ROOT / "scripts/remote_wma_wave1_project_v2.py"
        )
        manifest = json.loads(
            (ROOT / "comparisons/wma-r1-wave1-table-projection-prefreeze.v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["status"], "FROZEN_BEFORE_WAVE1_TERMINAL")
        self.assertEqual(manifest["inputs"]["implementation_ids"], list(module.EXPECTED_IMPLEMENTATIONS))
        self.assertEqual(manifest["output_root"], str(module.OUTPUT_ROOT))
        self.assertEqual(
            manifest["implementation"]["projector_sha256"],
            module.PACKAGE_FILES["scripts/project_wma_method_summaries_v2.py"],
        )

    def test_projection_archive_is_small_overlay_after_raw_archive(self) -> None:
        module = load_module(
            "wave1_projection_archive_v2",
            ROOT / "scripts/remote_archive_wma_wave1_projection_v2.py",
        )
        manifest = json.loads(
            (ROOT / "comparisons/wma-r1-wave1-table-projection-archive-prefreeze.v2.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["status"], "FROZEN_BEFORE_WAVE1_TERMINAL")
        self.assertEqual(manifest["raw_archive_root"], str(module.RAW_ARCHIVE_ROOT))
        self.assertEqual(manifest["projection_root"], str(module.PROJECTION_ROOT))
        self.assertEqual(manifest["destination_root"], str(module.ARCHIVE_ROOT))
        self.assertEqual(manifest["transfer"]["rate_limit_kbit_per_second"], 4096)
        self.assertLessEqual(module.ARCHIVE_STORAGE_CEILING_BYTES, 1024**3)


if __name__ == "__main__":
    unittest.main()
