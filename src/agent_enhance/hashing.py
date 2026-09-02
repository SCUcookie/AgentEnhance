from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


CHUNK_SIZE = 1024 * 1024


class FingerprintError(ValueError):
    """Raised when a path cannot be fingerprinted safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise FingerprintError(f"symlink is not allowed in a frozen input: {path}")
        if path.is_file():
            yield path


def fingerprint(path: Path) -> dict:
    if path.is_symlink():
        raise FingerprintError(f"symlink is not allowed in a frozen input: {path}")
    resolved = path.resolve(strict=True)
    if resolved.is_file():
        return {
            "kind": "file",
            "path": str(resolved),
            "size": resolved.stat().st_size,
            "sha256": sha256_file(resolved),
        }
    if not resolved.is_dir():
        raise FingerprintError(f"unsupported path type: {path}")

    digest = hashlib.sha256()
    count = 0
    total_size = 0
    for item in _files(resolved):
        relative = item.relative_to(resolved).as_posix().encode("utf-8")
        size = item.stat().st_size
        item_hash = sha256_file(item).encode("ascii")
        digest.update(b"file\0")
        digest.update(str(len(relative)).encode("ascii"))
        digest.update(b"\0")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(item_hash)
        digest.update(b"\n")
        count += 1
        total_size += size
    return {
        "kind": "directory",
        "path": str(resolved),
        "file_count": count,
        "total_size": total_size,
        "sha256": digest.hexdigest(),
    }
