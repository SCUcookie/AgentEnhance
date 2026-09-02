from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .hashing import FingerprintError, fingerprint
from .validation import validate_project


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-enhance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate repository contracts and invariants")
    validate.add_argument("root", nargs="?", default=".")

    hash_command = subparsers.add_parser("fingerprint", help="compute a deterministic SHA-256 fingerprint")
    hash_command.add_argument("path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        root = Path(args.root)
        issues = validate_project(root)
        report = {
            "schema_version": "repository_validation_report.v1",
            "status": "passed" if not issues else "failed",
            "root": str(root.resolve()),
            "issue_count": len(issues),
            "issues": [{"path": issue.path, "message": issue.message} for issue in issues],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not issues else 1

    try:
        report = fingerprint(Path(args.path))
    except (OSError, FingerprintError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"schema_version": "fingerprint_report.v1", **report}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
