#!/usr/bin/env python3
"""Render and execute a byte-identified successor of an immutable control script."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


Replacement = tuple[str, str, int]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def render_successor(
    parent: Path,
    parent_sha256: str,
    replacements: Iterable[Replacement],
    rendered_sha256: str,
) -> str:
    if sha256_file(parent) != parent_sha256:
        raise SystemExit(f"immutable parent script digest mismatch: {parent}")
    source = parent.read_text(encoding="utf-8")
    for old, new, expected_count in replacements:
        observed_count = source.count(old)
        if observed_count != expected_count:
            raise SystemExit(
                f"frozen replacement count mismatch: expected={expected_count} "
                f"observed={observed_count} token={old!r}"
            )
        source = source.replace(old, new)
    if sha256_bytes(source.encode("utf-8")) != rendered_sha256:
        raise SystemExit("rendered successor script digest mismatch")
    return source


def execute_successor(
    parent: Path,
    parent_sha256: str,
    replacements: Iterable[Replacement],
    rendered_sha256: str,
    arguments: list[str],
) -> int:
    source = render_successor(parent, parent_sha256, replacements, rendered_sha256)
    suffix = parent.suffix or ".tmp"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="agentenhance-successor-", suffix=suffix
    ) as handle:
        handle.write(source)
        handle.flush()
        result = subprocess.run([sys.executable, handle.name, *arguments], check=False)
    return result.returncode
