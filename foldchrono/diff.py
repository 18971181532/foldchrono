"""Diff between two snapshots, or a snapshot and the live working tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .core import current_tree_map
from .storage import Storage


@dataclass
class DiffResult:
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def summary(self) -> str:
        return (
            f"{len(self.added)} added, "
            f"{len(self.removed)} removed, "
            f"{len(self.modified)} modified"
        )


def _snapshot_map(storage: Storage, snapshot_id: int) -> Dict[str, str]:
    with storage._conn() as c:
        return {
            row[0]: row[1]
            for row in c.execute(
                "SELECT rel_path, sha256 FROM files WHERE snapshot_id = ?",
                (snapshot_id,),
            )
        }


def _compare(from_map: Dict[str, str], to_map: Dict[str, str]) -> DiffResult:
    result = DiffResult()
    for path, sha in to_map.items():
        if path not in from_map:
            result.added.append(path)
        elif from_map[path] != sha:
            result.modified.append(path)
        else:
            result.unchanged.append(path)
    for path in from_map:
        if path not in to_map:
            result.removed.append(path)
    result.added.sort()
    result.removed.sort()
    result.modified.sort()
    return result


def diff_snapshots(
    storage: Storage, from_id: int, to_id: int
) -> DiffResult:
    """Diff two stored snapshots."""
    return _compare(_snapshot_map(storage, from_id), _snapshot_map(storage, to_id))


def diff_working_tree(
    storage: Storage, snapshot_id: int, path: Path
) -> DiffResult:
    """Diff a stored snapshot against the current live contents of *path*."""
    return _compare(_snapshot_map(storage, snapshot_id), current_tree_map(path, storage))
