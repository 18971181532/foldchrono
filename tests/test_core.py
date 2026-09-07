"""Tests for the snapshot engine and blob deduplication."""

import unittest
from pathlib import Path

from foldchrono.core import (
    DEFAULT_IGNORE,
    is_ignored,
    load_ignore,
    sha256_file,
    take_snapshot,
)
from foldchrono.storage import Storage

from tests.helpers import TempProject


class TestSha256File(unittest.TestCase):
    def test_known_hash(self):
        with TempProject() as proj:
            p = proj.write("a.txt", "hello")
            # sha256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
            self.assertEqual(
                sha256_file(p),
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            )

    def test_empty_file(self):
        with TempProject() as proj:
            p = proj.write("empty.txt", "")
            self.assertEqual(
                sha256_file(p),
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            )


class TestIgnore(unittest.TestCase):
    def test_default_ignores_git(self):
        self.assertTrue(is_ignored(".git/config", DEFAULT_IGNORE))
        self.assertTrue(is_ignored("node_modules/foo.js", DEFAULT_IGNORE))
        self.assertFalse(is_ignored("src/main.py", DEFAULT_IGNORE))

    def test_load_ignore_file(self):
        with TempProject() as proj:
            proj.write(".foldchronoignore", "# comment\nbuild/\n*.log\n")
            patterns = load_ignore(proj.root)
            self.assertIn("build/", patterns)
            self.assertIn("*.log", patterns)
            self.assertNotIn("# comment", patterns)


class TestSnapshot(unittest.TestCase):
    def test_basic_snapshot_records_files(self):
        with TempProject() as proj:
            proj.write("a.txt", "alpha")
            proj.write("sub/b.txt", "beta")
            storage = Storage(data_dir=proj.root / ".fcdata")
            sid = take_snapshot(storage, proj.root)
            self.assertIsInstance(sid, int)
            with storage._conn() as c:
                files = c.execute(
                    "SELECT rel_path FROM files WHERE snapshot_id=?", (sid,)
                ).fetchall()
            rels = {r[0] for r in files}
            self.assertEqual(rels, {"a.txt", "sub/b.txt"})

    def test_deduplication_same_content(self):
        with TempProject() as proj:
            proj.write("one.txt", "same content")
            proj.write("two.txt", "same content")
            storage = Storage(data_dir=proj.root / ".fcdata")
            take_snapshot(storage, proj.root)
            blobs = list(storage.iter_blobs())
            # identical content → exactly one blob
            self.assertEqual(len(blobs), 1)

    def test_ignored_directories_skipped(self):
        with TempProject() as proj:
            proj.write("keep.txt", "yes")
            proj.write(".git/config", "x")
            proj.write("node_modules/pkg/index.js", "x")
            proj.write("__pycache__/mod.pyc", "x")
            storage = Storage(data_dir=proj.root / ".fcdata")
            sid = take_snapshot(storage, proj.root)
            with storage._conn() as c:
                rels = {
                    r[0]
                    for r in c.execute(
                        "SELECT rel_path FROM files WHERE snapshot_id=?", (sid,)
                    )
                }
            self.assertEqual(rels, {"keep.txt"})

    def test_custom_ignore_file(self):
        with TempProject() as proj:
            proj.write("keep.txt", "yes")
            proj.write("build/output.bin", "x")
            proj.write(".foldchronoignore", "build/\n")
            storage = Storage(data_dir=proj.root / ".fcdata")
            sid = take_snapshot(storage, proj.root)
            with storage._conn() as c:
                rels = {
                    r[0]
                    for r in c.execute(
                        "SELECT rel_path FROM files WHERE snapshot_id=?", (sid,)
                    )
                }
            self.assertEqual(rels, {"keep.txt", ".foldchronoignore"})

    def test_snapshot_metadata(self):
        with TempProject() as proj:
            proj.write("a.txt", "12345")  # 5 bytes
            storage = Storage(data_dir=proj.root / ".fcdata")
            sid = take_snapshot(storage, proj.root, comment="first")
            with storage._conn() as c:
                row = c.execute(
                    "SELECT file_count, total_size, comment FROM snapshots WHERE id=?",
                    (sid,),
                ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 5)
        self.assertEqual(row[2], "first")


if __name__ == "__main__":
    unittest.main()
