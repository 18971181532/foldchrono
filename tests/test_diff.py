"""Tests for diff between snapshots and working tree."""

import unittest

from foldchrono.core import take_snapshot
from foldchrono.diff import diff_snapshots, diff_working_tree
from foldchrono.storage import Storage

from tests.helpers import TempProject


class TestDiffSnapshots(unittest.TestCase):
    def test_add_modify_remove(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "v1")
            proj.write("b.txt", "v1")
            s1 = take_snapshot(storage, proj.root)

            proj.write("a.txt", "v2")  # modified
            proj.remove("b.txt")       # removed
            proj.write("c.txt", "new")  # added
            s2 = take_snapshot(storage, proj.root)

            result = diff_snapshots(storage, s1, s2)
            self.assertEqual(result.added, ["c.txt"])
            self.assertEqual(result.removed, ["b.txt"])
            self.assertEqual(result.modified, ["a.txt"])
            self.assertFalse(result.unchanged)
            self.assertTrue(result.has_changes)

    def test_no_changes(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "same")
            s1 = take_snapshot(storage, proj.root)
            s2 = take_snapshot(storage, proj.root)
            result = diff_snapshots(storage, s1, s2)
            self.assertFalse(result.has_changes)
            self.assertEqual(result.unchanged, ["a.txt"])


class TestDiffWorkingTree(unittest.TestCase):
    def test_working_tree_diff(self):
        with TempProject() as proj:
            storage = Storage(data_dir=proj.root / ".fcdata")
            proj.write("a.txt", "v1")
            s1 = take_snapshot(storage, proj.root)

            proj.write("a.txt", "v2")
            proj.write("new.txt", "x")
            result = diff_working_tree(storage, s1, proj.root)
            self.assertEqual(result.modified, ["a.txt"])
            self.assertEqual(result.added, ["new.txt"])


if __name__ == "__main__":
    unittest.main()
