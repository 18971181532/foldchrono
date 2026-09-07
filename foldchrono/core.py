"""Snapshot engine: walk a directory, hash files, record into Storage."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from .storage import Storage

# Directories / patterns always skipped, even without a .foldchronoignore.
DEFAULT_IGNORE: Tuple[str, ...] = (
    ".git",
    ".foldchrono",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "*.pyc",
    "*.pyo",
    "*.tmp",
)

_CHUNK = 1 << 16  # 64 KiB


def sha256_file(path: os.PathLike) -> str:
    """Return the hex SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_ignore(root: Path) -> List[str]:
    """Read ``.foldchronoignore`` from *root* if present (gitignore-lite)."""
    patterns: List[str] = []
    ignore_file = root / ".foldchronoignore"
    if ignore_file.is_file():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError:
            pass
    return patterns


def is_ignored(rel_path: str, patterns: Sequence[str]) -> bool:
    """Match *rel_path* against ignore patterns.

    A pattern matches if it matches the full relative path *or* any path
    component (so a directory pattern like ``.git`` ignores everything under
    ``.git/``).
    """
    norm = rel_path.replace("\\", "/")
    parts = norm.split("/")
    for p in patterns:
        pnorm = p.rstrip("/")
        if fnmatch.fnmatch(norm, pnorm) or fnmatch.fnmatch(norm, p):
            return True
        for part in parts:
            if fnmatch.fnmatch(part, pnorm):
                return True
    return False


def build_patterns(root: Path, storage: Optional[Storage] = None) -> List[str]:
    """Combine default ignores, .foldchronoignore, and the storage dir."""
    patterns = list(DEFAULT_IGNORE) + load_ignore(root)
    if storage is not None:
        try:
            rel_storage = storage.data_dir.resolve().relative_to(root).as_posix()
            patterns.append(rel_storage)
        except ValueError:
            pass  # storage dir is outside the snapshot root
    return patterns


def _walk_files(
    root: Path, patterns: Sequence[str]
) -> Iterable[Tuple[Path, str]]:
    """Yield ``(absolute_path, relative_path)`` for every non-ignored file."""
    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored directories in-place so os.walk doesn't descend
        dirnames[:] = [
            d
            for d in dirnames
            if not is_ignored(
                os.path.relpath(os.path.join(dirpath, d), root), patterns
            )
        ]
        for fn in filenames:
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            if is_ignored(rel, patterns):
                continue
            yield full, rel


def take_snapshot(
    storage: Storage,
    path: os.PathLike,
    comment: Optional[str] = None,
) -> int:
    """Snapshot *path* and return the new snapshot id."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    patterns = build_patterns(root, storage)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    files: List[Tuple[str, int, float, str, Optional[int]]] = []
    total_size = 0

    for full, rel in _walk_files(root, patterns):
        try:
            st = full.stat()
            sha = sha256_file(full)
            storage.store_blob(full, sha)
            files.append((rel, st.st_size, st.st_mtime, sha, st.st_mode))
            total_size += st.st_size
        except (OSError, PermissionError):
            # unreadable file — skip but keep going
            continue

    with storage._conn() as c:
        cur = c.execute(
            "INSERT INTO snapshots (path, created_at, comment, file_count, total_size)"
            " VALUES (?, ?, ?, ?, ?)",
            (str(root), now, comment, len(files), total_size),
        )
        sid = cur.lastrowid
        c.executemany(
            "INSERT OR REPLACE INTO files"
            " (snapshot_id, rel_path, size, mtime, sha256, mode)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(sid, *row) for row in files],
        )
    return sid


def tree_signature(path: os.PathLike, storage: Optional[Storage] = None) -> str:
    """Cheap hash of (relative path, size, mtime) for change detection.

    Used by ``watch`` — does *not* read file contents.
    """
    root = Path(path).resolve()
    patterns = build_patterns(root, storage)
    entries: List[Tuple[str, int, int]] = []
    for full, rel in _walk_files(root, patterns):
        try:
            st = full.stat()
            entries.append((rel, st.st_size, int(st.st_mtime)))
        except OSError:
            continue
    entries.sort()
    h = hashlib.sha256()
    for rel, size, mtime in entries:
        h.update(f"{rel}\x00{size}\x00{mtime}\x00".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def current_tree_map(path: os.PathLike, storage: Optional[Storage] = None) -> dict:
    """Return ``{relative_path: sha256}`` for the live tree (no storage)."""
    root = Path(path).resolve()
    patterns = build_patterns(root, storage)
    result: dict = {}
    for full, rel in _walk_files(root, patterns):
        try:
            result[rel] = sha256_file(full)
        except OSError:
            continue
    return result
