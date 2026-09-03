from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from frozen_source_successor import render_successor  # noqa: E402


CASES = {
    "remote_wma_wave1_postprocess_recovery2": "remote_wma_wave1_postprocess.py",
    "remote_wma_wave1_project_recovery2": "remote_wma_wave1_project_v2.py",
    "remote_archive_wma_wave1_recovery2": "remote_archive_wma_wave1.py",
    "remote_archive_wma_wave1_projection_recovery2": "remote_archive_wma_wave1_projection_v2.py",
}


class Wave1Recovery2ClosureTests(unittest.TestCase):
    def render(self, wrapper_name: str) -> tuple[object, str]:
        wrapper = importlib.import_module(wrapper_name)
        parent = SCRIPTS / CASES[wrapper_name]
        source = render_successor(
            parent,
            wrapper.PARENT_SHA256,
            wrapper.REPLACEMENTS,
            wrapper.RENDERED_SHA256,
        )
        compile(source, f"<{wrapper_name}>", "exec")
        return wrapper, source

    def test_all_successors_render_to_exact_frozen_python(self) -> None:
        for wrapper_name in CASES:
            with self.subTest(wrapper=wrapper_name):
                wrapper, source = self.render(wrapper_name)
                self.assertNotIn("TO_BE_FROZEN", source)
                self.assertEqual(len(wrapper.RENDERED_SHA256), 64)

    def test_postprocess_uses_only_recovery2_run_roots(self) -> None:
        _, source = self.render("remote_wma_wave1_postprocess_recovery2")
        namespace = {"__name__": "recovery2_postprocess_test"}
        exec(compile(source, "<postprocess>", "exec"), namespace)
        self.assertIn("controller-recovery2-20260904-v1", str(namespace["CONTROLLER_ROOT"]))
        self.assertIn("summaries-recovery2-20260904-v1", str(namespace["OUTPUT_ROOT"]))
        roots = [
            str(root)
            for item in namespace["build_plan"]()
            for root in item["aggregate_roots"]
        ]
        self.assertEqual(len(roots), 12)
        self.assertTrue(all("-recovery2-20260904-v1-aggregate" in root for root in roots))
        expected_rows = namespace["expected_progress_rows"]()
        self.assertEqual(len(expected_rows), 12)
        self.assertTrue(all("-recovery2-20260904-v1" in row[2] for row in expected_rows))

    def test_projection_and_archives_share_successor_roots(self) -> None:
        namespaces = {}
        for wrapper_name in (
            "remote_wma_wave1_project_recovery2",
            "remote_archive_wma_wave1_recovery2",
            "remote_archive_wma_wave1_projection_recovery2",
        ):
            _, source = self.render(wrapper_name)
            namespace = {"__name__": f"{wrapper_name}_test"}
            exec(compile(source, f"<{wrapper_name}>", "exec"), namespace)
            namespaces[wrapper_name] = namespace
        projection = namespaces["remote_wma_wave1_project_recovery2"]
        raw_archive = namespaces["remote_archive_wma_wave1_recovery2"]
        overlay = namespaces["remote_archive_wma_wave1_projection_recovery2"]
        self.assertEqual(projection["SUMMARY_ROOT"].name, raw_archive["SUMMARY"])
        self.assertEqual(projection["OUTPUT_ROOT"], overlay["PROJECTION_ROOT"])
        self.assertEqual(raw_archive["ARCHIVE_ROOT"], overlay["RAW_ARCHIVE_ROOT"])
        self.assertEqual(
            str(raw_archive["ARCHIVE_ROOT"]),
            "/data2/2026/ldh/AgentEnhance/archives/wma-r1-wave1-recovery2-20260904-v1",
        )
        self.assertEqual(
            str(overlay["ARCHIVE_ROOT"]),
            "/data2/2026/ldh/AgentEnhance/archives/"
            "wma-r1-wave1-table-projection-recovery2-20260904-v3",
        )

    def test_renderer_rejects_parent_or_replacement_drift(self) -> None:
        wrapper = importlib.import_module("remote_wma_wave1_project_recovery2")
        parent = SCRIPTS / CASES["remote_wma_wave1_project_recovery2"]
        with self.assertRaises(SystemExit):
            render_successor(
                parent,
                "0" * 64,
                wrapper.REPLACEMENTS,
                wrapper.RENDERED_SHA256,
            )
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / parent.name
            changed.write_bytes(parent.read_bytes() + b"\n")
            with self.assertRaises(SystemExit):
                render_successor(
                    changed,
                    wrapper.PARENT_SHA256,
                    wrapper.REPLACEMENTS,
                    wrapper.RENDERED_SHA256,
                )


if __name__ == "__main__":
    unittest.main()
