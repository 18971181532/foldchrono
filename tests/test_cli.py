"""End-to-end CLI tests using argparse main()."""

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr

from foldchrono.cli import main

from tests.helpers import TempProject


def run_cli(*args: str) -> tuple[int, str, str]:
    """Invoke foldchrono CLI and return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class TestCLI(unittest.TestCase):
    def test_snapshot_list_show_diff_restore_flow(self):
        with TempProject() as proj:
            data_dir = str(proj.root / ".fcdata")
            proj.write("a.txt", "v1")
            proj.write("b.txt", "v1")

            # snapshot
            code, out, _ = run_cli("--data-dir", data_dir, "snapshot", str(proj.root))
            self.assertEqual(code, 0)
            self.assertIn("Snapshot #1 created", out)

            # modify
            proj.write("a.txt", "v2")
            proj.write("c.txt", "new")

            # status
            code, out, _ = run_cli("--data-dir", data_dir, "status", str(proj.root))
            self.assertEqual(code, 0)
            self.assertIn("a.txt", out)
            self.assertIn("c.txt", out)

            # second snapshot
            code, out, _ = run_cli("--data-dir", data_dir, "snapshot", str(proj.root), "-m", "second")
            self.assertEqual(code, 0)
            self.assertIn("Snapshot #2 created", out)

            # list
            code, out, _ = run_cli("--data-dir", data_dir, "list")
            self.assertEqual(code, 0)
            self.assertIn("#1", out)
            self.assertIn("#2", out)

            # show
            code, out, _ = run_cli("--data-dir", data_dir, "show", "1")
            self.assertEqual(code, 0)
            self.assertIn("a.txt", out)
            self.assertIn("b.txt", out)

            # diff 1 -> 2
            code, out, _ = run_cli("--data-dir", data_dir, "diff", str(proj.root), "--from", "1", "--to", "2")
            self.assertEqual(code, 0)
            self.assertIn("+ c.txt", out)
            self.assertIn("~ a.txt", out)

            # restore snapshot 1
            out_dir = str(proj.root / "restored")
            code, out, _ = run_cli("--data-dir", data_dir, "restore", "1", "--to", out_dir)
            self.assertEqual(code, 0)
            self.assertIn("Restored 2 file(s)", out)
            self.assertEqual((proj.root / "restored" / "a.txt").read_text(), "v1")
            self.assertEqual((proj.root / "restored" / "b.txt").read_text(), "v1")

    def test_diff_no_snapshots(self):
        with TempProject() as proj:
            data_dir = str(proj.root / ".fcdata")
            code, out, _ = run_cli("--data-dir", data_dir, "diff", str(proj.root))
            self.assertEqual(code, 1)
            self.assertIn("No snapshots", out)

    def test_show_nonexistent(self):
        with TempProject() as proj:
            data_dir = str(proj.root / ".fcdata")
            code, _, err = run_cli("--data-dir", data_dir, "show", "999")
            self.assertEqual(code, 1)
            self.assertIn("does not exist", err)

    def test_rm_and_gc(self):
        with TempProject() as proj:
            data_dir = str(proj.root / ".fcdata")
            proj.write("a.txt", "data")
            run_cli("--data-dir", data_dir, "snapshot", str(proj.root))
            code, out, _ = run_cli("--data-dir", data_dir, "rm", "1")
            self.assertEqual(code, 0)
            code, out, _ = run_cli("--data-dir", data_dir, "gc")
            self.assertEqual(code, 0)
            self.assertIn("removed 1 blob", out)


if __name__ == "__main__":
    unittest.main()
