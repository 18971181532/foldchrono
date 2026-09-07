"""Tests for restore and garbage collection."""

import unittest
from pathlib import Path

from foldchrono.core import take_snapshot
from foldchrono.restore import restore
from foldchrono.storage import Storage

from tests.helpers import TempProject


class TestRestore(unittest.TestCase):
    def test_full_restore(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "alpha")
            proj.write("sub/b.txt", "beta")
            sid = take_snapshot(storage, proj.root)

            # destroy original
            proj.remove("a.txt")
            proj.remove("sub/b.txt")

            out = proj.root / "_restored"
            restored = restore(storage, sid, out)
            self.assertEqual(sorted(restored), ["a.txt", "sub/b.txt"])
            self.assertEqual((out / "a.txt").read_text(), "alpha")
            self.assertEqual((out / "sub/b.txt").read_text(), "beta")

    def test_restore_with_pattern(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "alpha")
            proj.write("b.log", "logdata")
            sid = take_snapshot(storage, proj.root)

            out = proj.root / "_restored"
            restored = restore(storage, sid, out, file_pattern="*.txt")
            self.assertEqual(restored, ["a.txt"])
            self.assertFalse((out / "b.log").exists())

    def test_restore_preserves_content(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            binary = bytes(range(256)) * 10
            (proj.root / "bin.dat").write_bytes(binary)
            sid = take_snapshot(storage, proj.root)

            out = proj.root / "_restored"
            restore(storage, sid, out)
            self.assertEqual((out / "bin.dat").read_bytes(), binary)


class TestGC(unittest.TestCase):
    def test_gc_removes_unreferenced_blobs(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "content-a")
            s1 = take_snapshot(storage, proj.root)
            # modify a.txt so the original content is referenced only by s1
            proj.write("a.txt", "content-a-modified")
            proj.write("b.txt", "content-b")
            s2 = take_snapshot(storage, proj.root)

            # delete snapshot 1 — the original "content-a" blob becomes unreferenced
            with storage._conn() as c:
                c.execute("DELETE FROM snapshots WHERE id=?", (s1,))

            removed, freed = storage.gc()
            self.assertEqual(removed, 1)
            self.assertGreater(freed, 0)
            # content-a-modified + content-b still referenced by s2
            blobs = {sha for sha, _ in storage.iter_blobs()}
            self.assertEqual(len(blobs), 2)

    def test_gc_noop_when_all_referenced(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "x")
            take_snapshot(storage, proj.root)
            removed, freed = storage.gc()
            self.assertEqual(removed, 0)
            self.assertEqual(freed, 0)


if __name__ == "__main__":
    unittest.main()
