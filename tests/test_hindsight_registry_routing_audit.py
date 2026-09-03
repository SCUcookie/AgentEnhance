from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_hindsight_registry_routing.py"
SPEC = importlib.util.spec_from_file_location("audit_hindsight_registry_routing", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightRegistryRoutingAuditTest(unittest.TestCase):
    def test_frozen_body_identity(self) -> None:
        self.assertEqual(MODULE.BODY_BYTES, 256_006)
        self.assertEqual(
            MODULE.BODY_SHA256,
            "6f0836431e1a0ba74bdc92732ffb0a81a1c72691bdab2bc3fba43c4a1e3716c6",
        )

    def test_hash_is_raw_byte_hash(self) -> None:
        self.assertEqual(
            MODULE.sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )


if __name__ == "__main__":
    unittest.main()
