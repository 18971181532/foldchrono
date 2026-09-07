"""SQLite metadata store + content-addressed blob store.

All file *content* lives under ``<data_dir>/blobs/<sha256[:2]>/<sha256[2:]>``
(git-style fan-out).  Identical content is stored exactly once, regardless of
how many snapshots or paths reference it.  Metadata (which path had which
hash at which snapshot) lives in SQLite.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple

DEFAULT_DATA_DIR = Path.home() / ".foldchrono"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    comment     TEXT,
    file_count  INTEGER,
    total_size  INTEGER
);
CREATE TABLE IF NOT EXISTS files (
    snapshot_id  INTEGER NOT NULL,
    rel_path     TEXT    NOT NULL,
    size         INTEGER NOT NULL,
    mtime        REAL    NOT NULL,
    sha256       TEXT    NOT NULL,
    mode         INTEGER,
    PRIMARY KEY (snapshot_id, rel_path),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_files_snapshot ON files(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_files_sha      ON files(sha256);
"""


class Storage:
    """Thin wrapper around the SQLite DB + blob directory."""

    def __init__(self, data_dir: Optional[os.PathLike] = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.db_path = self.data_dir / "foldchrono.db"
        self.blob_dir = self.data_dir / "blobs"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------ db
    @contextmanager
    def _conn(self):
        """Yield a connection, committing on success and always closing."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # --------------------------------------------------------------- blobs
    def blob_path(self, sha256: str) -> Path:
        return self.blob_dir / sha256[:2] / sha256[2:]

    def store_blob(self, src_path: os.PathLike, sha256: str) -> bool:
        """Copy *src_path* into the blob store under its content hash.

        Returns True if a new blob was written, False if it already existed
        (i.e. deduplication hit).
        """
        dst = self.blob_path(sha256)
        if dst.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp")
        shutil.copy2(src_path, tmp)
        os.replace(tmp, dst)  # atomic on POSIX & Windows
        return True

    def has_blob(self, sha256: str) -> bool:
        return self.blob_path(sha256).exists()

    def iter_blobs(self) -> Iterator[Tuple[str, Path]]:
        """Yield ``(sha256, path)`` for every blob currently on disk."""
        if not self.blob_dir.exists():
            return
        for prefix_dir in self.blob_dir.iterdir():
            if not prefix_dir.is_dir():
                continue
            for blob_file in prefix_dir.iterdir():
                if blob_file.is_file() and not blob_file.name.endswith(".tmp"):
                    sha = prefix_dir.name + blob_file.name
                    yield sha, blob_file

    def gc(self) -> Tuple[int, int]:
        """Delete blobs not referenced by any snapshot.

        Returns ``(removed_count, freed_bytes)``.
        """
        with self._conn() as c:
            referenced = {
                row[0] for row in c.execute("SELECT DISTINCT sha256 FROM files")
            }
        removed = 0
        freed = 0
        for sha, path in list(self.iter_blobs()):
            if sha not in referenced:
                try:
                    freed += path.stat().st_size
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        # remove now-empty fan-out directories
        for prefix_dir in list(self.blob_dir.iterdir()):
            if prefix_dir.is_dir() and not any(prefix_dir.iterdir()):
                try:
                    prefix_dir.rmdir()
                except OSError:
                    pass
        return removed, freed
