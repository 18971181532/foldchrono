"""Restore files from a snapshot back to disk."""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import List, Optional

from .storage import Storage


def restore(
    storage: Storage,
    snapshot_id: int,
    target_dir: os.PathLike,
    file_pattern: Optional[str] = None,
) -> List[str]:
    """Restore every file (or those matching *file_pattern*) from a snapshot.

    Returns the list of relative paths that were written.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    with storage._conn() as c:
        rows = c.execute(
            "SELECT rel_path, sha256, mode FROM files WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()

    restored: List[str] = []
    for rel, sha, mode in rows:
        if file_pattern and not fnmatch.fnmatch(rel, file_pattern):
            continue
        src = storage.blob_path(sha)
        if not src.exists():
            # blob was gc'd or is missing — skip silently
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if mode:
            try:
                os.chmod(dst, mode)
            except OSError:
                pass
        restored.append(rel)
    restored.sort()
    return restored
